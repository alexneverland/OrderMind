from fastapi.testclient import TestClient

from backend.app.config import settings


def test_excel_preview_rejects_oversized_upload_before_parser(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "MAX_IMPORT_UPLOAD_SIZE_BYTES", 16)
    response = client.post(
        "/api/v1/imports/preview",
        data={"entity_type": "products"},
        files={"file": ("products.xlsx", b"x" * 17,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 413
    assert "exceeds maximum" in response.json()["detail"]
