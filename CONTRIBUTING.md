# Contributing to OrderMind

Unless explicitly stated otherwise, contributions intentionally submitted for inclusion in OrderMind are provided under the Apache License, Version 2.0, as described in section 5 of [LICENSE](LICENSE). Preserve existing copyright and third-party license notices.

Read the local setup in [README.md](README.md) and the implementation boundaries in [AGENTS.md](AGENTS.md). Use a separate SQLite database and synthetic master data for development. Never include customer files, exports, credentials, database copies, or personal contact details in a commit or issue.

Create a focused branch from the current `main`, make the change, and open a pull request. Describe the user-visible problem, resulting behavior, and verification. Inspect automated review feedback before requesting a merge. The repository uses squash merges and deletes completed branches.

Backend dependencies are declared in `pyproject.toml` and resolved in `uv.lock`; frontend dependencies use `frontend/package.json` and `frontend/package-lock.json`. Keep the corresponding lockfile updated when changing dependencies. Do not add a parallel `requirements.txt`.

Run the checks relevant to your change:

```sh
uv sync --frozen
uv run --frozen python -m pytest backend/tests -q
uv run --frozen python -m alembic check
git diff --check
cd frontend
npm ci
npm test
npm run build
```

`alembic check` needs a development database migrated to head; backend tests exercise migrations on their own temporary databases. For schema changes, verify a fresh migration and the relevant previous schema, then check SQLite foreign keys. Do not run test migrations against populated business data.

For UI changes, check the affected flow in the running application as well as its automated tests. For order logic, verify tenant isolation, optimistic conflicts, snapshot semantics, and re-export behavior where applicable. Mock-provider tests should not require paid AI calls.

Use fictional names and reserved email domains in examples. Share a minimal synthetic reproduction when reporting a bug, with dependency versions and the relevant error message. Remove tokens and customer data from logs and screenshots. Follow [SECURITY.md](SECURITY.md) for sensitive findings.
