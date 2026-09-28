# OrderMind working guide

## What this repository is

OrderMind is currently a FastAPI backend for B2B order intake and catalog matching. There is no frontend or `/` route. The API docs are at `/docs`; `/health` reports process health. Plain-text intake, mock and Gemini extraction, master-data Excel import, review/approval, and CSV/XLSX/JSON export exist. Other input adapters, providers, a UI, and direct ERP integrations are planned.

## Local setup

- Work from the repository root so `sqlite:///./ordermind.db` resolves consistently.
- Use Python 3.12+ and `uv sync --frozen`; `pyproject.toml` plus `uv.lock` are the dependency source of truth. Do not add a separate `requirements.txt` unless a deployment requires it.
- Copy `.env.example` to `.env` for local settings. Never print, commit, or copy secret values into tests or docs. The mock provider works without an API key.
- Run `./.venv/Scripts/python.exe -m alembic upgrade head` before starting the API. Startup does not create tables. The legacy upgrade helper is only for the specific pre-Alembic schema; new installations use normal Alembic migrations.
- Start locally with `./.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log`. Port 8000 is currently used by the separate local Astakos service.

## Code and data boundaries

- Business identities come from SQL master data. AI extraction must not invent SKUs, products, or quantities unsupported by the customer's text.
- Keep company isolation consistent across ORM validation, composite tenant foreign keys, and migrations. Test a new constraint against a migrated database as well as `Base.metadata.create_all` when relevant.
- Order mutations participate in the order version/transaction boundary. Approval creates the business snapshot; final export reads its business values from that snapshot.
- Do not modify or delete a populated local database, backups, `.env`, or real business data as incidental cleanup. Generated pytest folders and Python caches are disposable.
- Treat `backend/fixtures/` as synthetic import samples. Do not commit customer uploads, exports, credentials, or SQLite databases.

## Verification

- Run focused tests for a change, then `./.venv/Scripts/python.exe -m pytest backend/tests -q` for broad backend changes.
- For schema changes, also run a fresh `alembic upgrade head`, `alembic check`, and a foreign-key check on SQLite. The database target is SQLite only. File databases use WAL at API startup and a 5-second busy timeout per connection; preserve those tests when changing engine setup.
- Review `git diff --check`, `git diff`, and `git status --short` before proposing a commit. Untracked migration and test files need explicit review; generated test directories should not be staged.
