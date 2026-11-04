"""End-to-end demo of what the project can do *today*. Extended by every task (see TASKS.md).

Today it covers the registry, compliance records, collected items, decisions and the operator
queue, all against a real database. The full pipeline demo arrives with T15 and T32.

Usage: python tools/demo.py [--database-url URL]   (default: a throw-away PostgreSQL database)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from sie.storage import migrate, repos, repos_content, repos_ops  # noqa: E402
from sie.storage.db import make_engine, make_session_factory, session_scope  # noqa: E402
from sie.storage.enums import AccessBasisType  # noqa: E402
from sie.storage.models import AuditLog, ContentItem, PolicyVersion, Source  # noqa: E402
from sie.storage.types import utcnow  # noqa: E402
from tools import pgtemp  # noqa: E402

# psycopg sometimes logs "error ignored terminating Pipeline" when a connection that just had a
# deliberately rejected INSERT is cleaned up. It is harmless (rows are rolled back, see the checks
# below), so keep it out of the transcript. See TASKS.md notes.
logging.getLogger("psycopg").setLevel(logging.ERROR)


def run(url: str) -> int:
    engine = make_engine(url)
    factory = make_session_factory(engine)
    checks = 0

    def say(text: str) -> None:
        print(text, flush=True)

    def must_reject(label: str, action) -> None:
        nonlocal checks
        try:
            with session_scope(factory) as session:
                action(session)
        except (DBAPIError, ValueError):
            checks += 1
            say(f"   rejected, as it must be: {label}")
        else:
            raise AssertionError(f"the database accepted something it must reject: {label}")

    say(f"== SIE demo on {engine.dialect.name} ==")
    migrate.upgrade(engine)
    say(f"1. empty database migrated to revision {migrate.current_revision(engine)}")

    with session_scope(factory) as session:
        person = repos.add_person(session, "Demo Figure", "blogger")
        source = repos.add_source(
            session,
            "telegram",
            "demo_channel",
            handle="@demo_channel",
            person_id=person.person_id,
            tags=["public_figure"],
        )
        source_id = source.source_id
        say(
            f"2. registered {person.display_name} + source telegram:demo_channel (agent state made)"
        )

    must_reject(
        "3. a consent basis with no document",
        lambda s: repos.add_access_basis(s, source_id, AccessBasisType.OWNER_CONSENT),
    )

    with session_scope(factory) as session:
        own = repos.add_access_basis(session, source_id, AccessBasisType.OWN_CHANNEL)
        consent = repos.add_access_basis(
            session, source_id, AccessBasisType.OWNER_CONSENT, document_ref="consent-demo-001"
        )
        say(
            "4. recorded two bases (own channel, signed consent); "
            f"comments allowed by default: {own.comments_allowed or consent.comments_allowed}"
        )
        own_id = own.basis_id

    must_reject(
        "5. deleting a source that has access bases", lambda s: s.delete(s.get(Source, source_id))
    )

    with session_scope(factory) as session:
        repos.revoke_access_basis(session, own_id, actor="operator:demo")
        actions = session.scalars(select(AuditLog.action).order_by(AuditLog.audit_id)).all()
        say(f"6. revoked the own-channel basis; audit trail: {', '.join(actions)}")

    must_reject(
        "7. a published policy with no approver",
        lambda s: s.add(
            PolicyVersion(version=1, status="published", effective_from=utcnow(), bundle={})
        ),
    )

    with session_scope(factory) as session:
        session.add(PolicyVersion(version=2, bundle={"policy_version": 2}))
        say("8. stored policy version 2 as a draft")

    if engine.dialect.name == "postgresql":
        from sqlalchemy import text

        must_reject(
            "9. editing the audit log",
            lambda s: s.execute(text("UPDATE audit_log SET actor = 'tampered'")),
        )
    else:
        say("9. (audit-log tamper check runs on PostgreSQL only)")

    # ---- T04: collected items, drops, decisions, operator tasks ----
    published = utcnow()
    with session_scope(factory) as session:
        first, created = repos_content.upsert_content_item(
            session, source_id=source_id, platform_msg_id="48213", published_at=published,
            text_raw="BRT announcement", text_norm="brt announcement", lang="uz", script="latin",
        )  # fmt: skip
        again, created_again = repos_content.upsert_content_item(
            session, source_id=source_id, platform_msg_id="48213", published_at=published,
            text_raw="an edited copy",
        )  # fmt: skip
        assert created and not created_again and first.item_id == again.item_id
        item_id = first.item_id
        checks += 1
        say("10. the same Telegram message ingested twice -> still ONE item, original text kept")

    def mark_dropped_keeping_text(s):
        s.get(ContentItem, item_id).status = "dropped"

    must_reject(
        "11. marking an item dropped while it still holds its text", mark_dropped_keeping_text
    )

    with session_scope(factory) as session:
        stored = session.get(ContentItem, item_id)
        stored.text_raw = stored.text_norm = None
        stored.status = "dropped"
        decision = repos_content.record_decision(session, item_id, 2, "default", "DROP", {})
        repos_content.add_audit_sample(session, item_id, decision.decision_id, "brt announcement")
        say("12. dropped it properly: text removed, decision logged, 3-day audit sample kept")

    with session_scope(factory) as session:
        task = repos_ops.open_operator_task(
            session, "session_revoked", "Telegram session ended for demo_channel",
            source_id=source_id, team="team-a",
            detail={"api_hash": "THIS-MUST-NOT-BE-STORED", "note": "owner must log in again"},
        )  # fmt: skip
        assert "THIS-MUST-NOT" not in str(task.detail)
        task_id = task.task_id
        checks += 1
        say(f"13. operator task opened; secrets were masked before storing: {task.detail}")

    must_reject(
        "14. an operator task link that carries a token",
        lambda s: repos_ops.open_operator_task(
            s, "access_denied", "recovery", account_link="https://example.org/recover?token=abc"
        ),
    )

    with session_scope(factory) as session:
        repos_ops.resolve_operator_task(
            session, task_id, resolved_by="operator:demo", resolution="owner logged in again"
        )
        recent = session.scalars(
            select(AuditLog.action).order_by(AuditLog.audit_id.desc()).limit(2)
        ).all()
        say(f"15. task resolved by a human; latest audit entries: {', '.join(reversed(recent))}")

    engine.dispose()
    say(f"DEMO OK ({checks} protections verified; storage and compliance only).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url", help="empty database to use (default: temporary PostgreSQL)"
    )
    args = parser.parse_args(argv)
    try:
        if args.database_url:
            return run(args.database_url)
        base = pgtemp.base_url()
        if base.startswith("sqlite"):
            return run(base)
        with pgtemp.temp_database(base) as url:
            return run(url)
    except pgtemp.PostgresUnavailable as exc:
        print(f"DEMO FAILED: {exc}", file=sys.stderr)
        return 1
    except AssertionError as exc:
        print(f"DEMO FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
