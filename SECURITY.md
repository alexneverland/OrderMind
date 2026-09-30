# Security and data handling

OrderMind is currently a local application without authentication or user authorization. Bind Uvicorn to `127.0.0.1` and use it on a trusted machine. Company constraints protect relationships in the database; they do not restrict who can call the HTTP API. Internet-facing deployment requires a separate security review and access controls.

The application accepts only localhost Host names and rejects foreign browser Origins, including `null`, and cross-site Fetch Metadata requests without an Origin. Same-origin browser requests and local CLI requests without browser headers remain supported. Development additionally permits `http://127.0.0.1:5173` for Vite. These checks protect the local browser boundary; they are not authentication and do not stop a local process from calling the API.

## AI and untrusted documents

Customer input, OCR text and AI responses are untrusted. Extraction and OCR use system task instructions; extraction/rule descriptions are serialized separately as data. Models receive no application tools, database access or credentials in prompt content. Provider credentials are used only by the SDK transport. Extraction responses reject extra fields and nonfinite/nonpositive quantities; application grounding and company-scoped matching validate business evidence. Analyze rules returns a proposal and cannot apply it; an operator must explicitly apply reviewed changes. Spreadsheet export sanitizes formula-like text, including gift markers.

These controls do not prove that a model always follows instructions or extracts every item correctly. An injected instruction can still corrupt OCR or produce plausible, source-grounded but unwanted suggestions. Check the source document, every extracted item and quantity, and the complete rules proposal before approval/Apply. Do not treat an AI response or confidence score as authorization. See [the focused review](docs/security-review.md) for evidence and limits.

## Data handling and reporting

Keep API keys and Google Cloud credentials outside version control. Local AI settings are stored in the ignored `.env`; restrict access to that file and the database. The settings API is limited to localhost and does not return API keys. Use only synthetic data in repository fixtures, tests, issues, and screenshots.

The offline mock provider does not call an AI service. Selecting Gemini, OpenAI, Claude, or Vertex sends customer input to the configured provider for extraction, and image/scanned-PDF OCR sends the document content. Review the provider's account settings and data handling before using confidential customer information.

Uploaded binaries are converted to editable text and are not retained by OrderMind. Submitted text, order lines, corrections, and approved snapshots remain in SQLite. Protect database backups and exports as business data. For a live SQLite backup, use the backup API or `VACUUM INTO` instead of copying a database file during writes.

Report a suspected vulnerability through the repository's **Security → Report a vulnerability** option if enabled. If private reporting is unavailable, contact the repository owner privately before sending details. Do not put credentials, personal data, customer records, or exploitable details in a public issue.

There is no security support commitment for older releases. Reproduce reports against the current `main` and include versions and a synthetic reproduction. Never send a live database or a usable API key.
