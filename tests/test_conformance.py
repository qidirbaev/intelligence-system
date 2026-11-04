"""Tripwires for the rules you set. If one of these fails, the build has drifted from the brief.

Each test is cited as evidence in docs/TRACEABILITY.md.
"""

import re
import socket
from pathlib import Path

import pytest
from tools import traceability

import sie.storage.models  # noqa: F401  (registers all tables)
from sie.storage.base import Base
from sie.storage.enums import AccessBasisType
from sie.storage.models import AccessBasis
from tests.conftest import NetworkBlocked

ROOT = Path(__file__).resolve().parent.parent

# Tooling whose purpose is to defeat a platform's access controls. The project must not use it
# (requirement CG-4). If a future task truly needs one of these names, that is a decision for the
# owner, not a code change: edit this list only after the owner agrees.
FORBIDDEN_TOKENS = [
    # captcha solving
    "2captcha", "anticaptcha", "capsolver", "deathbycaptcha", "captcha_solver", "solve_captcha",
    # proxy / account rotation
    "proxy_pool", "rotate_proxy", "rotating_proxy", "proxy_rotat",
    "rotate_account", "account_pool", "account_rotat", "session_pool",
    # detection evasion
    "undetected", "stealth", "cloudscraper", "fake_useragent", "fake-useragent",
    "user_agent_rotat", "tls_client", "curl_cffi", "bypass_",
    # browser automation for scraping (the pipeline is API-based only)
    "selenium", "playwright", "puppeteer",
]  # fmt: skip


def find_forbidden(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({token for token in FORBIDDEN_TOKENS if token in lowered})


def python_files(*roots: str) -> list[Path]:
    return [p for r in roots for p in (ROOT / r).rglob("*.py") if "__pycache__" not in p.parts]


def test_evasion_scanner_detects_known_tools():
    assert find_forbidden("import undetected_chromedriver") == ["undetected"]
    assert "rotate_proxy" in find_forbidden("def rotate_proxy(): ...")
    assert find_forbidden("import telethon  # a normal API client") == []


def test_no_evasion_tooling_in_source():
    offenders = {
        str(p.relative_to(ROOT)): hits
        for p in python_files("src", "tools")
        if (hits := find_forbidden(p.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"evasion tooling found (CG-4): {offenders}"


def test_no_evasion_dependencies():
    hits = find_forbidden((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert hits == [], f"evasion dependencies declared in pyproject.toml (CG-4): {hits}"


def test_every_table_has_tenant_id():
    assert Base.metadata.tables, "no tables registered"
    missing = [
        name
        for name, table in Base.metadata.tables.items()
        if "tenant_id" not in table.c or table.c.tenant_id.nullable
    ]
    assert missing == [], f"tables without a NOT NULL tenant_id: {missing}"


def test_comments_are_denied_by_default():
    column = AccessBasis.__table__.c.comments_allowed
    assert column.default.arg is False
    assert str(column.server_default.arg).lower() == "false"


def test_access_basis_types_match_the_compliance_spec():
    assert {t.value for t in AccessBasisType} == {
        "telegram_permission",
        "owner_consent",
        "own_channel",
        "other_official_api",
    }


def test_tests_cannot_reach_the_internet():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("93.184.216.34", 80), timeout=1)
    with pytest.raises(NetworkBlocked):
        socket.socket().connect(("149.154.167.50", 443))  # a Telegram-range address


def test_traceability_matrix_is_consistent():
    assert traceability.check(ROOT) == []


def test_every_task_is_a_known_requirement_target():
    tasks = traceability.parse_tasks((ROOT / "TASKS.md").read_text(encoding="utf-8"))
    assert tasks, "no tasks parsed from TASKS.md"
    assert all(re.fullmatch(r"T\d{2}[a-z]?", t) for t in tasks)


def test_l1_and_brain_never_read_audit_samples():
    """Audit samples exist only to estimate L0 recall (TZ 5.5); analysis code must not read them."""
    offenders = {}
    for package in ("l1", "brain", "comments", "api", "dashboard"):
        for path in python_files(f"src/sie/{package}"):
            text = path.read_text(encoding="utf-8").lower()
            if "audit_sample" in text or "auditsample" in text:
                offenders[str(path.relative_to(ROOT))] = "references audit samples"
    assert offenders == {}, offenders
