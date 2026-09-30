# OrderMind working guide

## What this repository is

OrderMind is a FastAPI backend and React operator workspace for B2B order intake and catalog matching. A built frontend is served at `/`; API docs are at `/docs` and `/health` reports process health. Pasted text and file-preview intake (TXT, CSV, XLSX, DOCX, PDF and common photos), mock and selected-provider extraction, master-data Excel import, review/approval, and CSV/XLSX/JSON export exist. Photo and scanned-PDF transcription uses the selected Gemini, OpenAI, Claude, or Vertex provider. Email intake, authentication, and direct ERP integrations are planned.

## Local setup

- Work from the repository root so `sqlite:///./ordermind.db` resolves consistently.
- Use Python 3.12+ and `uv sync --frozen`; `pyproject.toml` plus `uv.lock` are the dependency source of truth. Do not add a separate `requirements.txt` unless a deployment requires it.
- Copy `.env.example` to `.env` for local settings. Never print, commit, or copy secret values into tests or docs. The mock provider works without an API key.
- Run `uv run --frozen python -m alembic upgrade head` before starting the API. Startup does not create tables. The legacy upgrade helper is only for the specific pre-Alembic schema; new installations use normal Alembic migrations.
- Start locally with `uv run --frozen python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log`. Keep the current unauthenticated application on localhost.
- Build the UI with `cd frontend; npm ci; npm run build; cd ..` before starting Uvicorn if serving it at `/`. Use `npm run dev` in `frontend/` for Vite development.

## Code and data boundaries

- Business identities come from SQL master data. AI extraction must not invent SKUs, products, or quantities unsupported by the customer's text.
- Customer files are converted to editable text before creating an order. The binary is not retained; the operator must compare OCR and extracted quantities against the original file before submitting.
- Keep company isolation consistent across ORM validation, composite tenant foreign keys, and migrations. Test a new constraint against a migrated database as well as `Base.metadata.create_all` when relevant.
- Order mutations participate in the order version/transaction boundary. Approval creates the business snapshot; final export reads its business values from that snapshot.
- Do not modify or delete a populated local database, backups, `.env`, or real business data as incidental cleanup. Generated pytest folders and Python caches are disposable.
- Treat `backend/fixtures/` as synthetic import samples. Do not commit customer uploads, exports, credentials, or SQLite databases.
- Use `.test` or `example.com` addresses and clearly synthetic company/customer names in tests and samples. Inspect spreadsheet document properties before committing binary fixtures.
- Keep instructions independent of a contributor's machine paths, other local projects, or business identities. Changes to repository visibility, licensing, or Git history require explicit owner authorization.
- Use a focused branch and pull request for changes. Complete checks and inspect automated review feedback before merging; do not infer merge authorization from a request to push.

## Verification

- Run focused tests for a change, then `uv run --frozen python -m pytest backend/tests -q` for broad backend changes.
- Run `npm test` and `npm run build` in `frontend/` for UI changes.
- For schema changes, also run a fresh `alembic upgrade head`, `alembic check`, and a foreign-key check on SQLite. The database target is SQLite only. File databases use WAL at API startup and a 5-second busy timeout per connection; preserve those tests when changing engine setup.
- Review `git diff --check`, `git diff`, and `git status --short` before proposing a commit. Untracked migration and test files need explicit review; generated test directories should not be staged.
