# Focused prompt injection and local API review

Date: 2026-09-30. Scope: extraction/OCR across Gemini, Vertex, OpenAI and Claude, rule analysis/application, grounding, tenant checks, React text rendering and spreadsheet exports. This is a focused code review and deterministic boundary test pass, not a comprehensive penetration test or a claim that prompt injection has been eliminated.

## Findings corrected

1. **Spreadsheet formula injection in bonus marker (high).** Four-column export sanitized SKU and description but wrote the profile's bonus marker directly. `=1+1` became a formula cell; the marker can also originate in a reviewed AI proposal. The shared row expansion now sanitizes it, covering ordinary order sheets and all three pallet layouts without modifying the stored approval snapshot.
2. **Pre-parsed product evidence bypass (high).** `create-from-match` validated quantities and original text but did not check that the supplied product phrase appeared in that item. A caller could keep a grounded quantity while replacing the product with an unrelated catalog SKU. This route now rejects empty normalized original text and product phrases absent from their item, matching the AI parsing path. Deliberate operator product corrections still use the separate correction workflow.
3. **Foreign browser access to local API (high).** Wildcard CORS and the lack of general Origin/Host checks allowed foreign browser requests to data and mutation endpoints; only AI settings had dedicated local checks. The general application now rejects foreign Host/Origin and cross-site Fetch Metadata requests without Origin, and limits development CORS to the documented Vite origin. PR/branch protection is unrelated to these runtime controls.
4. **Inconsistent model task boundaries (defense in depth).** OCR had no system task instruction on Gemini/Vertex and OpenAI, and weaker instructions on Claude. All now share an OCR system instruction that transcribes embedded commands without obeying them. Extraction's company policy belongs to the system channel; customer/rule text is JSON-serialized separately. Response schemas reject unexpected fields and nonfinite/nonpositive quantities. These prompt changes reduce ambiguity but are not a deterministic security boundary.

## Existing boundaries reviewed

- SDK requests configure no tools; models have no application SQL, filesystem, shell or browser capability. API keys are not interpolated into prompts.
- Catalog matching is deterministic SQL/fuzzy matching. Catalog descriptions/aliases are not passed to an active LLM reranker in this implementation.
- AI parsing validates source snippets, product evidence, numeric quantities and units before matching/persistence. Client-supplied matches are recomputed server-side.
- Rule schemas permit typed settings, quantity bonuses and pallet configuration; arbitrary Python, SQL, settings credentials and unknown actions are rejected. Analyze cannot persist. Apply validates company-owned product/customer/profile references and rolls back invalid proposals.
- Approval/export gates and frozen business values remain in the workflow; AI output cannot declare an order approved.
- React displays these values as text; the reviewed source contains no raw HTML/Markdown rendering sink for AI/customer text. This is a code inspection, not an executed browser XSS campaign.
- Generic CSV/XLSX fields, constants and headers already use formula sanitization. JSON preserves text without spreadsheet escaping.

## Verification

`backend/tests/test_prompt_injection_security.py` injects role-spoofing text and deliberately compromised SDK responses. It checks all four providers' request channels, unknown response authority, rejected ungrounded product/quantity output with no order persisted, rule analysis without persistence, invalid rule responses, API rejection before reads/writes, allowed local/Vite requests, and literal gift markers in actual XLSX cells across normal and palletized layouts.

The test suite also exercises the real Google SDK schema conversion without a network call. A stricter numeric schema using `exclusiveMinimum` was caught during verification because this SDK schema does not accept it; the positive check is therefore enforced locally with a supported nonnegative transport schema.

The fake provider responses intentionally bypass model judgment to test application enforcement. They do not establish live model resistance to attacks. No paid provider calls or real customer files/credentials were used. Backend tests use disposable databases; existing tenant, approval, snapshot and export regression tests must pass alongside the new suite.

Test isolation was also corrected: overriding `get_db` did not prevent TestClient startup from opening the process-wide SQLite engine for WAL configuration. API tests now suppress that global startup operation; WAL behavior remains verified separately against disposable file engines in `test_sqlite_runtime.py`.

Final verification: 251 backend tests and 36 frontend tests passed. The 43 new backend cases include the adversarial boundaries above. The built UI and its assets returned HTTP 200 through the application test client with a localhost base URL; foreign Origin was rejected with HTTP 403. This serving check did not start the live application or open its database. `git diff --check` passed.

## Remaining limitations

- A model may omit items, transcribe falsely or select a malicious instruction that looks like genuine order data and passes grounding. Human comparison to the original is still required.
- A valid but unwanted rules proposal is allowed for review; explicit Apply is the authorization step. Do not apply a proposal blindly.
- Origin/Host checks are not authentication. Local processes can forge headers; keep the API on loopback. Other trusted local web services and browser extensions are outside this isolation guarantee.
- No automated live-provider adversarial evaluations, full file-parser resource-exhaustion audit, comprehensive browser penetration test, authentication or rate limiting were added in this pass.
- The published `v0.1.0` source is unchanged; these fixes need review and a subsequent release.

Design reference: [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html), particularly task/data separation, output validation, least privilege and human approval.

## Import/export follow-up

- CSV profiles were already checked against an allowed delimiter set on creation. The remaining path was a legacy/non-CSV profile with an invalid delimiter changed to CSV without a delimiter update. Create/update schemas now allow only the four supported delimiters, format changes validate the effective stored delimiter, and export rejects invalid legacy values with a controlled business error. An empty legacy delimiter continues to fall back to comma.
- Customer/product imports now acquire `BEGIN IMMEDIATE` after reading the workbook and before looking up existing codes, matching the packaging-import strategy. Two concurrent imports on a disposable WAL database verify that the second observes the first commit and reports a duplicate rather than failing on uniqueness. Import endpoints also roll back remaining integrity conflicts and return HTTP 409. Existing SQLite busy errors remain retryable HTTP 503.
- A shared pre-parser guard bounds DOCX/XLSX archives, including master-data preview/import, to 30 MiB expanded bytes and 1,000 entries and streams contents to check integrity. Tests reject highly compressed oversized content before entering document or DataFrame parsers. This is a targeted ZIP defense, not a full PDF/image/XML resource-exhaustion guarantee.
