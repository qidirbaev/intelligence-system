# SIE build plan: small tasks (15-20 min each)

Source of truth for scope: the TZ (v0.1) and `docs/ARCHITECTURE.md`.
Each task is one working session: implement, test, update this file, hand over a commit.

## Run protocol (definition of done)

1. Start a run by naming the task ("T04", or "next"). Push the previous result to GitHub, or upload the zip.
2. The run reads `TASKS.md`, `docs/ARCHITECTURE.md` and `docs/TRACEABILITY.md`, then implements **only that task**.
3. **Run the whole project:** `python tools/verify.py` (clean virtualenv, lint, all tests with zero skips,
   migrations through the CLI, the demo, the requirements register). It must be green.
4. Extend `tools/demo.py` so the demo shows what the task added.
5. Update `docs/TRACEABILITY.md` (status, tasks, evidence). The checker fails if a status contradicts this file,
   if cited evidence does not exist, or if a task is not asked for by any requirement.
6. Check against your brief: anything that differs from what you asked goes into the Deviations table, and
   items that need your decision are called out in the hand-over message.
7. Deliver the zip (it contains the fresh `docs/VERIFICATION.md`). If a task overruns ~20 minutes, stop at a clean
   point, mark it `partial` and list what is left.
8. Tests never contact Telegram or any third party (enforced by a network guard). Tests that need PostgreSQL carry
   `@pytest.mark.integration`.
9. Compliance first: no code path may read a source without a valid access basis (TZ section 2).

Legend: `[x]` done, `[~]` partial, `[ ]` not started.

## Phase 1: Skeleton

| | ID | Task | Deliverables | Done when |
|---|---|---|---|---|
| [x] | T01 | Repo scaffold | pyproject, package layout, CLI stub, compose (pgvector), CI, docs | `pytest` and `ruff` pass |
| [x] | T02 | Settings, logging, DB session | pydantic-settings config, JSON logging, SQLAlchemy engine/session, provider allow-list config | config loads from env; session opens (Postgres if available in sandbox, else SQLite) |
| [x] | T03 | Migration 1 + models | Alembic init; persons, sources, access_basis, agent_state, policy_versions, audit_log; `tenant_id` everywhere | migration up/down works; repo tests pass |
| [x] | T03a | Verification harness | `tools/verify.py`, `tools/demo.py`, requirements register `docs/TRACEABILITY.md` with checker, tripwire tests, network guard | `python tools/verify.py` is green |
| [x] | T04 | Migration 2 + models | content_items, decisions, rechecks, audit_samples, dead_letters, budget_counters, **operator_tasks** (gap found in the TZ: CG-4 needs a queue for access problems) | unique key (source_id, platform_msg_id, kind) enforced; upsert test |
| [x] | T05 | Permission engine | `compliance/`: access-basis checks CG-1..CG-3, expiry/revocation, denial logging | source without valid basis is always denied; comments denied unless allowed |
| [ ] | T06 | Policy bundle schema | pydantic models for the YAML bundle, loader, example `policies/policy_v0001.yaml` | example validates; bad bundles give clear errors |
| [ ] | T07 | Three-valued logic + conditions | TRUE/FALSE/UNKNOWN, all/any/not, condition registry (source_tag, text_matches_topic, view_count_gte, ...) | property-based tests for the truth tables |
| [ ] | T08 | Rule evaluator | first-match, `on_unknown`, DEFER/recheck info, Decision objects with reasons | table-driven tests incl. stale metrics -> UNKNOWN |
| [ ] | T09 | Policy manager + CLI | validate (refs, permissions within bases), publish, `effective_from`, active-version lookup, `sie policy ...` | v13 published while v12 active: switch exactly at effective time |
| [ ] | T10 | Language engine A | NFKC, apostrophe unification, Uzbek Cyrillic -> Latin transliteration | corpus tests (>=50 lines) pass |
| [ ] | T11 | Language engine B | script detection, language ID (uz/ru/mixed/other), keyword stem compiler + suffix-tolerant matcher, SimHash | matching works across Cyrillic/Latin/Russian fixtures |
| [ ] | T12 | Envelope + idempotent ingest | envelope model, upsert into content_items, decision write | same envelope twice -> one row |
| [ ] | T13 | Job queue + workers | Postgres `SKIP LOCKED` queue, leases, backoff, dead letters | killed worker -> job re-leased, no duplicates |
| [ ] | T14 | Scheduler + agent state | `agent_state`, next_check_at from posting rate, envelope clamps, **calls `check_access` / `granted_actions` when scheduling a fetch (first of the two CG-2 checks)** | interval never leaves the envelope |
| [ ] | T15 | Adapter interface + fake adapter + E2E | `SourceAdapter` protocol, FakeAdapter, pipeline adapter -> ingest -> normalize -> L0 -> decision, **`GatedAdapter`: wraps every adapter and calls `require_access` before each fetch, metrics refresh and comment read (the second CG-2 check)** | synthetic posts flow end to end (Phase 1 milestone) |
| [ ] | T16 | DROP handling + retention | null text on DROP, audit samples with TTL, retention job (purges expired audit samples and dead letters), **revocation hook: revoking an access basis flags that source's items for review or deletion (CG-7)** | dropped text gone; samples expire |
| [ ] | T17 | DEFER rechecks | decaying schedule, metric freshness, re-evaluate under **current** policy | pending recheck uses new version after publish |
| [ ] | T18 | Telegram adapter (read-only) | Telethon adapter behind the gate, error classification (flood wait, ban), encrypted session helper, dev runbook | unit tests with mocked client; never runs in CI |

## Phase 2: Understanding

| | ID | Task | Deliverables | Done when |
|---|---|---|---|---|
| [ ] | T19 | Embedder | interface, fake embedder, sentence-transformers implementation, pgvector column with numpy fallback | similar texts score higher than unrelated ones |
| [ ] | T20 | L1 clustering | assign/create events, centroid, time window | 200 reposts -> 1 event; unrelated -> separate |
| [ ] | T21 | Escalation | score, controller, `research_tasks`, one open task per event, material-change re-escalation | budget exhausted -> no new task |
| [ ] | T22 | LLM client + budgets | provider interface, allow-list enforcement, FakeLLM, budget counters, prompt registry | non-allow-listed provider refused |
| [ ] | T23 | Brain tasks | `event_summarize`, `stance_extract`, schema validation, evidence ids, version stamps | output without evidence ids rejected |
| [ ] | T24 | Views + read API | SQL views, FastAPI endpoints for topics, events, stances | endpoints return seeded demo data |

## Phase 3: Comments and evaluation

| | ID | Task | Deliverables | Done when |
|---|---|---|---|---|
| [ ] | T25 | Comments path A | gated comment fetch hook (CG-3), counting, reproducible sampling, Wilson interval | CI width shrinks with sample size |
| [ ] | T26 | Comments path B | rules + classifier interface, `coordinated_burst`, `attention_queue`, retention, hash-only authors | no author names stored; queue items expire |
| [ ] | T27 | Labeled sets + eval CLI | file formats, `sie eval ...` (recall, precision, F1, agreement) | metrics computed on a sample set |
| [ ] | T28 | Budget manager | daily caps, queue-depth thresholds, degraded mode, reserved on-demand share | load test enters and leaves degraded mode |

## Phase 4: Demo

| | ID | Task | Deliverables | Done when |
|---|---|---|---|---|
| [ ] | T29 | Mode B research | plan -> retrieve -> synthesize -> verify, report schema | unsupported statements removed or marked |
| [ ] | T30 | Dashboard | Streamlit pages: overview, topic, attention, ask, policy | pages render on demo data |
| [ ] | T31 | Observability | `/metrics`, operations page, audit-sample recall estimate | counters visible per stage |
| [ ] | T32 | Hardening + demo | chaos/replay/compliance suites, demo script, README | acceptance criteria AC-1..AC-8 checked |

## Notes and follow-ups

- T02: unit tests use in-memory SQLite; `@pytest.mark.integration` tests use real PostgreSQL 16 + pgvector
  (`make up`, or a local server). Set `SIE_TEST_DATABASE_URL` to point them elsewhere; they skip if unreachable.
- T02: `sie.compliance.providers.ProviderRegistry` is the CG-6 allow-list (default deny). T22 must route every
  LLM/embedding call through `registry.require(...)`.
- T02: `sie.logging_setup` redacts secret-looking extra fields; never put credentials in log messages themselves.
- Telegram permission (Phase 0 in the TZ) runs in parallel; until it is granted, only own channels and synthetic data are used.
- Packages pinned loosely for now; pin exact versions at T32.
- T03: migrations are hand-written and self-contained (`src/sie/storage/migrations/versions/`); a test compares
  models with the migrated schema, so a model change without a migration fails CI. Constraint names come from the
  naming convention in `storage/base.py`; give CHECK constraints a short `name=` (the convention prefixes it).
- T03: **for T04**: add models in `storage/models/` and a new revision `0002`; extend `ALL_TABLES` in
  `tests/conftest.py` (the Postgres test fixture TRUNCATEs that list); extend `EXPECTED_TABLES` and the
  `0001` head assertion in `tests/test_migrations.py`.
- T03: datetimes are UTC-aware only (`UTCDateTime` rejects naive values). Enums are plain text + CHECK.
  `audit_log` is append-only (Postgres trigger). `access_basis` rows are never deleted, only revoked.
- T03: `storage/repos.py` helpers never commit; the caller owns the transaction (`session_scope`).
- T03a: run `python tools/verify.py` after every task. I proved it is not a rubber stamp by breaking things on
  purpose: a task/status contradiction, an undeclared dependency (only the clean-room run catches it) and a stopped
  PostgreSQL (nothing silently skips). Add new evidence to `docs/TRACEABILITY.md` when a task lands.
- T03a: `tests/conftest.py` blocks every non-loopback connection during tests (requirement A-08).
- T03a: psycopg may log `error ignored terminating <psycopg.Pipeline ...>` (intermittently) after a deliberately
  rejected INSERT. Rows are rolled back and all checks pass, so it is treated as harmless noise and silenced in the
  demo only. If it ever appears in real logs during normal operation, investigate (SQLAlchemy insertmanyvalues +
  psycopg pipeline mode).
- T04: the schema itself enforces requirement U-06: an item with status `dropped` cannot hold `text_raw` or
  `text_norm` (CHECK `dropped_has_no_text`). T16 only has to null the text and keep ids/hashes/decision.
- T04: `repos_content.upsert_content_item` is the idempotent insert (unique key `source_id + platform_msg_id + kind`,
  an existing item is never overwritten). T12 should build on it instead of writing another upsert.
- T04: `audit_samples` and `dead_letters` have a mandatory `expires_at`; the purge job is T16. `budget_counters`
  exists; T28 adds the atomic increment. `operator_tasks` details are redacted and links must be plain https.
- T04 gap found: CG-7 says revoking a basis must flag derived data, but no task covered it; added to T16.
- Reminder: after a break, PostgreSQL may be down and database tests silently SKIP under plain `pytest`.
  `python tools/verify.py` treats skips as failures, so always finish with it.
- T05: the gate API is `sie.compliance.permission`: `evaluate_access` (pure), `check_access(session, ...)` (never
  raises, logs denials inside YOUR transaction) and `require_access(session_factory, ...)` (own transaction, commits the
  denial record, then raises `AccessDenied`). Always use `require_access` in code that raises on denial.
- T05 for T15: AC-1 ("no unauthorized read, ever") is only true once every adapter is wrapped in `GatedAdapter`
  and a test proves the wrapped adapter is never called when access is denied. Do not let any code call an adapter
  directly.
- T05 for T06/T09: the policy bundle's `permissions` section (allowed_sources, allowed_actions, denied_actions)
  must be added to the engine as a further check that can only narrow what bases allow. Until then the engine denies
  everything except the three read actions an access basis can grant.
- T05: mutation-tested: 8 deliberate breakages of the engine (comments check, revocation, expiry boundary, media
  grant, paused source, denial logging, tenant check, "any basis") were each caught by a named test.

