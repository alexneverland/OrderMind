import time
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.ai.remote_providers import OpenAIProvider, AnthropicProvider, _drafts
from backend.app.services import rules_assistant


def test_remote_providers_remap_mock_model(monkeypatch):
    monkeypatch.setattr(settings, "AI_MODEL", "mock-model")
    assert OpenAIProvider().model_name != "mock-model"
    assert AnthropicProvider().model_name != "mock-model"


def test_drafts_tolerates_markdown_json_fences():
    raw = '```json\n{"items":[{"original_text":"10 olives","product_phrase":"olives","quantity":10,"unit":null,"quantity_text":"10","bonus_quantity":0}]}\n```'
    items = _drafts(raw)
    assert len(items) == 1
    assert items[0].product_phrase == "olives"
    assert items[0].quantity == 10


@pytest.mark.asyncio
async def test_rules_assistant_tolerates_markdown_fences(monkeypatch):
    class FakeProvider:
        name = "openai"
        model_name = "gpt-4.1-mini"

        async def _complete(self, prompt, system_instruction=None):
            return '```json\n{"settings_patch":{"bonus_enabled":true},"quantity_rules":[],"export_patch":null,"unsupported_rules":[]}\n```'

    monkeypatch.setattr(rules_assistant, "get_ai_provider", lambda: FakeProvider())
    result = await rules_assistant.analyze_rule_description("Enable bonus")
    assert result.settings_patch.bonus_enabled is True


def test_imports_preview_rejects_legacy_xls_clearly():
    client = TestClient(app, base_url="http://127.0.0.1:8001")
    response = client.post(
        "/api/v1/imports/preview",
        data={"entity_type": "products"},
        files={"file": ("legacy.xls", b"dummy", "application/vnd.ms-excel")},
    )
    assert response.status_code == 400
    assert ".xls" in response.json()["detail"].lower()


def test_async_file_preview_job_lifecycle():
    client = TestClient(app, base_url="http://127.0.0.1:8001")
    create_resp = client.post(
        "/api/v1/orders/file-preview/jobs",
        files={"file": ("order.txt", b"5 cases Feta 400g", "text/plain")},
    )
    assert create_resp.status_code == 202
    job = create_resp.json()
    assert job["job_id"]
    assert job["status"] in {"pending", "processing", "completed"}

    for _ in range(30):
        poll_resp = client.get(f"/api/v1/orders/file-preview/jobs/{job['job_id']}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        if data["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert data["status"] == "completed"
    assert data["text"] == "5 cases Feta 400g"
    assert data["method"] == "text"


def test_async_file_preview_job_rejects_invalid_pdf_upfront_and_404_unknown():
    client = TestClient(app, base_url="http://127.0.0.1:8001")
    bad = client.post(
        "/api/v1/orders/file-preview/jobs",
        files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
    )
    assert bad.status_code == 400

    missing = client.get("/api/v1/orders/file-preview/jobs/does-not-exist")
    assert missing.status_code == 404
