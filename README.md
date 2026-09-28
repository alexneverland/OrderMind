# OrderMind

> **Intelligent Multi-Channel B2B Order Intake & Matching Platform**

OrderMind is a platform designed for B2B distributors and wholesalers that receive orders from customers in diverse, unstructured formats (plain text, emails, PDFs, images, Excel, spreadsheets, etc.). 

The core philosophy of OrderMind is: **AI understands language and extracts intent, but the backend and the real business master data are the single source of truth.**

---

## 🎯 Core Philosophy & Processing Pipeline

OrderMind is **not a chatbot**. The LLM never hallucinates or guesses product SKUs directly out of thin air. Instead, the backend drives deterministic catalog filtering, fuzzy matching, historical alias resolution, and unit validation, calling the AI only for natural language extraction and disambiguation among a tight candidate set.

```text
INPUT (Plain text, Email, PDF, Image, etc.)
  ↓
Input Normalization (Adapter Layer)
  ↓
AI Extraction (Entities, Quantities, Unit Phrases)
  ↓
Customer Detection (Sender, Phone, Manual selection)
  ↓
Product / Quantity / Unit Extraction
  ↓
Matching Engine (SKU, Barcodes, Aliases, Fuzzy, Semantic)
  ↓
Confidence Scoring & Reason Explanation
  ↓
Human Review (Review queue with [Confirm] / [Change])
  ↓
SQL Learning Memory (Aliases, Human corrections)
  ↓
Final Structured Order
  ↓
Configurable Export (Excel, CSV, JSON, ERP integrations)
```

---

## 🚀 Key Architectural Pillars

1. **Deterministic Business Source of Truth**: Customers, Products, Packaging, Units, and Customer-specific Aliases live in a relational SQL database.
2. **Provider-Agnostic AI Layer**: Abstracted AI provider interface (`AIProvider`) supporting Google Gemini, Vertex AI, OpenAI, Anthropic Claude, and Mock mode for testing.
3. **Extensible Input Adapters**: Pluggable `InputAdapter` interface (Plain text for MVP; extensible to PDF, Image, Excel, Email without touching core logic).
4. **Explainable Confidence Scoring**: Every matched item receives a score calculated from deterministic weighted factors (exact SKU, barcode, customer alias, previous confirmations, packaging match) with clear human-readable explanations.
5. **SQL Learning Memory**:
   - `CustomerProductAlias`: Customer-specific phrases learned and weighted through usage.
   - `HumanCorrection`: Complete audit trail of operator corrections to improve future recommendations.
6. **Configurable Export Profiles**: User-defined output column mappings for Excel, CSV, and JSON (direct ERP import compatibility).

---

## 🛠️ Tech Stack (MVP)

- **Backend**: Python 3.12+ / FastAPI / Pydantic v2 / SQLAlchemy 2.0 / Alembic
- **Database**: SQLite (local development) / PostgreSQL (production ready via SQLAlchemy)
- **Data & Excel Processing**: Pandas, OpenPyXL, RapidFuzz
- **Frontend**: Clean modern Web UI (FastAPI static/SPA)
- **AI Integrations**: Google Gemini API, OpenAI, Claude, Vertex AI (via modular adapters)

---

## 🔒 Security Notice

- No API keys, credentials, or actual business data are ever committed to Git.
- Always use a local `.env` file copied from `.env.example`.
