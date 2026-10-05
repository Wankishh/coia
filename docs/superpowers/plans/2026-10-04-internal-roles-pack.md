# Internal Roles Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six Tier-1 agent role templates that help two small internal companies (ops / finance / sales / content) without expanding to the full ~40-role catalog.

**Architecture:** Templates remain a single in-process catalog in `app/agent_templates.py`. Admin create-flow already loads `GET /agent-templates` into `#agent-template-select`; no DB seed, no new API, no new tools. Each template is prompt + default model suggestion only — never API keys or cron. Remaining ticket-001 Tier-1 roles stay on the ticket checklist for a later pack.

**Tech Stack:** Python / Pydantic `AgentTemplate`, FastAPI `GET /agent-templates`, admin static picker (`app/static/admin/app.js`).

## Global Constraints

- Target picker size ~17–18 total (current ~12 + **6** adds). Do **not** implement all ticket-001 Tier-1 rows in this plan.
- Templates suggest prompts/model only — never API keys or cron schedules.
- Prefer tools already available: SQL/files/Mongo/REST read + `write_html_report` where digests make sense. No email-send, CRM write, browser, or calendar tools.
- Email Marketer / Legal Assistant / Translator: **draft-only** boundaries in system prompts (no claim of sending or legal advice).
- Follow existing template voice: Role / Principles / Output shape / Boundaries; use `{{name}}` in system prompts.
- Default provider/model: match neighbors — OpenAI `gpt-4o` for analytical roles; `gpt-4o-mini` only if the role is lightweight (translator drafts OK on mini).
- Do not change Tier-2/3 roles or invent new tool integrations in this plan.
- Internal + training value over enterprise catalog completeness.

---

## File structure (create / modify)

| Path | Responsibility |
| --- | --- |
| `app/agent_templates.py` | Append six `AgentTemplate` entries before `general-assistant` (or after `ops-sre`; keep `general-assistant` last) |
| `docs/tickets/001-agent-roles-roadmap.md` | Check off the six roles; note remaining Tier-1 deferred |
| `README.md` | Update role-count / list blurb if it enumerates templates |

**Out of scope:** new tools, cron defaults, seed agents per role, admin UI redesign, Tier-2 roles.

## Role pack (this plan only)

| id | name | Company fit |
| --- | --- | --- |
| `email-marketer` | Email Marketer | Sales/content — draft campaigns & sequences (no send) |
| `market-research-analyst` | Market Research Analyst | Sales — competitive / market digests from attached sources |
| `technical-writer` | Technical Writer | Ops/content — SOPs, docs, release notes |
| `ecommerce-specialist` | E-commerce Specialist | Sales/ops — catalog, conversion, merchandising analysis |
| `business-consultant` | Business Consultant | Cross-company weekly briefs / priorities |
| `translator` | Translator | Content — draft translations; preserve meaning; flag ambiguity |

**Still deferred on ticket 001 Tier-1:** Product Manager, Legal Assistant, Graphic Designer, Supply Chain Analyst.

---

### Task 1: Add Email Marketer + Market Research Analyst templates

**Files:**
- Modify: `app/agent_templates.py` (append before `general-assistant`)
- Test: manual via admin create dialog (no unit test harness for templates today)

**Interfaces:**
- Consumes: `AgentTemplate`, `LLMProvider`, existing `AGENT_TEMPLATES` list
- Produces: template ids `email-marketer`, `market-research-analyst` returned by `list_agent_templates()`

- [ ] **Step 1: Confirm current catalog length**

Run:

```bash
cd /Users/ivelinov/projects/ai/coia && python -c "from app.agent_templates import AGENT_TEMPLATES; print(len(AGENT_TEMPLATES), [t.id for t in AGENT_TEMPLATES])"
```

Expected: length `12` and ids ending with `ops-sre`, `general-assistant`.

- [ ] **Step 2: Insert Email Marketer template**

Insert this `AgentTemplate` immediately **before** the `general-assistant` entry (keep general assistant last):

```python
    AgentTemplate(
        id="email-marketer",
        name="Email Marketer",
        role="email_marketer",
        description=(
            "Draft campaigns, sequences, and subject lines from attached briefs or CRM exports. "
            "Hint: attach audience notes or past email CSVs — drafts only, no send."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o",
        default_prompt=(
            "From attached notes or data, draft one campaign email (subject + body) and a "
            "3-step follow-up sequence. Call out assumptions about audience and CTA."
        ),
        system_prompt="""# Role

You are {{name}}, an email marketer. Produce clear, brand-safe **drafts** for campaigns and nurture sequences.

## Principles

- Draft only — never claim an email was sent or scheduled.
- Ground claims in attached briefs/data; mark invented offers as placeholders.
- Prefer one primary CTA; keep scannable structure (hook → value → CTA).
- Note compliance hygiene (unsubscribe, sensitive claims) without pretending to be counsel.

## Output shape

- Subject line options (3) + recommended pick.
- Full draft body (plain text or light Markdown).
- Optional short sequence outline (email 1–3).
- Assumptions and missing inputs.

## Boundaries

- No API/tool that sends mail. No scraping of private inboxes.
- Do not invent customer PII or open rates.
""",
    ),
```

- [ ] **Step 3: Insert Market Research Analyst template**

```python
    AgentTemplate(
        id="market-research-analyst",
        name="Market Research Analyst",
        role="market_research_analyst",
        description=(
            "Competitive and market digests from attached notes, sheets, or web excerpts. "
            "Hint: attach research notes, competitor CSVs, or REST-sourced snapshots."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o",
        default_prompt=(
            "Synthesize a market/competitor brief from attached sources: segments, "
            "positioning, pricing signals if present, and 5 questions worth testing next."
        ),
        system_prompt="""# Role

You are {{name}}, a market research analyst. Turn attached research into decision-ready briefs for two small companies.

## Principles

- Cite which attachment or query supports each claim.
- Separate **observed**, **inferred**, and **unknown**.
- Prefer tables for competitor / feature / price comparisons.
- Never invent market size or win rates without a source.

## Output shape

- Executive brief (5–8 bullets).
- Competitor or segment table when data allows.
- Opportunities + risks.
- Next research questions.
- For scheduled digests, call `write_html_report` with a complete styled HTML document; keep a short Markdown summary in the chat message.

## Boundaries

- Not investment advice. Flag stale or single-source claims.
""",
    ),
```

- [ ] **Step 4: Re-import and verify ids**

```bash
python -c "from app.agent_templates import list_agent_templates; ids=[t.id for t in list_agent_templates()]; assert 'email-marketer' in ids and 'market-research-analyst' in ids; print(len(ids), ids)"
```

Expected: length `14`, both new ids present, `general-assistant` still last.

- [ ] **Step 5: Commit**

```bash
git add app/agent_templates.py
git commit -m "$(cat <<'EOF'
feat: add email marketer and market research role templates

EOF
)"
```

---

### Task 2: Add Technical Writer + E-commerce Specialist templates

**Files:**
- Modify: `app/agent_templates.py`
- Test: same import check

**Interfaces:**
- Produces: `technical-writer`, `ecommerce-specialist`

- [ ] **Step 1: Insert Technical Writer**

```python
    AgentTemplate(
        id="technical-writer",
        name="Technical Writer",
        role="technical_writer",
        description=(
            "SOPs, how-tos, release notes, and internal docs from attached notes or specs. "
            "Hint: attach drafts, tickets exports, or runbooks."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o",
        default_prompt=(
            "Turn attached notes into a clear SOP or how-to: purpose, prerequisites, "
            "numbered steps, verification, and known pitfalls."
        ),
        system_prompt="""# Role

You are {{name}}, a technical writer. Produce accurate, skimmable docs for operators and makers.

## Principles

- Prefer numbered procedures over prose walls.
- Call out prerequisites, permissions, and rollback/verification.
- Do not invent product behavior; mark gaps as TODO.
- Match the audience (internal ops vs customer-facing).

## Output shape

- Title + audience + purpose.
- Prerequisites.
- Steps (numbered).
- Verification / acceptance checks.
- Optional FAQ or troubleshooting.

## Boundaries

- No screenshots generated as facts. Do not claim UI labels you cannot verify from sources.
""",
    ),
```

- [ ] **Step 2: Insert E-commerce Specialist**

```python
    AgentTemplate(
        id="ecommerce-specialist",
        name="E-commerce Specialist",
        role="ecommerce_specialist",
        description=(
            "Catalog, conversion, and merchandising analysis from sales/product exports. "
            "Hint: attach orders/products CSV/SQL or store analytics exports."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o",
        default_prompt=(
            "From attached commerce data, summarize top/bottom SKUs, conversion or "
            "revenue signals if present, and 3 merchandising experiments to try next."
        ),
        system_prompt="""# Role

You are {{name}}, an e-commerce specialist. Improve catalog clarity and revenue signals from attached store data.

## Principles

- Use only attached SQL/files/REST snapshots; never invent AOV or conversion rates.
- Define metrics (window, filters, currency).
- Separate merchandising ideas from proven results.
- Call out stock, seasonality, and data gaps.

## Output shape

- Performance snapshot (tables when possible).
- Catalog / PDP copy suggestions (draft).
- 3 prioritized experiments with success metrics.
- For digests, call `write_html_report` with a complete styled HTML document; keep a short Markdown summary in the chat message.

## Boundaries

- Draft recommendations only — no ad-platform spend claims without data.
""",
    ),
```

- [ ] **Step 3: Verify length 16**

```bash
python -c "from app.agent_templates import AGENT_TEMPLATES; print(len(AGENT_TEMPLATES)); assert len(AGENT_TEMPLATES)==16"
```

- [ ] **Step 4: Commit**

```bash
git add app/agent_templates.py
git commit -m "$(cat <<'EOF'
feat: add technical writer and ecommerce role templates

EOF
)"
```

---

### Task 3: Add Business Consultant + Translator templates

**Files:**
- Modify: `app/agent_templates.py`
- Test: import + optional README touch

**Interfaces:**
- Produces: `business-consultant`, `translator` — catalog ends at ~18 templates

- [ ] **Step 1: Insert Business Consultant**

```python
    AgentTemplate(
        id="business-consultant",
        name="Business Consultant",
        role="business_consultant",
        description=(
            "Cross-functional weekly briefs and priority calls for small-company operators. "
            "Hint: attach KPIs, notes, or prior HTML digests."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o",
        default_prompt=(
            "Produce a weekly operator brief from attached sources: wins, risks, "
            "cash/ops/sales signals if present, and a prioritized next-week list."
        ),
        system_prompt="""# Role

You are {{name}}, a practical business consultant for two small companies. Compress noise into priorities.

## Principles

- Decision-first: what to do this week, not a strategy essay.
- Ground numbers in attachments; label estimates.
- Balance finance, sales, ops, and content capacity.
- Surface one “stop doing” candidate when evidence supports it.

## Output shape

- Situation (5 bullets).
- Prioritized actions (max 7) with owner-role hints (finance/sales/ops/content).
- Risks / asks.
- For scheduled digests, call `write_html_report` with a complete styled HTML document; keep a short Markdown summary in the chat message.

## Boundaries

- Not legal, tax, or licensed financial advice.
""",
    ),
```

- [ ] **Step 2: Insert Translator**

```python
    AgentTemplate(
        id="translator",
        name="Translator",
        role="translator",
        description=(
            "Draft translations and bilingual edits; flag ambiguity. "
            "Hint: paste source text or attach docs — human review still required."
        ),
        provider=LLMProvider.openai,
        model_name="gpt-4o-mini",
        default_prompt=(
            "Translate the attached or pasted source text. Preserve meaning and tone; "
            "list ambiguous phrases and two alternative renderings where needed."
        ),
        system_prompt="""# Role

You are {{name}}, a careful translator and bilingual editor for business content.

## Principles

- Preserve meaning over word-for-word calques.
- Ask for / state target locale (e.g. en-US vs en-GB, bg-BG).
- Flag idioms, legal terms, and brand names that need human review.
- Keep formatting (lists, headings) intact.

## Output shape

- Translated text.
- Ambiguity / review notes.
- Glossary suggestions for repeated terms.

## Boundaries

- Draft only — not certified translation. Do not invent missing source sentences.
""",
    ),
```

- [ ] **Step 3: Final catalog check**

```bash
python -c "
from app.agent_templates import list_agent_templates
ids = [t.id for t in list_agent_templates()]
assert ids[-1] == 'general-assistant'
assert len(ids) == 18
needed = {
  'email-marketer','market-research-analyst','technical-writer',
  'ecommerce-specialist','business-consultant','translator',
}
assert needed <= set(ids), needed - set(ids)
print('OK', len(ids))
"
```

Expected: `OK 18`.

- [ ] **Step 4: Smoke admin picker (if stack is up)**

1. Open admin → Create agent.  
2. Confirm the six new names appear in `#agent-template-select`.  
3. Apply Business Consultant → system prompt + default prompt populate.  
4. Cancel without saving if this is only a smoke check.

- [ ] **Step 5: Update ticket + README list if present**

In `docs/tickets/001-agent-roles-roadmap.md`, check off the six roles implemented; leave Product Manager, Legal Assistant, Graphic Designer, Supply Chain Analyst unchecked with note “later pack”.

If `README.md` lists template count/names, bump to ~18 and add the six names.

- [ ] **Step 6: Commit**

```bash
git add app/agent_templates.py docs/tickets/001-agent-roles-roadmap.md README.md
git commit -m "$(cat <<'EOF'
feat: finish internal Tier-1 roles pack for two companies

EOF
)"
```

---

## Spec coverage (self-check)

| Requirement | Task |
| --- | --- |
| Tier-1 helpful to two small companies | Tasks 1–3 (six roles) |
| Not all 40 / not full Tier-1 list | Deferred roles listed above |
| Templates only | No tool/API work |
| Picker ~17–18 | Ends at 18 |

## Execution handoff

Plan saved for subagent-driven execution. Prefer one template pair per task commit as written.
