# intelligence-system (SIE): social media intelligence platform, demo / MVP
 
A policy-governed pipeline that collects *permitted* public posts, filters them in layers (L0, L1),
and lets a central Brain summarize events, extract stances and measure sentiment. Telegram first.

**Status:** under construction, built in small tasks. See [TASKS.md](TASKS.md) for progress,
[docs/TRACEABILITY.md](docs/TRACEABILITY.md) for what you asked for versus what exists (and where the build
differs), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the rules every change follows, and
[docs/VERIFICATION.md](docs/VERIFICATION.md) for the latest full-project run.

## First run: check that everything works on your machine

You need Python 3.11+, Git and Docker (for PostgreSQL). Nothing else.

```bash
git clone https://github.com/qidirbaev/intelligence-system.git
cd intelligence-system
docker compose up -d db          # starts PostgreSQL 16 with pgvector
python tools/verify.py           # builds a clean virtualenv, runs EVERYTHING, writes docs/VERIFICATION.md
python tools/demo.py             # watch what the project does today
```

`verify.py` takes about a minute. It fails (exit code 1) if anything is wrong: lint, any test (skipped tests count as
failures), database migrations on a fresh database, the demo, or a mismatch between the requirements register and
the code. Read `docs/VERIFICATION.md` for the result and for what the run does *not* prove.

- No Docker? Use any PostgreSQL 16 where the role may create databases and run
  `python tools/verify.py --database-url postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres`.
- Windows and macOS: written to be cross-platform but only tested on Linux so far. If a step fails there, send me
  the printed error.

## Everyday commands

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
make install        # pip install -e ".[dev]"
make test           # unit tests, no services needed
make test-int       # integration tests against PostgreSQL
make verify         # the full run (same as python tools/verify.py)
sie db-upgrade      # apply migrations (also: db-downgrade, db-current, db-ping)
```

## Compliance first

Telegram's terms restrict automated collection and any AI use of platform data. This project therefore refuses to
read any source without a recorded access basis (Telegram permission, owner consent, or a channel run by the
project), and it contains tests that fail if tooling for evading platform limits is ever added. Until a basis
exists, develop and test with your own channels and synthetic data.

## Layout

`src/sie/` one package per component (module map in docs/ARCHITECTURE.md) | `tools/` verification, demo and
register checker | `policies/` versioned policy bundles | `config/` example configuration | `tests/` mirrors the packages.
