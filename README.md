# OrderMind

OrderMind is a B2B order intake workspace. It turns customer order text into reviewable order lines, matches them against a company's own catalog, records operator corrections, and exports approved orders. The catalog and operator decisions are the source of truth; an AI provider extracts text but does not invent products or SKUs.

The operator UI runs at `http://127.0.0.1:8001/` after a frontend build. API docs remain at `http://127.0.0.1:8001/docs`.

## Current scope

- Pasted-text or file order input (TXT, CSV, XLSX, DOCX, PDF, JPG, PNG, WebP); mock order extraction works offline for readable text. Gemini, OpenAI, Claude and Vertex can be selected for text extraction and OCR.
- Company, customer, product, packaging, and export-profile APIs; Excel imports for master data.
- Catalog matching using identifiers, aliases, normalized descriptions, and bounded fuzzy candidates; confidence and review states.
- Operator confirmation/correction, approval with a stored snapshot, and CSV/XLSX/JSON export.
- React operator workspace for order intake, review, approval, export, profile mappings, and catalog browsing with Excel import.
- SQLite database with Alembic migrations and tenant foreign-key constraints.

Email intake, legacy `.doc` files, authentication, and direct ERP integrations are **planned**, not available yet. Exported files can be imported into other systems separately.

## First local run (Windows PowerShell)

Run these commands from the repository root (`C:\OrderMind`). Python 3.12+, uv, and Node.js are required for the UI build.

```powershell
uv sync --frozen
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open `http://127.0.0.1:8001/`. Check `/health` and `/docs` for the API. Stop the server with Ctrl+C. If you rebuild the UI while Uvicorn is running, restart Uvicorn so it picks up the built assets. Port 8001 avoids the local Astakos service currently using port 8000; choose another free port if needed. The `.env` file is local and ignored by Git; the default `AI_PROVIDER=mock` needs no API key. Select a provider in Settings or set `AI_PROVIDER`, `AI_MODEL` and its credentials in `.env`, then restart the server.

For frontend development, run `npm run dev` in `frontend/` and open `http://127.0.0.1:5173/`. Vite proxies `/api` to `http://127.0.0.1:8001`; override with `VITE_API_PROXY_TARGET` if the backend uses another port. The production build uses same-origin `/api/v1`.

On a localhost instance, **Settings → AI extraction** can choose mock, Gemini, OpenAI, Claude or Vertex, set the model, and enter or replace the selected API key. Vertex uses a Google Cloud project and location plus Application Default Credentials on the host. The screen saves settings to the local ignored `.env` and applies them to new orders immediately. The settings API never returns keys. Process environment variables take precedence and cannot be overridden from this screen. The API endpoint is limited to same-origin localhost requests because this milestone has no authentication.

If there is no company yet, the Customers and Products pages show a **Create company** form. The Excel import appears after the company is created and selected.

On a fresh database, create the first company from the dashboard. Select it in the top bar. Under **Customers** and **Products**, add records individually or use **Import from Excel**: choose an `.xlsx` file (up to 10 MB), preview its columns and sample rows, check the suggested column mapping, then import. Customer files need a code and name column; product files need an SKU and description column. The UI reports imported rows and row-level errors. Duplicate customer codes are errors. Duplicate product SKUs remain errors unless the Excel explicitly maps gross kg per piece; then only that trusted weight is updated for the existing SKU. Synthetic sample workbooks are in `backend/fixtures/`. Select a company in the top bar, then use **New order** to choose a customer and paste text or upload a customer file (up to 10 MB). TXT, CSV, XLSX, DOCX and text PDFs are read locally. JPG, PNG, WebP, handwritten photos and scanned PDFs require a configured Gemini, OpenAI, Claude or Vertex provider in **Settings**; the mock provider cannot transcribe them. OCR marks unreadable words or numbers as `[UNCLEAR]` and the operator must correct those before continuing. Check and edit all extracted text against the original file before selecting **Parse & Match**, especially product names, quantities and units. The original file is not saved; the order stores the submitted text. Legacy `.doc` and `.xls` files are not supported yet. Review each line, confirm or correct its product, edit final quantity/unit when needed, approve when all lines are ready, then select an export profile and download. Create profiles under **Export profiles**. The mock parser works without a key.

Direct ERP synchronization is future work. Its adapter should map the ERP's customer and product identities into the same company-scoped master data; no live ERP connection or background sync runs today.

On **Products**, import packaging Excel after its parent products. Reimporting an identical workbook skips existing packaging rows. A code/barcode that points to changed packaging values is reported as a row conflict; the import does not silently alter ratios used by order matching. Packaging without a code or barcode is recognized by its product, type, quantity ratio, weight, and unit; a changed definition with the same product/type/unit is flagged for review instead of inserted as another unidentified package. Give distinct package sizes stable codes or barcodes. Imports for one company serialize during the SQLite write phase to avoid duplicate rows from overlapping uploads.

Order intake does not require a fixed customer sheet layout. The configured AI provider extracts one product per requested item from text, spreadsheets, documents, or OCR text and supplies the exact quantity phrase for validation. A unit in a product description or source M.M column does not set the ordered unit. An explicit unit next to the requested quantity takes precedence. The mock provider remains a simple offline text parser and does not understand arbitrary layouts or promotions.

### Pallet planning

Pallet planning is optional on each four-column order-sheet export profile and disabled until explicitly configured. Configure it under **Export profiles** or describe it in **Settings → Company business rules**. AI Analyze proposes group membership, capacities, row counting and layout; the operator resolves company catalog references and applies the proposal. Runtime planning is deterministic and does not call AI. The manual editor supports ordered dedicated SKU groups, optional maximum gross weight and row limits (at least one when enabled), actual exported rows or logical product lines, and three layouts: one sheet with pallet sections, one worksheet per pallet, or one workbook per pallet inside a ZIP. Titles, headers and separator rows do not count against product capacity. Order review offers a pallet preview with assigned SKUs, paid/free quantities, gross weight, row count and warnings before download.

For weight-limited pallets, kg orders weigh their approved kg quantity. Piece orders require trusted **gross kg per piece**, entered on Products or mapped from the product Excel column «Μικτό βάρος»; case orders require trusted gross kg per case or a validated pieces-per-case ratio multiplied by gross kg per piece. Paid and free units both contribute physical weight. Existing `Packaging.weight` has no guaranteed unit or per-unit meaning and is not used for pallet limits. Missing trusted weight fails clearly with the SKU. Approval freezes the relevant weight basis and profile policy; later master-data or profile changes do not silently alter the approved pallet export. Existing approved snapshots without those fields are not backfilled. The final ZIP bytes are hashed in the normal export audit.

### Company rules and export policy

OrderMind's engine can retain bonus quantities, normalize units, use packaging ratios, and learn operator unit corrections. An order with no stated unit is extracted as `unknown`; this records customer evidence and does not mean pieces. The selected company's **Settings → Company business rules** determine whether `10+1` means paid plus bonus, whether a unitless order needs review or a configured fallback, whether packaging conversion is allowed, and whether unit corrections are learned. New companies start with bonus, conversion, and learning disabled; unitless orders require review and need an operator-selected final unit before approval. These rules are stored as typed columns in `company_business_settings` and validated by the API. An AI provider may extract evidence but cannot activate a rule.

The business rules assistant accepts a natural-language description and returns a structured proposal for review. It uses the selected AI provider, but **Analyze rules never saves anything**. Only **Apply rules** persists validated settings, optional order-sheet export conventions, and typed `quantity_bonus` promotions. Unsupported requests are shown separately. The manual controls remain under Advanced settings. The LLM is a configuration assistant only; the order engine never asks it to execute a rule or calculate a promotion.

`quantity_bonus` supports `greater_than` (strictly above), `greater_or_equal` (at least), and `per_quantity` (`floor(paid_quantity / threshold) × reward`). For example, every 10 cases gives 1 free case: 9 → 0, 10 → 1, 25 → 2. Above 30 pieces gives 2 free pieces only from 31 onward. Rules may apply to every product/customer or to one company-owned product/customer. Trigger and reward use the same canonical unit; mixed-unit conversion is deliberately unsupported. Multiple matching promotions do not stack: the line requires review. A customer-stated bonus takes precedence over a calculated bonus; if the values disagree, the operator must choose a final bonus before approval.

The review keeps three values distinct: the customer's `bonus_quantity`, the rule's `calculated_bonus_quantity`, and an optional operator `final_bonus_quantity`. Approval stores those values plus the applied rule ID, configuration and explanation in the immutable snapshot. Disabling or editing a rule later does not alter approved orders. Promotion rules are new-company data; the migration leaves historical order bonuses unchanged.

Output conventions belong to each **Export profile**. A 4-column order sheet uses SKU, description, marker, and quantity. Its settings choose whether bonus goods get a separate row, the marker text, whether quantity stays in the source unit or becomes pieces using `pieces_per_case`, and whether to include a header. Missing or ambiguous conversion ratios fail safely. An order with bonus goods cannot export through a profile that has no bonus row policy. Approval freezes line values, conversion ratios, company rules, and the order-sheet rules of existing export profiles for deterministic re-export. Profiles created after approval use their current rules with frozen order values for ordinary exports. A newly selected palletized profile requires policy and trusted weight frozen at approval and rejects historical orders without them. General CSV/XLSX/JSON column mappings are still live profile configuration and are not versioned by this refactor.

The migration inserts compatibility rules for **all companies that already exist**, because the previous behavior was global; it does not identify a company by name. Existing 4-column profiles receive the former separate bonus row, `Α` marker, piece conversion, and headerless output. Companies created after the migration retain neutral defaults. To configure a new company with the former conventions, enable paid-plus-bonus syntax and packaging conversion in Company business rules, then configure the desired 4-column profile with a separate bonus row, `Α`, and piece output. Changes to company rules or profile rules do not change approved orders that froze those rules.

The `HOST` and `PORT` settings in `.env` do not change the command above; the Uvicorn CLI flags choose the listening address and port. The default `DATABASE_URL=sqlite:///./ordermind.db` is relative to the working directory, so run migrations and the server from the repository root. The API does **not** create or migrate tables at startup.

## Dependencies and tests

`pyproject.toml` declares dependencies and `uv.lock` pins their resolution. Use `uv sync --frozen` for a reproducible environment; there is no separate `requirements.txt` to keep in sync.

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m alembic check
cd frontend
npm test
npm run build
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
- `frontend/src/`: React operator workspace, API client, pages, and UI tests.

See [AGENTS.md](AGENTS.md) for repository working conventions.
