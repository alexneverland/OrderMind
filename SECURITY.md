# Security and data handling

OrderMind is currently a local application without authentication or user authorization. Bind Uvicorn to `127.0.0.1` and use it on a trusted machine. Company constraints protect relationships in the database; they do not restrict who can call the HTTP API. Internet-facing deployment requires a separate security review and access controls.

Keep API keys and Google Cloud credentials outside version control. Local AI settings are stored in the ignored `.env`; restrict access to that file and the database. The settings API is limited to localhost and does not return API keys. Use only synthetic data in repository fixtures, tests, issues, and screenshots.

The offline mock provider does not call an AI service. Selecting Gemini, OpenAI, Claude, or Vertex sends customer input to the configured provider for extraction, and image/scanned-PDF OCR sends the document content. Review the provider's account settings and data handling before using confidential customer information.

Uploaded binaries are converted to editable text and are not retained by OrderMind. Submitted text, order lines, corrections, and approved snapshots remain in SQLite. Protect database backups and exports as business data. For a live SQLite backup, use the backup API or `VACUUM INTO` instead of copying a database file during writes.

Report a suspected vulnerability through the repository's **Security → Report a vulnerability** option if enabled. If private reporting is unavailable, contact the repository owner privately before sending details. Do not put credentials, personal data, customer records, or exploitable details in a public issue.

There is no security support commitment for older releases. Reproduce reports against the current `main` and include versions and a synthetic reproduction. Never send a live database or a usable API key.
