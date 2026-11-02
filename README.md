# SIE: Social Media Intelligence Platform (demo / MVP)

A policy-governed pipeline that collects *permitted* public posts, filters them in layers (L0, L1),
and lets a central Brain summarize events, extract stances and measure sentiment. Telegram first.

**Status:** under construction. See [TASKS.md](TASKS.md) for progress and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the rules every change must follow.

## Compliance first

Telegram's terms restrict automated collection and any AI use of platform data. This project therefore refuses
to read any source without a recorded access basis (permission, owner consent, or a channel run by the project).
Until that is settled, develop and test with your own channels and synthetic data.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
make install        # pip install -e ".[dev]"
make test           # unit tests
make lint
cp .env.example .env
make up             # PostgreSQL with pgvector (for integration tests)
sie version
```

## Layout

`src/sie/` holds one package per component (see the module map in docs/ARCHITECTURE.md);
`policies/` holds versioned policy bundles; `tests/` mirrors the packages.
