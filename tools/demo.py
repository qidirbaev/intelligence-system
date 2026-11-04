"""End-to-end demo of what the project can do *today*. Extended by every task (see TASKS.md).

At task T03a it covers the registry and the compliance records only: sources, access bases,
audit trail and policy-version rules, all against a real database. The full pipeline demo
arrives with T15 and T32.

Usage: python tools/demo.py [--database-url URL]   (default: a throw-away PostgreSQL database)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from sie.storage import migrate, repos  # noqa: E402
from sie.storage.db import make_engine, make_session_factory, session_scope  # noqa: E402
from sie.storage.enums import AccessBasisType  # noqa: E402
from sie.storage.models import AuditLog, PolicyVersion, Source  # noqa: E402
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
        except DBAPIError:
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

    engine.dispose()
    say(f"DEMO OK ({checks} protections verified). Covers registry + compliance records only.")
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
