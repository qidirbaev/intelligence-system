#!/usr/bin/env python3
"""Run the WHOLE project end to end and write docs/VERIFICATION.md.

    python tools/verify.py                 # full run in a clean virtual environment (recommended)
    python tools/verify.py --quick         # reuse the current environment (faster, weaker)
    python tools/verify.py --database-url postgresql+psycopg://user:pass@host:5432/postgres

What it does, in order (any failure makes the exit code 1):
  1. clean-room install: new virtualenv + `pip install -e ".[dev]"` (catches missing deps)
  2. PostgreSQL reachable
  3. lint + format check (ruff)
  4. all tests, unit AND integration; skipped tests count as a failure (a skip hides problems)
  5. migrations through the real CLI on a fresh database: upgrade, downgrade to base, upgrade again
  6. the end-to-end demo (tools/demo.py)
  7. requirements register vs. code and tasks (tools/traceability.py)

Only the standard library is used here, so it runs before anything is installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = "postgresql+psycopg://sie:sie_dev_only@127.0.0.1:5432/sie"


@dataclass
class Step:
    name: str
    ok: bool
    seconds: float
    detail: str = ""


class Verifier:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.steps: list[Step] = []
        self.python = sys.executable
        self.db_url = args.database_url or os.environ.get("DATABASE_URL") or DEFAULT_DB
        self.postgres_ok = False
        self.pg_version = "unknown"
        self.test_counts = ""
        self.skips: list[str] = []
        self.demo_transcript = ""
        self.matrix_summary = ""
        self.tmp = Path(tempfile.mkdtemp(prefix="sie_verify_"))

    # ------------------------------------------------------------------ helpers
    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SIE_")}
        env["DATABASE_URL"] = self.db_url
        env["SIE_TEST_DATABASE_URL"] = self.db_url
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(extra or {})
        return env

    def sh(self, cmd: list[str], extra_env: dict[str, str] | None = None, timeout: int = 1200):
        return subprocess.run(
            cmd, cwd=ROOT, env=self.env(extra_env), capture_output=True, text=True, timeout=timeout
        )

    def record(self, name: str, ok: bool, started: float, detail: str = "") -> bool:
        step = Step(name, ok, time.time() - started, detail.strip())
        self.steps.append(step)
        mark = "PASS" if ok else "FAIL"
        print(
            f"[{mark}] {name} ({step.seconds:.1f}s)" + (f"\n       {step.detail}" if not ok else "")
        )
        return ok

    @staticmethod
    def tail(text: str, lines: int = 12) -> str:
        return "\n       ".join(text.strip().splitlines()[-lines:])

    # ------------------------------------------------------------------ steps
    def clean_room(self) -> bool:
        started = time.time()
        venv_dir = self.tmp / "venv"
        made = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)], capture_output=True, text=True
        )
        if made.returncode != 0:
            return self.record(
                "clean-room: create virtualenv", False, started, self.tail(made.stderr)
            )
        bin_dir = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        self.python = str(venv_dir / bin_dir / exe)
        install = self.sh([self.python, "-m", "pip", "install", "-q", "-e", ".[dev]"])
        if install.returncode != 0:
            return self.record("clean-room: pip install", False, started, self.tail(install.stderr))
        check = self.sh([self.python, "-m", "sie.cli", "version"])
        ok = check.returncode == 0
        return self.record(
            "clean-room install (new virtualenv, pip install -e .[dev], sie runs)",
            ok,
            started,
            check.stdout + check.stderr if not ok else f"sie {check.stdout.strip()}",
        )

    def postgres(self) -> bool:
        started = time.time()
        result = self.sh([self.python, "-m", "tools.pgtemp", "check"])
        self.postgres_ok = result.returncode == 0
        if self.postgres_ok:
            self.pg_version = result.stdout.strip().split(",")[0]
        return self.record(
            "PostgreSQL reachable",
            self.postgres_ok,
            started,
            self.tail(result.stderr or result.stdout),
        )

    def lint(self) -> bool:
        started = time.time()
        lint = self.sh([self.python, "-m", "ruff", "check", "."])
        fmt = self.sh([self.python, "-m", "ruff", "format", "--check", "."])
        ok = lint.returncode == 0 and fmt.returncode == 0
        return self.record(
            "lint and format (ruff)", ok, started, self.tail(lint.stdout + lint.stderr + fmt.stdout)
        )

    def tests(self) -> bool:
        started = time.time()
        if not self.postgres_ok:
            return self.record(
                "tests (unit + integration)", False, started, "not run: PostgreSQL unreachable"
            )
        xml_path = self.tmp / "junit.xml"
        result = self.sh([self.python, "-m", "pytest", "-q", "-rs", f"--junitxml={xml_path}"])
        try:
            suite = ET.parse(xml_path).getroot()
            suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
            total = int(suite.get("tests", 0))
            failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
            skipped = int(suite.get("skipped", 0))
            self.skips = [(el.get("message") or "skipped")[:160] for el in suite.iter("skipped")]
        except Exception as exc:  # junit file missing -> pytest crashed before running
            return self.record(
                "tests (unit + integration)", False, started, f"{exc}\n{self.tail(result.stdout)}"
            )
        passed = total - failed - skipped
        self.test_counts = f"{passed} passed, {failed} failed, {skipped} skipped (of {total})"
        ok = result.returncode == 0 and failed == 0 and (skipped == 0 or self.args.allow_skips)
        detail = self.tail(result.stdout) if not ok else self.test_counts
        if skipped and not self.args.allow_skips:
            detail += "\n       skipped tests are failures (they hide problems): " + "; ".join(
                self.skips[:3]
            )
        return self.record("tests (unit + integration, zero skips)", ok, started, detail)

    def migrations(self) -> bool:
        started = time.time()
        if not self.postgres_ok:
            return self.record(
                "migrations via CLI", False, started, "not run: PostgreSQL unreachable"
            )
        created = self.sh([self.python, "-m", "tools.pgtemp", "create"])
        if created.returncode != 0:
            return self.record("migrations via CLI", False, started, self.tail(created.stderr))
        name, url = created.stdout.strip().split("\t")
        try:

            def cli(*args: str) -> str:
                out = self.sh([self.python, "-m", "sie.cli", *args], {"DATABASE_URL": url})
                if out.returncode != 0:
                    raise RuntimeError(f"sie {' '.join(args)} failed: {out.stderr or out.stdout}")
                return out.stdout.strip()

            before = cli("db-current")
            cli("db-upgrade")
            head = cli("db-current")
            cli("db-downgrade", "base")
            base = cli("db-current")
            cli("db-upgrade")
            again = cli("db-current")
            ping = cli("db-ping")
            ok = before == "none" and head != "none" and base == "none" and again == head
            detail = f"fresh -> {head} -> base -> {again}; {ping}"
            return self.record(
                "migrations via CLI on a fresh database (up, down, up)", ok, started, detail
            )
        except Exception as exc:
            return self.record("migrations via CLI", False, started, str(exc))
        finally:
            self.sh([self.python, "-m", "tools.pgtemp", "drop", name])

    def demo(self) -> bool:
        started = time.time()
        if not self.postgres_ok:
            return self.record("end-to-end demo", False, started, "not run: PostgreSQL unreachable")
        result = self.sh([self.python, "tools/demo.py"])
        self.demo_transcript = result.stdout.strip()
        ok = result.returncode == 0 and "DEMO OK" in result.stdout
        lines = result.stdout.strip().splitlines()
        detail = (lines[-1] if lines else "") if ok else self.tail(result.stderr or result.stdout)
        return self.record("end-to-end demo (tools/demo.py)", ok, started, detail)

    def traceability(self) -> bool:
        started = time.time()
        result = self.sh([self.python, "-m", "tools.traceability"])
        self.matrix_summary = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return self.record(
            "requirements register consistent with code and tasks",
            result.returncode == 0,
            started,
            self.tail(result.stdout),
        )

    # ------------------------------------------------------------------ report
    def git_info(self) -> str:
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
            ).stdout.strip()
            return f"{sha or 'no commits'}{' (+ uncommitted changes)' if dirty else ''}"
        except Exception:
            return "unknown"

    def report(self) -> str:
        overall = all(s.ok for s in self.steps)
        now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
        rows = "\n".join(
            f"| {'PASS' if s.ok else 'FAIL'} | {s.name} | {s.seconds:.1f}s | "
            f"{(s.detail.splitlines()[0] if s.detail else '').replace('|', '/')[:110]} |"
            for s in self.steps
        )
        mode = "quick (current environment)" if self.args.quick else "clean room (new virtualenv)"
        transcript = "\n".join(self.demo_transcript.splitlines()[:40]) or "(demo did not run)"
        return f"""# Verification report

**Result: {"ALL CHECKS PASSED" if overall else "FAILED"}** | {now} | commit {self.git_info()}

Generated by `python tools/verify.py` ({mode}). Python {platform.python_version()} on
{platform.system()} {platform.release()}; {self.pg_version}.

| Result | Check | Time | Detail |
|---|---|---|---|
{rows}

**Tests:** {self.test_counts or "not run"}
**Requirements register:** {self.matrix_summary or "not run"}

## Demo transcript (what the project does today)

```text
{transcript}
```

## What this run does NOT prove

- Nothing has talked to real Telegram. The tests cannot reach the internet by design, and the
  Telegram adapter does not exist yet (task T18).
- Only the Python and PostgreSQL versions listed above were exercised, on that operating system.
- No load, soak or performance testing yet (task T32). No LLM or embedding model is wired in yet.
- Quality of Uzbek text handling and of any model output cannot be judged until T10, T11, T23, T27.
- The requirements register shows where the build deviates from your brief (Deviations table);
  items marked "Needs your decision" are waiting for you.
"""

    def run(self) -> int:
        try:
            if not self.args.quick and not self.clean_room():
                return self.finish()
            self.postgres()
            self.lint()
            self.tests()
            self.migrations()
            self.demo()
            self.traceability()
            return self.finish()
        finally:
            if not self.args.keep:
                shutil.rmtree(self.tmp, ignore_errors=True)

    def finish(self) -> int:
        overall = all(s.ok for s in self.steps)
        path = Path(self.args.report) if self.args.report else ROOT / "docs" / "VERIFICATION.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.report(), encoding="utf-8")
        print(f"\n{'ALL CHECKS PASSED' if overall else 'VERIFICATION FAILED'}; report: {path}")
        return 0 if overall else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--quick", action="store_true", help="skip the clean-room virtualenv")
    parser.add_argument(
        "--database-url", help="PostgreSQL URL (role must be allowed to CREATE DATABASE)"
    )
    parser.add_argument("--allow-skips", action="store_true", help="do not fail on skipped tests")
    parser.add_argument("--report", help="where to write the report (default docs/VERIFICATION.md)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary virtualenv")
    return Verifier(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
