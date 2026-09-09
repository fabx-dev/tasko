# Contributing

Hobby project, Italian-first. Issues in Italian or English welcome.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

## Rules

- Every change ships with or updates tests in `tests/` (isolated temp files only —
  never touch real `~/.todo_*` files; see `tests/conftest.py`).
- Keep `ruff check` and `ruff format --check` green on `src/` and `tests/`.
- UI text goes through `src/lang.py` in **both** languages (`T("key")` + parity test).
- Small, focused commits; one feature per PR.

## What gets rejected

- New dependencies without discussion (offline-first, lean install).
- Features that break the JSON formats without migration + tests.
- AI/network calls in the default path (opt-in only, mocked in tests).
