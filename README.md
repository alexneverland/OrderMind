# OrderMind

OrderMind is an early-stage B2B order intake **backend API**. It turns customer order text into reviewable order lines, matches them against a company's own catalog, records operator corrections, and exports approved orders. The catalog and operator decisions are the source of truth; an AI provider extracts text but does not invent products or SKUs.

There is no web frontend or `/` homepage yet. Once the server is running, use the interactive API at `http://127.0.0.1:8001/docs`. A 404 at `/` is expected.

## Current scope

- Plain-text order input; mock extraction works offline, and Gemini extraction is implemented when configured.
- Company, customer, product, packaging, and export-profile APIs; Excel imports for master data.
- Catalog matching using identifiers, aliases, normalized descriptions, and bounded fuzzy candidates; confidence and review states.
- Operator confirmation/correction, approval with a stored snapshot, and CSV/XLSX/JSON export.
- SQLite database with Alembic migrations and tenant foreign-key constraints.

PDF/image/email intake, OpenAI/Anthropic/Vertex providers, a frontend, and direct ERP integrations are **planned**, not available in this API. Exported files can be imported into other systems separately.

## First local run (Windows PowerShell)

Run these commands from the repository root (`C:\OrderMind`). Python 3.12+ and uv are required.

```powershell
uv sync --frozen
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open `http://127.0.0.1:8001/docs`. Check `http://127.0.0.1:8001/health` and `GET /api/v1/companies` to verify the API and database connection. Stop the server with Ctrl+C. Port 8001 avoids the local Astakos service currently using port 8000; choose another free port if needed. The `.env` file is local and ignored by Git; the default `AI_PROVIDER=mock` needs no API key. To use Gemini, set `AI_PROVIDER=gemini`, an appropriate `AI_MODEL`, and `GEMINI_API_KEY` in `.env`, then restart the server.

The `HOST` and `PORT` settings in `.env` do not change the command above; the Uvicorn CLI flags choose the listening address and port. The default `DATABASE_URL=sqlite:///./ordermind.db` is relative to the working directory, so run migrations and the server from the repository root. The API does **not** create or migrate tables at startup.

## Dependencies and tests

`pyproject.toml` declares dependencies and `uv.lock` pins their resolution. Use `uv sync --frozen` for a reproducible environment; there is no separate `requirements.txt` to keep in sync.

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m alembic check
```

Tests use temporary databases. They do not require the local `ordermind.db` or a Gemini key.

## Database migrations

For a new database, set `DATABASE_URL` in `.env` and run `alembic upgrade head` before starting the API. Back up any populated database before a future schema upgrade. SQLite files, local `.env` files, and generated test files are ignored by Git.

OrderMind currently accepts SQLite URLs only. On API startup, a file database is placed in WAL mode; every SQLite connection enables foreign keys and waits at most 5 seconds for a short write lock. A lock that persists past that wait returns HTTP 503 with `Retry-After: 1`. Order edits use optimistic version checks, and alias counters use atomic SQL updates. SQLite still has one writer at a time, so keep write transactions short.

For a future **live** backup, use SQLite's backup API or `VACUUM INTO` on a separate destination file. Do not copy only `ordermind.db` while the API is writing: WAL may hold committed data in `ordermind.db-wal`. There is no automated backup or maintenance job yet. If maintenance becomes necessary, use `PRAGMA integrity_check` for a consistency check, `PRAGMA wal_checkpoint` to inspect/checkpoint WAL, and `VACUUM` for deliberate compaction during a maintenance window. These are operational tools, not commands to run on every startup.

The separate `python -m backend.alembic.upgrade_legacy` command exists only for a database created by the pre-Alembic schema at commit `1cd7f52`. It is **not needed for a new installation**. It rejects legacy approved/exported orders because their historical business values were never snapshotted; those databases need manual review.

## Repository layout

- `backend/app/api/v1/`: HTTP endpoints.
- `backend/app/services/`: parsing, matching, workflow, learning memory, imports, and exports.
- `backend/app/models/`: SQLAlchemy models and tenant constraints.
- `backend/alembic/`: database migrations.
- `backend/tests/`: automated backend tests.
- `backend/fixtures/`: synthetic Excel import samples.

See [AGENTS.md](AGENTS.md) for repository working conventions.
