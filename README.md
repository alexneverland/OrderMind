# OrderMind

OrderMind is a local B2B order intake and review workspace built with FastAPI, React, and SQLite. It turns customer orders into reviewable lines, matches them against each company's catalog, records operator corrections, and exports approved orders. The catalog and operator decisions are the source of truth; an AI provider extracts customer evidence and cannot create catalog products or SKUs.

The operator UI runs at `http://127.0.0.1:8001/` after a frontend build. API docs remain at `http://127.0.0.1:8001/docs`.

## Workspace preview

![OrderMind dashboard showing pending and approved orders for a synthetic demo company](docs/images/dashboard.jpg)

**Intake → catalog matching → operator review → approval → export.** Browse the [screenshots and workflow walkthrough](docs/screenshots.md) for order review, Excel catalog import, company rules, and pallet planning. All screenshots use synthetic demo data.

## Current scope

- Pasted-text or file order input (TXT, CSV, XLSX, DOCX, PDF, JPG, PNG, WebP); mock order extraction works offline for readable text. Gemini, OpenAI, Claude and Vertex can be selected for text extraction and OCR.
- Company, customer, product, packaging, and export-profile APIs; Excel imports for master data.
- Catalog matching using identifiers, aliases, normalized descriptions, and bounded fuzzy candidates; confidence and review states.
- Operator confirmation/correction, approval with a stored snapshot, and CSV/XLSX/JSON export.
- React operator workspace for order intake, review, approval, export, profile mappings, and catalog browsing with Excel import.
- SQLite database with Alembic migrations and tenant foreign-key constraints.

Email intake, legacy `.doc` files, authentication, and direct ERP integrations are **planned**, not available yet. Exported files can be imported into other systems separately.

The current application is intended for a trusted local operator. Keep the API bound to `127.0.0.1`: company isolation in the database does not provide user authentication or access control. See [SECURITY.md](SECURITY.md) for data handling and reporting guidance.

## First local run (Windows PowerShell)

Install Git, Python 3.12 or later, uv, and Node.js with npm. Supported Node versions are 20.19+ within 20.x, 22.12+ within 22.x, or 24+. These satisfy both Vite and Vitest. Clone the repository, or extract its downloaded ZIP and open a terminal in the extracted repository root.

```powershell
git clone https://github.com/alexneverland/OrderMind.git
cd OrderMind
uv sync --frozen
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open `http://127.0.0.1:8001/`. Check `/health` and `/docs` for the API. Stop the server with Ctrl+C. If you rebuild the UI while Uvicorn is running, restart Uvicorn so it picks up the built assets. If port 8001 is occupied, choose another free port in the Uvicorn command. The `.env` file is local and ignored by Git; the default `AI_PROVIDER=mock` needs no API key. Select a provider in Settings or set `AI_PROVIDER`, `AI_MODEL` and its credentials in `.env`, then restart the server.

### Linux and macOS

After cloning and entering the repository root, use:

```sh
uv sync --frozen
test -f .env || cp .env.example .env
uv run --frozen python -m alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
uv run --frozen python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

The cross-platform `uv run --frozen python` commands also work in PowerShell. No global Python package installation is needed.

For frontend development, run `npm run dev` in `frontend/` and open `http://127.0.0.1:5173/`. Vite proxies `/api` to `http://127.0.0.1:8001`; override with `VITE_API_PROXY_TARGET` if the backend uses another port. The production build uses same-origin `/api/v1`.

On a localhost instance, **Settings → AI extraction** can choose mock, Gemini, OpenAI, Claude or Vertex, set the model, and enter or replace the selected API key. Vertex uses a Google Cloud project and location plus Application Default Credentials on the host. The screen saves settings to the local ignored `.env` and applies them to new orders immediately. The settings API never returns keys. Process environment variables take precedence and cannot be overridden from this screen. The API endpoint is limited to same-origin localhost requests because this milestone has no authentication.

### First order

1. Create a company on the dashboard or the Customers/Products page, then select it in the top bar.
2. Import `backend/fixtures/sample_customers.xlsx` under **Customers** and `sample_products.xlsx` under **Products**. Preview and confirm the column mappings. These files contain synthetic examples.
3. Optionally import `sample_packaging.xlsx` under **Products**, after the products exist.
4. Under **New order**, select a customer. For an offline smoke test with the mock provider, paste `5 τεμάχια Γαλοπούλα Καπνιστή 1kg`. Parse and review the suggested product, quantity, and final unit.
5. Resolve every pending line, then approve. New companies have neutral business rules; configure company conventions explicitly when needed.
6. Create an export profile under **Export profiles**. A general CSV/XLSX profile needs column mappings; a four-column order sheet has fixed columns. Select the profile on the approved order and download its export.

The Excel import appears after a company is selected. The mock provider is a limited text parser; arbitrary layouts, OCR and AI rule proposals require a configured remote provider.

DOCX/XLSX files, including master-data workbooks, must contain at most 30 MiB of expanded ZIP content and 1,000 archive entries. Compressed upload size alone is not sufficient; oversized or corrupt archives are rejected before parsing.

On a fresh database, create the first company from the dashboard. Select it in the top bar. Under **Customers** and **Products**, add records individually or use **Import from Excel**: choose an `.xlsx` file (up to 10 MB), preview its columns and sample rows, check the suggested column mapping, then import. Customer files need a code and name column; product files need an SKU and description column. The UI reports imported rows and row-level errors. Duplicate customer codes are errors. Duplicate product SKUs remain errors unless the Excel explicitly maps gross kg per piece; then only that trusted weight is updated for the existing SKU. Synthetic sample workbooks are in `backend/fixtures/`. Select a company in the top bar, then use **New order** to choose a customer and paste text or upload a customer file (up to 10 MB). TXT, CSV, XLSX, DOCX and text PDFs are read locally. JPG, PNG, WebP, handwritten photos and scanned PDFs require a configured Gemini, OpenAI, Claude or Vertex provider in **Settings**; the mock provider cannot transcribe them. OCR marks unreadable words or numbers as `[UNCLEAR]` and the operator must correct those before continuing. Check and edit all extracted text against the original file before selecting **Parse & Match**, especially product names, quantities and units. The original file is not saved; the order stores the submitted text. Legacy `.doc` and `.xls` files are not supported yet. Review each line, confirm or correct its product, edit final quantity/unit when needed, approve when all lines are ready, then select an export profile and download. Create profiles under **Export profiles**. The mock parser works without a key.

Direct ERP synchronization is future work. Its adapter should map the ERP's customer and product identities into the same company-scoped master data; no live ERP connection or background sync runs today.

On **Products**, import packaging Excel after its parent products. Reimporting an identical workbook skips existing packaging rows. A code/barcode that points to changed packaging values is reported as a row conflict; the import does not silently alter ratios used by order matching. Packaging without a code or barcode is recognized by its product, type, quantity ratio, weight, and unit; a changed definition with the same product/type/unit is flagged for review instead of inserted as another unidentified package. Give distinct package sizes stable codes or barcodes. Imports for one company serialize during the SQLite write phase to avoid duplicate rows from overlapping uploads.

Order intake does not require a fixed customer sheet layout. The configured AI provider extracts one product per requested item from text, spreadsheets, documents, or OCR text and supplies the exact quantity phrase for validation. A unit in a product description or source M.M column does not set the ordered unit. An explicit unit next to the requested quantity takes precedence. The mock provider remains a simple offline text parser and does not understand arbitrary layouts or promotions.

### Pallet planning

Pallet planning is optional on each four-column order-sheet export profile and disabled until explicitly configured. Configure it under **Export profiles** or describe it in **Settings → Company business rules**. AI Analyze proposes group membership, capacities, row counting and layout; the operator resolves company catalog references and applies the proposal. Runtime planning is deterministic and does not call AI. The manual editor supports ordered dedicated SKU groups, optional maximum gross weight and row limits (at least one when enabled), actual exported rows or logical product lines, and three layouts: one sheet with pallet sections, one worksheet per pallet, or one workbook per pallet inside a ZIP. Titles, headers and separator rows do not count against product capacity. Order review offers a pallet preview with assigned SKUs, paid/free quantities, gross weight, row count and warnings before download.

For weight-limited pallets, kg orders weigh their approved kg quantity. Piece orders require trusted **gross kg per piece**, entered on Products or mapped from the product Excel column «Μικτό βάρος»; case orders require trusted gross kg per case or a validated pieces-per-case ratio multiplied by gross kg per piece. Paid and free units both contribute physical weight. Existing `Packaging.weight` has no guaranteed unit or per-unit meaning and is not used for pallet limits. If any enabled weight-limited profile requires missing weight, approval is rejected with the profile and SKU; add the weight or resolve the final unit before approving again. Approval freezes the relevant weight basis and profile policy; later master-data or profile changes do not silently alter the approved pallet export. Pallet preview is available only for profiles enabled in the approved snapshot. Existing approved snapshots without those fields are not backfilled. The final ZIP bytes are hashed in the normal export audit.

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

The two pre-Alembic compatibility tests also need the old Git revision `1cd7f52`; they are skipped when that revision is unavailable, such as in a downloaded ZIP or a shallow clone. Fresh-install migrations are tested independently of Git history.

If pytest reports a Windows permission error for its shared temporary directory, run it with a new disposable directory: `uv run --frozen python -m pytest backend/tests -q --basetemp .pytest_local_run`. Do not point `--basetemp` at a folder containing files you want to keep.

### Updating a local installation

Stop Uvicorn, back up any populated database using a safe method described below, then pull the desired version. Run `uv sync --frozen`, `alembic upgrade head` through the project Python environment, and `npm ci` / `npm run build` in `frontend/`. Restart Uvicorn from the repository root. Preserve your local `.env` and database.

### Troubleshooting

- `/` returns `Not Found`: build the frontend, then restart Uvicorn from the repository root.
- `no such table`: run `uv run --frozen python -m alembic upgrade head` from that root.
- No import controls: create and select a company first.
- Image or scanned PDF cannot be read: configure a supported AI provider and model; mock does not provide OCR.
- Address already in use: select a free port and adjust `VITE_API_PROXY_TARGET` for Vite development.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and review instructions, [AGENTS.md](AGENTS.md) for agent working conventions, and [SECURITY.md](SECURITY.md) for security and data handling.

## License and author

Copyright 2026 Lazaros Avramidis ([alexneverland](https://github.com/alexneverland)).

OrderMind is licensed under the [Apache License, Version 2.0](LICENSE). Commercial use and modified distributions are permitted subject to its terms; publishing modifications is not required. See [NOTICE](NOTICE) for project attribution. Third-party dependencies retain their own licenses. This license does not grant rights to use the author's trademarks.
