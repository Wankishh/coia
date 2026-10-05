# Offline / On-Prem Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Coia Agents as a private Docker appliance that a customer can load and run on an air-gapped host without source code, CDN access, or cloud LLMs.

**Architecture:** Build images once on a networked machine (`mongo:7`, `postgres:16-alpine`, tagged `coia-agent-harness:<version>`), `docker save` them into a transfer bundle, and on the customer host `docker load` + `docker compose -f docker-compose.offline.yml up`. Compose for delivery uses only `image:` (never `build:`). Admin CDN assets are vendored into `app/static/admin/` so the browser talks only to `:8000`. Ollama stays external to Compose (host or LAN) via `OLLAMA_BASE_URL` to keep the appliance footprint small. No auth in Phase A.

**Tech Stack:** Docker / Docker Compose, existing `Dockerfile` (Python 3.11-slim + uvicorn single worker), MongoDB 7, Postgres 16 Alpine, FastAPI static admin, Ollama (OpenAI-compatible) as the offline LLM runtime.

## Global Constraints

- Single uvicorn worker only — never `--workers > 1` (in-process tasks + APScheduler).
- Customer delivery: private image distribution; do **not** ship the git repo / source tree.
- Offline Compose file must use `image:` only — no `build:` keys on the customer path.
- Ollama is **not** baked into Compose by default (external host/LAN install).
- No authentication / roles in Phase A (deferred — see tickets 004 / 005).
- Keep install short: load images → compose up → point Ollama → smoke check. No ceremony.
- Prefer little host footprint: Docker Engine, published port `8000`, disk for volumes + models.
- Dev Compose (`docker-compose.yml`) may keep `build:` for engineers; offline path is separate.
- Version pin images used in the transfer bundle (`mongo:7`, `postgres:16-alpine`, harness tag).

---

## File structure (create / modify)

| Path | Responsibility |
| --- | --- |
| `deploy/docker-compose.offline.yml` | Customer Compose: `image:` only, same service topology as today |
| `deploy/.env.offline.example` | Minimal env for air-gap (Mongo, demo DB, Ollama URL, workspace) |
| `deploy/README.md` | Customer-facing install + Ollama offline notes + smoke checklist |
| `scripts/package_offline.sh` | Online build → tag → `docker save` → tarball layout |
| `scripts/vendor_admin_assets.sh` | Download fonts + EasyMDE + marked + DOMPurify into static tree |
| `app/static/admin/vendor/` | Vendored JS/CSS (easymde, marked, purify) |
| `app/static/admin/fonts/` | Self-hosted DM Sans, IBM Plex Mono, Outfit (+ CSS) |
| `app/static/admin/index.html` | Point at local vendor/font paths (no CDN / Google Fonts) |
| `docs/tickets/003-offline-installation.md` | Backlog ticket → this plan |
| `docs/tickets/004-auth-roles.md` | Later: auth + roles (stub) |
| `docs/tickets/005-external-clients.md` | Later: external company clients (stub) |

**Out of scope for Phase A product code:** auth middleware, multi-tenant tenancy, baking Ollama into Compose, multi-worker uvicorn, shipping source to customers.

**Phase B (mention only — separate tickets):** auth with roles; external company clients connecting to the platform.

---

## Phase A — Offline appliance package

### Task 1: Vendor admin CDN assets into static tree

**Files:**
- Create: `scripts/vendor_admin_assets.sh`
- Create: `app/static/admin/vendor/` (populated by script)
- Create: `app/static/admin/fonts/` (populated by script)
- Create: `app/static/admin/fonts/fonts.css`
- Modify: `app/static/admin/index.html` (replace Google Fonts + jsDelivr URLs)

**Interfaces:**
- Consumes: Current CDN URLs in `app/static/admin/index.html` (EasyMDE 2.18.0, marked 15.0.7, DOMPurify 3.2.4; Google Fonts families DM Sans / IBM Plex Mono / Outfit)
- Produces: Local paths served under `/admin/vendor/...` and `/admin/fonts/...` (same StaticFiles mount)

- [ ] **Step 1: Confirm current remote asset URLs**

Open `app/static/admin/index.html` and note the exact href/src values (as of plan writing):

- Google Fonts CSS: `fonts.googleapis.com/css2?...DM+Sans...IBM+Plex+Mono...Outfit...`
- `https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.css`
- `https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.js`
- `https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js`
- `https://cdn.jsdelivr.net/npm/dompurify@3.2.4/dist/purify.min.js`

- [ ] **Step 2: Write `scripts/vendor_admin_assets.sh`**

```bash
#!/usr/bin/env bash
# Download admin CDN assets into app/static/admin for air-gapped browsers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/app/static/admin/vendor"
FONTS="$ROOT/app/static/admin/fonts"
mkdir -p "$VENDOR" "$FONTS"

curl -fsSL -o "$VENDOR/easymde.min.css" \
  "https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.css"
curl -fsSL -o "$VENDOR/easymde.min.js" \
  "https://cdn.jsdelivr.net/npm/easymde@2.18.0/dist/easymde.min.js"
curl -fsSL -o "$VENDOR/marked.min.js" \
  "https://cdn.jsdelivr.net/npm/marked@15.0.7/marked.min.js"
curl -fsSL -o "$VENDOR/purify.min.js" \
  "https://cdn.jsdelivr.net/npm/dompurify@3.2.4/dist/purify.min.js"

# EasyMDE ships Font Awesome-like icon font refs; if CSS references relative
# font files, also pull those next to easymde.min.css or adjust paths after download.
# Inspect easymde.min.css for url(...) and fetch companions into $VENDOR as needed.

# Google Fonts: prefer downloading woff2 files via google-webfonts-helper
# (https://gwfh.mranftl.com) or `npm pack` of @fontsource packages, then write fonts.css.
# Minimum families/weights used by styles.css / index.html:
#   DM Sans: 400,500,600,700 (+ italic 400)
#   IBM Plex Mono: 400,500,600
#   Outfit: 500,600,700,800

cat > "$FONTS/fonts.css" <<'EOF'
/* Self-hosted — populated by scripts/vendor_admin_assets.sh */
@font-face {
  font-family: "DM Sans";
  font-style: normal;
  font-weight: 400 700;
  font-display: swap;
  src: url("./dm-sans-latin.woff2") format("woff2");
}
@font-face {
  font-family: "IBM Plex Mono";
  font-style: normal;
  font-weight: 400 600;
  font-display: swap;
  src: url("./ibm-plex-mono-latin.woff2") format("woff2");
}
@font-face {
  font-family: "Outfit";
  font-style: normal;
  font-weight: 500 800;
  font-display: swap;
  src: url("./outfit-latin.woff2") format("woff2");
}
EOF

# Replace the three @font-face blocks above with concrete per-weight files
# once you pick a download method; keep family names identical to styles.css.

echo "Vendored JS/CSS into $VENDOR"
echo "Add woff2 files under $FONTS and finalize fonts.css before committing."
```

Make executable:

```bash
chmod +x scripts/vendor_admin_assets.sh
```

- [ ] **Step 3: Run the vendor script (online machine)**

```bash
./scripts/vendor_admin_assets.sh
ls -la app/static/admin/vendor app/static/admin/fonts
```

Expected: vendor files present; font woff2 + finalized `fonts.css` present before commit.

- [ ] **Step 4: Point `index.html` at local assets**

In `app/static/admin/index.html`, remove the two Google Fonts `<link rel="preconnect"...>` tags and the Google Fonts stylesheet `<link>`. Replace with:

```html
<link rel="stylesheet" href="/admin/fonts/fonts.css" />
```

Replace EasyMDE CSS:

```html
<link rel="stylesheet" href="/admin/vendor/easymde.min.css" />
```

Replace bottom scripts:

```html
<script src="/admin/vendor/easymde.min.js"></script>
<script src="/admin/vendor/marked.min.js"></script>
<script src="/admin/vendor/purify.min.js"></script>
```

Keep `/admin/styles.css` and `/admin/app.js` as they are.

- [ ] **Step 5: Smoke-check admin offline in browser**

With harness running locally (`docker compose up` or `uvicorn`), open DevTools → Network, enable Offline (or block `fonts.googleapis.com` / `cdn.jsdelivr.net`). Reload `/admin/`.

Expected:

- No failed requests to external hosts
- EasyMDE editors still initialize (prompt fields)
- Markdown preview still renders (marked + DOMPurify)
- Fonts render (or fall back cleanly if a weight is missing — fix gaps before shipping)

- [ ] **Step 6: Commit**

```bash
git add scripts/vendor_admin_assets.sh \
  app/static/admin/vendor \
  app/static/admin/fonts \
  app/static/admin/index.html
git commit -m "$(cat <<'EOF'
feat: vendor admin CDN assets for air-gapped UI

Serve fonts, EasyMDE, marked, and DOMPurify from /admin so the console
works without internet on the operator browser.
EOF
)"
```

---

### Task 2: Customer offline Compose (image-only)

**Files:**
- Create: `deploy/docker-compose.offline.yml`
- Create: `deploy/.env.offline.example`
- Modify: none required in root `docker-compose.yml` (keep `build:` for dev)

**Interfaces:**
- Consumes: Image tags produced by Task 3 (`coia-agent-harness:<version>`, `mongo:7`, `postgres:16-alpine`)
- Produces: Compose stack reachable on host port `8000`, Mongo + demo Postgres on internal network only

- [ ] **Step 1: Draft `deploy/docker-compose.offline.yml`**

Mirror the service topology of root `docker-compose.yml`, but:

- Every service uses `image:` — never `build:`
- Harness image: `coia-agent-harness:${COIA_IMAGE_TAG:-latest}` (or a pinned default like `1.0.0`)
- `demo-db-seed` uses the **same** harness image with overridden `entrypoint` (no bind-mount of host `scripts/` — seed script is already `COPY`'d in `Dockerfile`)
- Demo SQL init: bake path already in image (`init_demo_db.sql`); for Postgres init mount, either (a) include a tiny `deploy/init_demo_db.sql` copy in the transfer bundle, or (b) document that first-boot seed runs via `demo-db-seed` only and drop the init mount for offline. Prefer (a) for parity: ship `deploy/init_demo_db.sql` as a copy of repo root file in the package script.
- Keep `extra_hosts: host.docker.internal:host-gateway` for host Ollama
- Publish only `8000:8000`
- Workspace volume: named volume `agent_workspaces` (not host `./data/...`) so customers need no source tree

Sketch:

```yaml
services:
  mongo:
    image: mongo:7
    volumes:
      - mongo_data:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 5s
      timeout: 5s
      retries: 10

  demo-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
      POSTGRES_DB: demo
    volumes:
      - demo_db_data:/var/lib/postgresql/data
      - ./init_demo_db.sql:/docker-entrypoint-initdb.d/init_demo_db.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U demo -d demo"]
      interval: 5s
      timeout: 5s
      retries: 10

  demo-db-seed:
    image: coia-agent-harness:${COIA_IMAGE_TAG:-latest}
    restart: "no"
    environment:
      DEMO_DATABASE_URL: postgresql+psycopg2://demo:demo@demo-db:5432/demo
    entrypoint: ["python", "scripts/load_demo_db.py"]
    depends_on:
      demo-db:
        condition: service_healthy

  coia-agent-harness:
    image: coia-agent-harness:${COIA_IMAGE_TAG:-latest}
    ports:
      - "8000:8000"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    env_file:
      - .env
    environment:
      MONGODB_URL: mongodb://mongo:27017
      MONGODB_DB: coia_agents
      DEMO_DATABASE_URL: postgresql+psycopg2://demo:demo@demo-db:5432/demo
      WORKSPACE_ROOT: /app/data/agent_workspaces
    volumes:
      - agent_workspaces:/app/data/agent_workspaces
    depends_on:
      mongo:
        condition: service_healthy
      demo-db:
        condition: service_healthy
      demo-db-seed:
        condition: service_completed_successfully

volumes:
  mongo_data:
  demo_db_data:
  agent_workspaces:
```

- [ ] **Step 2: Write `deploy/.env.offline.example`**

```bash
# Copy to .env next to docker-compose.offline.yml on the customer host.
COIA_IMAGE_TAG=latest
MONGODB_URL=mongodb://mongo:27017
MONGODB_DB=coia_agents
DEMO_DATABASE_URL=postgresql+psycopg2://demo:demo@demo-db:5432/demo
WORKSPACE_ROOT=/app/data/agent_workspaces
HARNESS_HOST=0.0.0.0
HARNESS_PORT=8000
CHAT_TIMEOUT_SECONDS=120

# Host Ollama (Docker → host). Change if Ollama runs on another LAN machine.
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Do **not** require cloud API keys for the offline happy path.

- [ ] **Step 3: Validate Compose file syntax**

```bash
docker compose -f deploy/docker-compose.offline.yml config
```

Expected: prints merged config; exit 0. Fail if any `build:` remains.

- [ ] **Step 4: Grep guard — no build keys in offline compose**

```bash
! grep -E '^\s*build:' deploy/docker-compose.offline.yml
```

Expected: no matches (shell `!` makes “no match” success).

- [ ] **Step 5: Commit**

```bash
git add deploy/docker-compose.offline.yml deploy/.env.offline.example
git commit -m "$(cat <<'EOF'
feat: add image-only Compose for offline appliance delivery

Customer stack loads prebuilt images without a source tree or build step.
EOF
)"
```

---

### Task 3: Online packaging script (`docker save` bundle)

**Files:**
- Create: `scripts/package_offline.sh`
- Create: `deploy/init_demo_db.sql` — either committed copy of root `init_demo_db.sql` or copied by the package script into the bundle (prefer package script copy into `dist/` so deploy stays DRY; if Compose references `./init_demo_db.sql`, the package script must place it beside `docker-compose.offline.yml` in the tarball)

**Interfaces:**
- Consumes: Root `Dockerfile`, `docker-compose.yml` image pins, `deploy/*`
- Produces: `dist/coia-offline-<version>.tar.gz` containing images archive + compose + env example + README

- [ ] **Step 1: Write `scripts/package_offline.sh`**

```bash
#!/usr/bin/env bash
# Build/pull images on a networked machine and produce a transferable offline bundle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$(date +%Y%m%d)}"
TAG="coia-agent-harness:${VERSION}"
OUT="$ROOT/dist/coia-offline-${VERSION}"
mkdir -p "$OUT"

echo "==> Building harness image ${TAG}"
docker build -t "$TAG" -t coia-agent-harness:latest "$ROOT"

echo "==> Pulling dependency images"
docker pull mongo:7
docker pull postgres:16-alpine

echo "==> Saving images"
docker save -o "$OUT/coia-images.tar" \
  "$TAG" \
  coia-agent-harness:latest \
  mongo:7 \
  postgres:16-alpine

echo "==> Copying deploy artifacts"
cp "$ROOT/deploy/docker-compose.offline.yml" "$OUT/docker-compose.offline.yml"
cp "$ROOT/deploy/.env.offline.example" "$OUT/.env.offline.example"
cp "$ROOT/init_demo_db.sql" "$OUT/init_demo_db.sql"
cp "$ROOT/deploy/README.md" "$OUT/README.md"

# Pin default tag in a small env hint file
printf 'COIA_IMAGE_TAG=%s\n' "$VERSION" > "$OUT/COIA_IMAGE_TAG.txt"

echo "==> Creating tarball"
mkdir -p "$ROOT/dist"
tar -C "$ROOT/dist" -czf "$ROOT/dist/coia-offline-${VERSION}.tar.gz" "coia-offline-${VERSION}"

echo "Bundle ready: $ROOT/dist/coia-offline-${VERSION}.tar.gz"
echo "Transfer that file to the customer host (USB/SCP). No source required."
```

```bash
chmod +x scripts/package_offline.sh
```

- [ ] **Step 2: Dry-run package on an online builder**

```bash
./scripts/package_offline.sh 1.0.0
ls -lh dist/coia-offline-1.0.0.tar.gz
tar -tzf dist/coia-offline-1.0.0.tar.gz | head
```

Expected: tarball lists `coia-images.tar`, compose, env example, README, `init_demo_db.sql`.

- [ ] **Step 3: Document that `dist/` is not committed**

Ensure `dist/` is in `.gitignore` (add if missing):

```gitignore
dist/
```

- [ ] **Step 4: Commit script + gitignore change**

```bash
git add scripts/package_offline.sh .gitignore
git commit -m "$(cat <<'EOF'
feat: add offline appliance packaging script

Build and docker-save harness + DB images into a transferable tarball.
EOF
)"
```

---

### Task 4: Customer-facing offline install docs

**Files:**
- Create: `deploy/README.md`

**Interfaces:**
- Consumes: Bundle layout from Task 3; Ollama external; smoke checks from Task 5
- Produces: Single short install guide operators can follow without Coia source access

- [ ] **Step 1: Write `deploy/README.md` with these sections only**

1. **Host requirements (minimal)**
   - Linux/macOS with Docker Engine + Compose plugin
   - Free host port `8000`
   - Disk: ~2–4 GB for images/volumes (plus Ollama model disk separately — often 4–40+ GB depending on models)
   - No git, no Node, no Python toolchain required on the customer host

2. **Install appliance (air-gap)**

```bash
# On transfer media / after copy:
tar -xzf coia-offline-<version>.tar.gz
cd coia-offline-<version>
docker load -i coia-images.tar
cp .env.offline.example .env
# Edit .env: set COIA_IMAGE_TAG from COIA_IMAGE_TAG.txt; set OLLAMA_BASE_URL if needed
docker compose -f docker-compose.offline.yml up -d
curl -sS http://127.0.0.1:8000/health
# Open http://127.0.0.1:8000/admin/
```

3. **Ollama (separate — not in Compose)**
   - Install Ollama on the Docker host (or a LAN box) using Ollama’s own offline/install docs for the OS
   - Online builder: `ollama pull <model>` then transfer model blobs / use `ollama create` / vendor model files per Ollama’s offline import path for the target version
   - Point harness: `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (default) or `http://<lan-ip>:11434/v1`
   - In admin UI: create/select an agent with provider `ollama` and a local model name (e.g. `llama3.2`)
   - Explicitly state cloud providers (OpenAI/Anthropic/etc.) need egress and are optional

4. **What is not included**
   - Source code / git repo
   - Auth (open admin console on port 8000 — put behind VPN/firewall)
   - Ollama binary/models inside the Compose stack

5. **Air-gap smoke checklist** (link content aligned with Task 5)

Keep the doc short — no install theater.

- [ ] **Step 2: Cross-link from root README (one paragraph)**

In root `README.md`, add a short “Offline / on-prem” pointer to `deploy/README.md` under deployment — do not duplicate the full guide.

- [ ] **Step 3: Commit**

```bash
git add deploy/README.md README.md
git commit -m "$(cat <<'EOF'
docs: add offline appliance install guide

Document load/compose/Ollama steps for air-gapped hosts without source.
EOF
)"
```

---

### Task 5: Air-gap smoke checklist (verify end-to-end)

**Files:**
- Modify: `deploy/README.md` (checklist section — finalize wording after a real dry run)

**Interfaces:**
- Consumes: Bundle from Task 3, vendored admin from Task 1, Ollama on host
- Produces: Pass/fail checklist operators and engineers share

- [ ] **Step 1: Simulate transfer on a clean Docker host**

Prefer a machine/VM with Docker but no project checkout:

```bash
tar -xzf dist/coia-offline-1.0.0.tar.gz
cd coia-offline-1.0.0
docker load -i coia-images.tar
cp .env.offline.example .env
# set COIA_IMAGE_TAG=1.0.0
docker compose -f docker-compose.offline.yml up -d
```

- [ ] **Step 2: Health**

```bash
curl -sS http://127.0.0.1:8000/health
```

Expected JSON includes `"status":"ok"` (or `"degraded"` only if Mongo failed — that is a fail for this checklist) and `"service":"coia-agent-harness"`.

- [ ] **Step 3: Admin loads with browser offline**

Open `http://127.0.0.1:8000/admin/`, DevTools → Network → Offline (or disconnect NIC). Hard reload.

Expected: console shell + CSS/JS/fonts/vendor all `200` from same origin; no CDN/Google Fonts errors.

- [ ] **Step 4: Ollama agent chat**

With Ollama running on the host and a model pulled/imported:

1. Ensure `.env` has `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`
2. In admin, create or edit an agent: provider `ollama`, model matching a local tag
3. Send a short chat message

Expected: non-error assistant reply; no cloud provider calls required.

- [ ] **Step 5: Confirm code not required on host**

```bash
# From the extract directory — should succeed with only deploy artifacts + images
ls docker-compose.offline.yml coia-images.tar .env init_demo_db.sql README.md
# There must be no app/ Python package required beside the running container
test ! -d app
```

Expected: `test ! -d app` succeeds in the customer extract dir.

- [ ] **Step 6: Record results + commit doc tweaks if any**

If paths/commands needed edits during the dry run, update `deploy/README.md` and commit:

```bash
git add deploy/README.md
git commit -m "docs: tighten offline smoke checklist after dry run"
```

---

### Task 6: Private image distribution notes (leak concern)

**Files:**
- Modify: `deploy/README.md` (short “Distribution” subsection)
- Optional create: `deploy/DISTRIBUTION.md` only if the README subsection would exceed ~15 lines

**Interfaces:**
- Consumes: Packaging output from Task 3
- Produces: Explicit policy: customers get image tarball + compose, not git

- [ ] **Step 1: Add Distribution subsection to `deploy/README.md`**

Cover:

- Ship `coia-offline-<version>.tar.gz` via private channel (customer portal, signed USB, SCP to jump host)
- Do **not** grant git access for on-prem installs
- Image contains application code (inevitable with Docker) — treat the tarball as confidential; customers agree not to redistribute
- Optional hardening later (not Phase A): private registry + `docker pull` over VPN, image signing, read-only rootfs — mention as future, do not implement now
- Rebuild/republish when releasing a new `<version>` tag

- [ ] **Step 2: Commit**

```bash
git add deploy/README.md
git commit -m "$(cat <<'EOF'
docs: clarify private image distribution for on-prem

Customers receive the appliance tarball, not the source repository.
EOF
)"
```

---

## Phase B — later (out of scope for this plan)

Track only via tickets; do not expand into tasks here:

- **Auth + roles** — `docs/tickets/004-auth-roles.md`
- **External clients / multi-tenant company access** — `docs/tickets/005-external-clients.md`

No implementation work for Phase B under this plan.

---

## Self-review (plan author)

| Spec item | Task |
| --- | --- |
| Build mongo/postgres/harness once online | Task 3 |
| docker save / transfer / load | Tasks 3, 4, 5 |
| Compose `image:` not `build:` | Task 2 |
| Vendor admin CDN assets | Task 1 |
| Document Ollama separately + `OLLAMA_BASE_URL` | Task 4 |
| Minimal host requirements | Task 4 |
| Air-gap smoke checklist | Task 5 |
| Private image, no source to customer | Tasks 3, 5, 6 |
| Single worker uvicorn unchanged | Global Constraints + existing Dockerfile CMD |
| No auth in Phase A | Global Constraints + Phase B tickets |
| Ollama external (small footprint) | Global Constraints + Tasks 2, 4 |

No TBD placeholders remain in task steps. Phase B is deliberately stubbed to tickets only.
