# Requirements register: what you asked for, and where it stands

This file is checked by machine on every run (`tests/test_conformance.py`, `python -m tools.traceability`).
It fails the build if a row claims something that does not exist, if a status contradicts `TASKS.md`,
or if a task exists that no requirement asks for.

**Sources:** SKD = System Knowledge Document v1.0 (your original vision). TZ = the technical task document
(kept in the Claude doc; drop an export into `docs/TZ.md` if you want it in the repo). "chat" = your messages.

**Statuses:** Implemented (all its tasks are done, evidence cited) / Partial (some tasks done, evidence cited) /
Planned (nothing built yet) / Deferred or Changed (differs from your request: see the Deviations table).

## Requirements

| ID | Requirement | Source | Status | Tasks | Evidence |
|---|---|---|---|---|---|
| V-01 | Large-scale, distributed platform for commercial and authorized research use | SKD 1-2 | Partial | T01, T02, T03, T32 | `docs/ARCHITECTURE.md`, `docker-compose.yml` |
| V-02 | Source-based Data Agents: one logical agent per source, durable state that survives restarts | SKD 4 | Partial | T03, T14 | `tests/test_registry_models.py::test_agent_state_cursor_and_memory_roundtrip`, `tests/test_registry_models.py::test_source_defaults_and_agent_state` |
| V-03 | L0 inside each agent: cheap PASS / DEFER / DROP / REQUEST decisions | SKD 5 | Planned | T07, T08, T15, T17 | none yet |
| V-04 | L1 shared layer: groups posts into events and decides what deserves deeper work | SKD 6 | Planned | T19, T20, T21 | none yet |
| V-05 | L2 Brain: continuous 24/7 plus on-demand research over one shared knowledge base | SKD 7 | Planned | T23, T29 | none yet |
| V-06 | Agents keep local memory (M1-M3) and plan their own checks | SKD 4.5, 11 | Partial | T03, T14 | `tests/test_registry_models.py::test_agent_state_cursor_and_memory_roundtrip` |
| V-07 | Agents propose improvements; controlled changes need human approval | SKD 4.4, 11.2 | Deferred | none | D-3 |
| V-08 | Mandatory permission engine, separate from and checked before the priority engine | SKD 9 | Partial | T03, T05, T06, T09 | `tests/test_registry_models.py::test_policy_version_lifecycle_rules`, `tests/test_permission.py::test_property_decision_matches_the_rule` |
| V-09 | Human operations teams handle access problems through authorized paths | SKD 13 | Changed | T04 | `tests/test_operator_tasks.py::test_operator_task_lifecycle_is_audited`, D-3 |
| V-10 | Multimodal input (text, image, audio, video); videos converted to text summaries | SKD 8, chat | Deferred | none | D-2 |
| V-11 | Output flows Sink to Views to Dashboards | SKD 16 | Planned | T24, T30 | none yet |
| V-12 | Resource-efficient: costly processing only when earlier layers justify it; budgets | SKD 19 | Planned | T21, T28 | none yet |
| V-13 | Agents discover related sources and propose them to a central registry | SKD 12 | Deferred | none | D-3 |
| V-14 | Multi-tenant platform serving several organizations | SKD 2.3 | Changed | T03 | D-3 |
| U-01 | Start with Telegram (solo prototype), built so other platforms plug in | chat | Planned | T15, T18 | none yet |
| U-02 | Later platforms: Instagram, Threads, mainly TikTok | chat | Deferred | none | D-3 |
| U-03 | Scale: 2,000 sources at start, 10,000 at scale | chat | Planned | T14, T28, T32 | none yet |
| U-04 | Sources are public figures, influencers, bloggers; a Person layer links their accounts | chat | Implemented | T03 | `tests/test_registry_models.py::test_source_defaults_and_agent_state`, `tests/test_registry_models.py::test_deleting_person_keeps_source` |
| U-05 | Policies can change at any moment; a new rule applies from that moment only | chat | Partial | T03, T09, T17 | `tests/test_registry_models.py::test_policy_version_lifecycle_rules` |
| U-06 | Dropped content is not retained (decision record plus tiny audit sample only) | chat | Partial | T04, T16 | `tests/test_content_models.py::test_dropped_content_cannot_keep_text`, `tests/test_conformance.py::test_l1_and_brain_never_read_audit_samples` |
| U-07 | Demo: what public figures say on a topic, trending narratives, sentiment among figures and civilians | chat | Planned | T23, T24, T29, T30 | none yet |
| U-08 | Comments: only those needing attention (per policy) go through; sentiment from a sample | chat | Planned | T25, T26 | none yet |
| U-09 | Language engine for Uzbek (Cyrillic and Latin), Russian and mixed text | chat | Planned | T10, T11 | none yet |
| U-10 | Policy format designed by me for the MVP | chat | Planned | T06 | none yet |
| U-11 | Small tasks; run the whole project after each task; no deviation from what you asked | chat | Implemented | T03a | `tools/verify.py`, `tools/traceability.py`, `tests/test_conformance.py::test_traceability_matrix_is_consistent` |
| CG-1 | Every source needs a documented access basis before any reading | TZ 2.2 | Partial | T03, T05, T15 | `tests/test_registry_models.py::test_document_ref_required_except_for_own_channel`, `tests/test_registry_models.py::test_access_basis_invalid_type_rejected`, `tests/test_permission.py::test_source_without_basis_is_denied_and_the_denial_is_audited` |
| CG-2 | Permission engine denies reads without a valid, unexpired, unrevoked basis; denials logged | TZ 2.2 | Partial | T05, T15 | `tests/test_permission.py::test_revoking_a_basis_takes_effect_immediately`, `tests/test_permission.py::test_validity_window_boundaries`, `tests/test_permission.py::test_require_access_raises_but_the_denial_record_survives`, `tests/test_permission.py::test_repeated_denials_are_audited_once_per_window_but_always_logged` |
| CG-3 | Comments only if comments_allowed (default false); owner consent alone does not allow them | TZ 2.2 | Partial | T03, T05, T25 | `tests/test_registry_models.py::test_access_basis_defaults_deny_comments`, `tests/test_conformance.py::test_comments_are_denied_by_default`, `tests/test_permission.py::test_owner_consent_alone_never_grants_comments`, `tests/test_permission.py::test_property_comments_are_never_easier_than_posts` |
| CG-4 | No circumvention: obey waits, pause the source, open an operator task; no account or proxy rotation | TZ 2.2 | Partial | T03a, T04, T18 | `tests/test_conformance.py::test_no_evasion_tooling_in_source`, `tests/test_conformance.py::test_no_evasion_dependencies`, `tests/test_operator_tasks.py::test_operator_task_lifecycle_is_audited`, `tests/test_operator_tasks.py::test_unsafe_account_links_are_refused` |
| CG-5 | Secrets never in logs or queues; sessions encrypted | TZ 2.2 | Partial | T02, T04, T18 | `tests/test_config.py::test_secrets_never_appear_in_repr_or_dump`, `tests/test_logging.py::test_secret_looking_fields_are_redacted`, `tests/test_operator_tasks.py::test_operator_task_never_stores_secrets`, `tests/test_content_models.py::test_dead_letter_masks_secrets_and_expires` |
| CG-6 | Model providers: allow-list, default deny, cross-border needs sign-off | TZ 2.2 | Partial | T02, T22 | `tests/test_providers.py::test_empty_registry_denies_everything`, `tests/test_providers.py::test_cross_border_requires_signoff` |
| CG-7 | Retention enforced by jobs; revoking a basis flags derived data | TZ 2.2 | Partial | T04, T16 | `tests/test_content_models.py::test_audit_sample_expires_in_the_future`, `tests/test_content_models.py::test_dead_letter_masks_secrets_and_expires` |
| CG-8 | Every report states its source coverage and monitoring-since date | TZ 2.2 | Planned | T29 | none yet |
| CG-9 | Access-basis changes are audited; the audit log cannot be edited; bases are revoked, not deleted | TZ 2, 4 | Implemented | T03 | `tests/test_registry_models.py::test_revoke_sets_time_and_audits_once`, `tests/test_registry_models.py::test_source_with_basis_cannot_be_deleted`, `tests/test_migrations.py::test_audit_log_is_append_only_on_postgres` |
| A-01 | Conditions are three-valued; missing data is UNKNOWN, never FALSE | SKD 5.5 | Planned | T07 | none yet |
| A-02 | Idempotent processing: stable identity key, cursor advances after durable writes | TZ 5.1 | Partial | T04, T12, T13 | `tests/test_content_models.py::test_upsert_is_idempotent_on_identity_key` |
| A-03 | Every table carries tenant_id | TZ 4 | Implemented | T03 | `tests/test_conformance.py::test_every_table_has_tenant_id` |
| A-04 | Timestamps are timezone-aware UTC | engineering | Implemented | T03 | `tests/test_registry_models.py::test_naive_datetimes_are_rejected` |
| A-05 | Findings, stances and reports carry evidence ids and model, prompt and policy versions | SKD 15.4 | Planned | T23, T29 | none yet |
| A-06 | Collected text is data, not instructions (prompt-injection defence) | SKD 21 | Planned | T22, T23 | none yet |
| A-07 | Schema changes only through migrations that match the models | engineering | Implemented | T03 | `tests/test_migrations.py::test_models_match_migration_on_sqlite` |
| A-08 | Tests never touch the internet (no Telegram or third-party traffic) | process | Implemented | T03a | `tests/test_conformance.py::test_tests_cannot_reach_the_internet` |
| A-09 | Runs from a clean checkout; one command verifies everything | chat | Implemented | T01, T02, T03a | `tools/verify.py`, `tools/demo.py`, `Makefile` |
| A-10 | Reliability: crash recovery, retries, dead letters, backpressure | TZ 5.9 | Planned | T13, T28 | none yet |
| A-11 | Measurable processing: metrics, labeled sets, recall estimate | SKD principle 8 | Planned | T27, T31 | none yet |
| A-12 | Reports separate facts, attributed claims, interpretations, conflicts and gaps | SKD 7.5 | Planned | T29 | none yet |
| AC-1 | Acceptance: no source without a valid basis is ever read | TZ 12.4 | Partial | T05, T32 | `tests/test_permission.py::test_property_a_source_without_any_basis_is_never_readable` |
| AC-2 | Acceptance: a new policy version changes decisions only from its effective time | TZ 12.4 | Planned | T09, T17, T32 | none yet |
| AC-3 | Acceptance: a killed worker causes no loss or duplicates | TZ 12.4 | Planned | T13, T32 | none yet |
| AC-4 | Acceptance: Cyrillic Uzbek, Latin Uzbek and Russian posts on one topic form one event | TZ 12.4 | Planned | T10, T11, T20, T32 | none yet |
| AC-5 | Acceptance: dashboard shows stances, trend and sentiment with sample size and coverage | TZ 12.4 | Planned | T24, T30 | none yet |
| AC-6 | Acceptance: attention queue holds only policy-matching comments; no commenter names stored | TZ 12.4 | Planned | T26 | none yet |
| AC-7 | Acceptance: a research question returns an evidence-linked report in under 3 minutes | TZ 12.4 | Planned | T29 | none yet |
| AC-8 | Acceptance: LLM usage stays under the cap; degraded mode triggers and recovers | TZ 12.4 | Planned | T28 | none yet |

## Deviations and additions (where the build differs from what you asked, or adds something)

| ID | What differs | Why | Needs your decision |
|---|---|---|---|
| D-1 | Compliance gate: nothing is read from a source without a recorded access basis, and comments need separate permission. You asked to monitor public figures' Telegram channels; Telegram's content-licensing terms restrict automated collection and AI use of its data. | Avoids building something that breaks the platform's rules. No bypass tooling will be built, and a test enforces that. | Yes |
| D-2 | The MVP is text-only. Turning videos into text summaries (which you asked for) is Phase 2. | Needs permitted media download, transcription cost and a media pipeline; the demo does not need it to prove the idea. | Yes |
| D-3 | Deferred beyond the MVP: Human Operations Center UI (only a minimal operator-task queue is built), agent self-improvement proposals, source discovery, tenant admin UI, Instagram, Threads and TikTok adapters. | Keeps a solo demo small. The adapter interface and tenant_id keep the door open. | Yes |
| D-4 | Agent "planning" is a statistical scheduler (when to check next), not an LLM planner. | Cost and predictability across 2,000 to 10,000 agents. | Yes |
| D-5 | Extras I added that you did not ask for: provider allow-list, append-only audit log, access-basis revocation record, expiry dates on dead letters and audit samples (privacy), tripwire tests against evasion tooling, this register. | Each one enforces a rule you or the compliance review need. | No |
| D-6 | Gap found in my own TZ: it promised "operator tasks" but its data model had no table for them. Built in T04 (`operator_tasks`). | Found while writing this register. | No |
| D-7 | The full TZ lives in the Claude doc, not in the repo. | Export is a manual step: Download as Markdown, save as `docs/TZ.md`. | No |
| D-8 | Denial logging: every denial goes to the application log, but the permanent audit record is written once per hour per (source, action, reason). The TZ says "every denial is logged". | A scheduler that retries every few minutes would flood the append-only audit table with identical rows. | No |
