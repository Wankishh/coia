# Coia Agents

Monolithic agent harness: **FastAPI + LangGraph + APScheduler + MongoDB** in one process.

Agents are configured via REST, optionally scheduled with cron, and executed as LangGraph ReAct-style tool-calling agents. Execution steps stream into MongoDB `ExecutionLog` documents in near real time. A Postgres **demo-db** is available as a read-only SQL tool target.

## Stack

| Service | Role |
|---------|------|
| `coia-agent-harness` | API, agent runner, scheduler |
| `mongo` | AgentConfig + ExecutionLog storage |
| `demo-db` | Read-only Postgres with demo sales schema (`customers`, `products`, `employees`, `orders`, `order_items`, `sales_transactions`, plus `demo_info` / `schema_version`) |
| `demo-db-seed` | One-shot job that re-applies `init_demo_db.sql` on every `compose up` (does not wipe the volume) |

## Quick start

### 1. Configure environment

```bash
cp .env.example .env
# Harness runtime does not need OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY.
# LLM keys are stored per-agent (admin UI or seed --api-key).
```

### 2. Start the stack

```bash
docker compose up --build -d
```

#### Demo DB persistence

- The named volume `demo_db_data` keeps Postgres data across container restarts.
- `docker-entrypoint-initdb.d` runs `init_demo_db.sql` only when that volume is **empty** (first boot).
- On every `compose up`, the one-shot `demo-db-seed` service waits for a healthy `demo-db` and re-applies the same SQL via `scripts/load_demo_db.py` (DROP + CREATE + reseed). Schema and seed data stay current without `down -v`.
- Agents can discover the dataset with `SELECT * FROM demo_info;`.

Force a reload without deleting the volume:

```bash
python scripts/load_demo_db.py
# or:
docker compose up demo-db-seed
```

Wipe Postgres entirely (rare — resets all DB files):

```bash
docker compose down -v && docker compose up --build -d
```

Wait until health is green:

```bash
curl http://localhost:8000/health
```

### 3. Seed the demo Finance Ops agent

The seed script **writes the key onto the agent** (`api_key`). Pass `--api-key`, or set `SEED_AGENT_API_KEY` / `OPENAI_API_KEY` (etc.) only as a one-time convenience for seed — those env vars are not read when agents run.

```bash
# From host (requires httpx + python-dotenv), or:
docker compose exec coia-agent-harness python scripts/seed_demo.py --api-key "$OPENAI_API_KEY" --run
```

Or without Docker exec:

```bash
pip install httpx python-dotenv
python scripts/seed_demo.py --base-url http://localhost:8000 --api-key sk-... --run
```

You can also create/edit agents in the admin console and paste the API key there — no harness env key required.

Seed persona defaults to **Finance Ops** (FP&A / sales-finance analytics on the demo SQL source) and is overridable via `SEED_AGENT_*` env vars (see `.env.example`).

Built-in role templates (`GET /agent-templates`, 18 total): Finance Ops, Data Analyst, Sales Ops, Inventory Ops, Marketing Ops (analytics), Content Writer, Social Marketer, Research Assistant, Customer Support Agent, Exec Brief Writer, Ops / SRE Assistant, Email Marketer, Market Research Analyst, Technical Writer, E-commerce Specialist, Business Consultant, Translator, General Assistant.

### 4. View logs / executions

```bash
# List agents
curl http://localhost:8000/agents

# Manual run (202 + execution_id)
curl -X POST http://localhost:8000/agents/<agent_id>/run \
  -H 'Content-Type: application/json' \
  -d '{}'

# Poll a single execution (tool_calls stream as the run progresses)
curl http://localhost:8000/executions/<execution_id>

# Agent execution history
curl http://localhost:8000/agents/<agent_id>/logs
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 5. Open the admin console

Full console (agents CRUD, run, executions, chat HTML reports, health):

[http://localhost:8000/admin/](http://localhost:8000/admin/)

## API

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/health` | Liveness + mongo / scheduler status |
| `GET` | `/agent-templates` | Built-in role templates for admin create (no secrets / no cron) |
| `POST` | `/agents` | Create agent (reschedules cron if set) |
| `GET` | `/agents` | List agents |
| `GET` | `/agents/{id}` | Get agent |
| `PATCH` | `/agents/{id}` | Update agent (reschedule cron on change) |
| `DELETE` | `/agents/{id}` | Delete agent + unschedule |
| `POST` | `/agents/{id}/run` | `202 {execution_id}`; background `asyncio.create_task` |
| `GET` | `/agents/{id}/logs` | Recent execution logs |
| `POST` | `/agents/{id}/chats` | Create chat conversation `{ id }` (Mongo `conversations`) |
| `GET` | `/agents/{id}/chats` | List chats (`id`, `title`, `updated_at`) |
| `GET` | `/chats/{id}` | Full transcript |
| `POST` | `/chats/{id}/messages` | `{ content }` — sync agent reply (uses system_prompt + tools/sources; no ExecutionLog) |
| `POST` | `/chats/{id}/messages/stream` | Same body; **SSE** stream (`token`/`delta`, `tool`, `done`, `error`). Admin Chat UI default. |
| `POST` | `/chats/{id}/cancel` | Best-effort cancel of an in-flight chat stream |
| `GET` | `/chats/{id}/messages/{index}/html` | HTML report body for iframe preview |
| `POST` | `/chats/{id}/attachments` | Upload a file into the chat (`multipart`) |
| `POST` | `/chats/{id}/read` | Mark session read (`last_read_at`) |
| `POST` | `/chats/{id}/handoff` | Send latest (or indexed) HTML report to handoff agent |
| `GET` | `/usage?days=7` | Rough usage meter by agent/day |
| `GET` | `/activity` | Live in-flight runs + chat streams `{ items, count }` |
| `GET` | `/executions/{id}` | Single execution (incl. HTML) |
| `POST` | `/executions/{id}/cancel` | Best-effort cancel of a running execution |
| `GET` | `/providers/{provider}/models` | Live model list (`openai` \| `anthropic` \| `google` \| `openrouter`); optional `api_key` query or `X-Api-Key` header |
| `POST` / `GET` / `PATCH` / `DELETE` | `/sources`, `/sources/{id}` | Data Sources library CRUD (secrets redacted on GET) |
| `POST` | `/sources/test` | Probe unsaved config `{ ok, message, latency_ms? }` (SQL `SELECT 1` / Mongo `ping` / files folder) |
| `POST` | `/sources/{id}/test` | Probe saved source (optional body overrides; secrets merge from storage) |
| `GET` / `POST` | `/sources/{id}/files` | List / upload files for a `files` library source |
| `GET` / `PUT` / `DELETE` | `/sources/{id}/files/{path}` | Read / update text / delete a library source file |
| `GET` | `/admin/` | Admin console (agents, chat, activity, sources, executions, system) |

**Concurrency:** if an agent already has `status=running`, a **manual** run returns **409**; a **cron** trigger skips and logs.

**Chat:** From **Agents** in the admin console, use **Chat** on a row or in the detail pane. Conversations are stored separately from runs (no `ExecutionLog`, so chat does not contend with the single-running claim). The admin UI streams via `POST /chats/{id}/messages/stream` (SSE); the sync `POST /chats/{id}/messages` endpoint remains available. Default timeout `CHAT_TIMEOUT_SECONDS=120`. Cancel with the composer **Cancel** button (`AbortController` + `POST /chats/{id}/cancel`). After `done`, the UI always `GET /chats/{id}` and renders HTML report cards from `message.html` (iframe via `/chats/{id}/messages/{index}/html`). Paperclip uploads go to `POST /chats/{id}/attachments`.

**Reports:** HTML reports are chat/session-only (cards + Expand in Chat; Open HTML on Executions). Legacy `/admin/reports` redirects to Chat; there is no top-level Reports gallery or `GET /reports`.

**Activity:** Admin **Activity** nav lists running `ExecutionLog`s and in-flight chat streams (polled ~2.5s). Cancel per item via `/executions/{id}/cancel` or `/chats/{id}/cancel`. Sessions filter **Runs only** focuses Agent runs inboxes. Chat nav badge sums per-session `unread_count` (assistant replies / run results newer than `last_read_at`).

**Source test:** Data sources dialog / detail **Test connection** calls `/sources/{id}/test` (or `/sources/test` for unsaved drafts). Attached SQL schemas are injected into the system prompt (capped) when available.

**Compose note:** Mongo/Postgres host ports are not published by default. Uncomment `ports:` in `docker-compose.yml` for local DB tools. Harness stays on `8000`.

No auth in this MVP.

## Agent config fields

**Write (create / patch):** `name` (display / persona name, e.g. Josh), `role`, `system_prompt`, `provider` (`openai` \| `anthropic` \| `google` \| `openrouter` \| `ollama`), `model_name`, `api_key` (required on create for cloud providers; optional/empty for `ollama`; optional on patch — omit to keep), `base_url?` (optional OpenAI-compatible endpoint; meaningful for `ollama`), `enabled_tools[]` (optional; admin UI sends `[]`), `cron_schedule?`, `default_prompt?`, `source_ids[]` (ordered library attachments), `handoff_agent_id?` (optional peer agent for HTML report handoff). Legacy `sources[]` (embedded full configs) is still accepted briefly when `source_ids` is empty.

**Prompt placeholders:** before chat/run LLM calls, `{{name}}` / `{{agent_name}}`, `{{role}}`, `{{provider}}`, `{{model}}` / `{{model_name}}` in `system_prompt` and user/default prompts are replaced from the agent config.

OpenRouter uses OpenAI-compatible chat at `https://openrouter.ai/api/v1` with model ids like `openai/gpt-4o` or `anthropic/claude-3.5-sonnet`. The admin console fetches model dropdowns from `/providers/{provider}/models` (falls back to a small static list when the upstream API is unavailable or a key is required but missing).

### Local Ollama

Talk to an **existing** Ollama on the host or LAN — Coia does not run or pull models for you.

1. Install/start Ollama on the host and pull a model (`ollama pull llama3.2`).
2. Create an agent with `provider: ollama`, a local `model_name` (e.g. `llama3.2`), and **no API key**.
3. Optional `base_url` overrides the default `OLLAMA_BASE_URL` (`http://host.docker.internal:11434/v1`). From the harness container that hostname reaches the Docker host (Compose sets `extra_hosts: host.docker.internal:host-gateway` for Linux). For a LAN box use e.g. `http://192.168.1.10:11434/v1`.
4. Model lists and readiness probes hit Ollama’s OpenAI-compatible `/v1/models` (or native `/api/tags`) — no cloud key required.

**Read (GET / list):** same fields except secrets are redacted — responses include `api_key_set: bool` and never echo `api_key`. Attached sources appear as summaries (`id`, `title`, `type`, `description`) plus `source_ids`. Full source configs (with redacted secrets) live on `/sources`.

Also: `id`, `created_at`, `updated_at`.

### Data Sources library

Sources are **first-class library documents** in Mongo (`data_sources`), managed under **Data sources** in the admin console. Agents **attach** them via `source_ids` instead of embedding full connection configs.

| Field | Notes |
|-------|--------|
| `id` | UUID (auto if omitted) |
| `title` / `description` | Markdown OK — explain what the source is and what the agent can do with it |
| `type` | `sql` \| `nosql` \| `files` |
| `config` | Type-specific object (same shapes as before) |
| `created_at` / `updated_at` | Library metadata |

- **sql** — `{ engine: postgresql\|mysql\|sqlite, connection_string?, ssh? }`. Runtime resolves attached SQL sources into read-only `run_sql_query` tools (first → `run_sql_query`; additional get suffixed names). If no SQL source is attached, the tool falls back to `DEMO_DATABASE_URL`.
- **nosql** — `{ engine: mongodb, connection_string?, ssh? }`. Persisted + editable; **query tool execution is deferred**.
- **files** — `{ path_prefix? }`. Files live under `data/agent_workspaces/_library/{source_id}/` (shared). Sandbox tools mount attached file sources at `sources/{source_id}/` for the agent. Upload / list / edit / delete via `/sources/{id}/files`.
- **ssh** (sql/nosql) — `{ enabled, host, port, username, auth: password\|key, password?, private_key?, remote_host?, remote_port? }`. Credentials stored plaintext for MVP. When `enabled`, the SQL tool opens an `sshtunnel` per query.

**Migration / compat:** Older agents may still have embedded `sources[]`. On read/run, the harness prefers `source_ids` (library lookup); if `source_ids` is empty it falls back to embedded blobs. New admin UI writes `source_ids` only.

Admin: markdown editors for agent prompts and source descriptions; agent form uses an **Attach sources** checklist (link to Data sources). Enabled-tools checkboxes remain removed (`enabled_tools: []` = all tools).

### Enabled tools

- `sandbox_file` / `read_file` / `write_file` / `list_files` — agent workspace under `./data/agent_workspaces/{agent_id}/`, plus attached library file sources under `sources/{source_id}/`
- `sql` / `run_sql_query` — read-only SQL (`SELECT` / `WITH` / `SHOW` / `EXPLAIN`) against attached SQL library sources or `DEMO_DATABASE_URL`
- `write_html_report` — preferred path for HTML; also extracted from the final answer as fallback

If `enabled_tools` is empty, all tools are enabled.

### Cron / schedule

Stored as a standard 5-field crontab string on `cron_schedule` (or `null` when off), e.g. `0 9 * * 1-5`. The admin console exposes presets (Off / every minute / 5 / 15 / hourly / daily / weekly / custom crontab). Cron only triggers runs; all CRUD is on the harness API.

## Project layout

```
app/
  main.py           # lifespan: mongo + scheduler; mounts /admin
  static/admin/     # console SPA (HTML/CSS/JS)
  config.py         # pydantic-settings
  models/           # AgentConfig, DataSource, Conversation, ExecutionLog
  api/              # agents, chats, sources, executions, health
  services/         # repos, LLMFactory, AgentRunner, ChatService, source resolve/files
  tools/            # sandbox file, SQL, write_html_report
  scheduler.py      # APScheduler AsyncIOScheduler
scripts/seed_demo.py
scripts/load_demo_db.py   # re-apply demo schema/data to DEMO_DATABASE_URL
init_demo_db.sql          # idempotent demo schema + demo_info catalog
docker-compose.yml        # demo-db + demo-db-seed one-shot
```

## Local development (without Compose for the app)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Start mongo + demo-db via compose (re-enable DB ports in docker-compose.yml for host access), then:
export MONGODB_URL=mongodb://localhost:27017
export DEMO_DATABASE_URL=postgresql+psycopg2://demo:demo@localhost:5432/demo
uvicorn app.main:app --reload --port 8000
```

> **Do not run uvicorn with `--workers > 1`.** The harness keeps in-process background tasks and a single APScheduler instance; multiple workers break run tracking, cron ownership, and graceful shutdown.

## Known limitations / TODOs

- No authentication or multi-tenancy (API keys on agents / source DB credentials are stored in Mongo; protect the admin/API surface in real deployments)
- Background runs use in-process `asyncio.create_task` (interrupted runs are marked failed on restart; no Redis/Celery by design)
- Cron expressions are standard 5-field crontab only (admin UI maps common presets)
- HTML charting is plain HTML/CSS (no JS chart library bundled)
- Single-process deployment only (see uvicorn workers note above); concurrent runs are claimed via a Mongo partial unique index on `agent_id` where `status=running`
- Agents created before the `api_key` migration (`api_key_env_var`) must be re-created or patched with `api_key`
- NoSQL (Mongo) source **runtime query tool** not wired yet (config + UI only)
- SSH tunnels for SQL are best-effort per query via `sshtunnel`; prefer direct connections for the demo path
