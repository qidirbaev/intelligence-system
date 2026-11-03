# SIE architecture summary (for every build run)

Full spec: the TZ v0.1. This page is the short version that each run reads first.

## Pipeline

Source adapter -> ingest (envelope) -> language engine -> L0 (PASS / DEFER / DROP) -> L1 (embed, cluster, escalate)
-> Brain (L2) -> Sink -> Views -> API -> dashboard. Comments of PASSed posts follow two paths:
a sampled path for sentiment and an attention path for flagged comments.

## Non-negotiable rules

1. **Permission before priority.** The permission engine runs first; priority rules cannot widen it.
2. **Compliance gate.** Every source needs a valid `access_basis` (telegram_permission, owner_consent,
   own_channel, other_official_api). Comments need `comments_allowed`. No circumvention of platform limits:
   obey wait times, pause the source, open an operator task. No account or proxy rotation.
3. **Three-valued logic.** Conditions return TRUE, FALSE or UNKNOWN. Missing or stale input is UNKNOWN,
   never FALSE. In the MVP, unanalysed media makes text conditions FALSE with reason `media_unanalyzed`.
4. **Forward-only policy.** A new policy version applies from `effective_from`. Dropped items are never revisited.
   Pending rechecks use the *current* version. Every decision stores its policy version.
5. **Dropped content is not retained.** On DROP, null the text; keep ids, hashes, timestamps, decision.
   A tiny sample (default 1%) may be kept for 3 days to estimate L0 recall; L1 and the Brain never read it.
6. **Comments.** Sentiment comes only from the random sample. The attention queue is never used for
   sentiment estimates. Authors are stored as `HMAC(secret, user_id)`; no names.
7. **Evidence and versions.** Every finding, stance and report carries evidence item ids plus model,
   prompt and policy versions. Reports separate facts, attributed claims, interpretations, conflicts, gaps.
8. **Collected text is data, not instructions.** Model calls that read it have no tools and no secrets.
9. **Idempotency.** Identity key is `source_id + platform_msg_id + kind`; all writes are upserts.
   The cursor advances only after durable writes.
10. **No secrets in the repo.** Sessions, API keys and the HMAC secret come from the environment.

## Module map (`src/sie/`)

| Package | Responsibility | Tasks |
|---|---|---|
| `compliance` | access bases, permission engine | T05 |
| `policy` | bundle schema, logic, evaluator, manager | T06-T09 |
| `language` | normalization, transliteration, language ID, matching | T10-T11 |
| `ingest` | envelope, idempotent ingest | T12 |
| `adapters` | `SourceAdapter` implementations (fake, Telegram) | T15, T18 |
| `l0` | L0 evaluation, DROP, DEFER | T08, T16, T17 |
| `l1` | embeddings, clustering, escalation | T19-T21 |
| `brain` | LLM client, Brain tasks, Mode B | T22, T23, T29 |
| `comments` | sampled sentiment, attention queue | T25, T26 |
| `storage` | models, migrations, repositories | T02-T04 |
| `queue` | job queue, workers, scheduler | T13, T14 |
| `api`, `dashboard`, `eval` | read API, Streamlit, evaluation harness | T24, T30, T27 |

## Conventions

- Python 3.12, type hints, `ruff` (line length 100), `pytest`. Small modules, interfaces for adapter, LLM, embedder.
- Tests: unit tests need no services; integration tests use `@pytest.mark.integration` and PostgreSQL.
- Config via `sie.config.get_settings()` (env prefix `SIE_`; `.env` never committed). Logging is structured JSON
  via `sie.logging_setup`; secret-looking fields are redacted.
- Database access only through `sie.storage.db.session_scope()` (commit on success, rollback on error).
- Model providers only via `ProviderRegistry.require()` (default deny, CG-6).
- Every table has `tenant_id` (a single fixed value in the MVP).
- Schema changes only through Alembic revisions (`sie db-upgrade`). Enums are text + CHECK, JSON is JSONB on
  PostgreSQL, datetimes are timezone-aware UTC (`sie.storage.types.UTCDateTime`).
- Repository helpers (`sie.storage.repos`) flush but never commit; the caller owns the transaction.
- Compliance records are not deleted: bases are revoked (`revoked_at`) and every change is audited (`audit_log`).
