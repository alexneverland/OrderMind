from fastapi.testclient import TestClient

from backend.app.api.v1 import runtime_settings
from backend.app.config import Settings, settings
from backend.app.main import app


def test_ai_settings_are_local_only_and_never_return_the_key(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("APP_ENV=development\nAI_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setattr(runtime_settings, "SETTINGS_ENV_PATH", env_path)
    originals = (settings.AI_PROVIDER, settings.AI_MODEL, settings.GEMINI_API_KEY,
                 settings.OPENAI_API_KEY, settings.ANTHROPIC_API_KEY,
                 settings.GOOGLE_CLOUD_PROJECT, settings.GOOGLE_CLOUD_LOCATION)
    try:
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            initial = client.get("/api/v1/runtime-settings/ai")
            assert initial.status_code == 200
            assert "gemini_api_key" not in initial.json()

            rejected = client.put(
                "/api/v1/runtime-settings/ai",
                json={"provider": "gemini", "model": "gemini-test"},
            )
            if not settings.GEMINI_API_KEY:
                assert rejected.status_code == 400

            saved = client.put(
                "/api/v1/runtime-settings/ai",
                json={"provider": "gemini", "model": "gemini-test", "gemini_api_key": "example-test-key"},
            )
            assert saved.status_code == 200
            assert saved.json()["provider"] == "gemini"
            assert saved.json()["model"] == "gemini-test"
            assert saved.json()["gemini_key_configured"] is True
            assert "example-test-key" not in saved.text
            assert "APP_ENV=development" in env_path.read_text(encoding="utf-8")
            assert 'GEMINI_API_KEY="example-test-key"' in env_path.read_text(encoding="utf-8")
            restored = Settings(_env_file=env_path)
            assert restored.AI_PROVIDER == "gemini"
            assert restored.AI_MODEL == "gemini-test"
            assert restored.GEMINI_API_KEY == "example-test-key"

            openai = client.put("/api/v1/runtime-settings/ai", json={
                "provider": "openai", "model": "gpt-test", "openai_api_key": "openai-test-key",
            })
            assert openai.status_code == 200
            assert openai.json()["openai_key_configured"] is True
            assert "openai-test-key" not in openai.text
            claude = client.put("/api/v1/runtime-settings/ai", json={
                "provider": "anthropic", "model": "claude-test", "anthropic_api_key": "claude-test-key",
            })
            assert claude.status_code == 200
            assert claude.json()["anthropic_key_configured"] is True
            vertex = client.put("/api/v1/runtime-settings/ai", json={
                "provider": "vertex", "model": "gemini-test",
                "google_cloud_project": "test-project", "google_cloud_location": "us-central1",
            })
            assert vertex.status_code == 200
            assert vertex.json()["google_cloud_project"] == "test-project"

            if settings.APP_ENV == "development":
                vite_origin = client.get(
                    "/api/v1/runtime-settings/ai",
                    headers={"Origin": "http://127.0.0.1:5173"},
                )
                assert vite_origin.status_code == 200

            foreign_origin = client.put(
                "/api/v1/runtime-settings/ai",
                headers={"Origin": "https://other.example"},
                json={"provider": "mock", "model": "mock-model"},
            )
            assert foreign_origin.status_code == 403
            foreign_host = client.get(
                "/api/v1/runtime-settings/ai", headers={"Host": "other.example"},
            )
            assert foreign_host.status_code == 403
        with TestClient(app, client=("192.0.2.10", 50000)) as remote:
            assert remote.get("/api/v1/runtime-settings/ai").status_code == 403
    finally:
        (settings.AI_PROVIDER, settings.AI_MODEL, settings.GEMINI_API_KEY,
         settings.OPENAI_API_KEY, settings.ANTHROPIC_API_KEY,
         settings.GOOGLE_CLOUD_PROJECT, settings.GOOGLE_CLOUD_LOCATION) = originals
