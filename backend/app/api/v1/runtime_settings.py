"""Local operator controls for the two implemented extraction providers."""

import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from backend.app.config import settings

router = APIRouter(prefix="/runtime-settings", tags=["Runtime Settings"])
SETTINGS_ENV_PATH = Path.cwd() / ".env"
_write_lock = Lock()


class AISettingsResponse(BaseModel):
    provider: str
    model: str
    gemini_key_configured: bool
    openai_key_configured: bool
    anthropic_key_configured: bool
    google_cloud_project: str | None
    google_cloud_location: str | None


class AISettingsUpdate(BaseModel):
    provider: str = Field(pattern="^(mock|gemini|openai|anthropic|vertex)$")
    model: str = Field(min_length=1, max_length=120)
    gemini_api_key: SecretStr | None = Field(default=None, max_length=512)
    openai_api_key: SecretStr | None = Field(default=None, max_length=512)
    anthropic_api_key: SecretStr | None = Field(default=None, max_length=512)
    google_cloud_project: str | None = Field(default=None, max_length=120)
    google_cloud_location: str | None = Field(default=None, max_length=120)


def _local_request(request: Request) -> None:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="AI settings are available only on localhost")
    host = request.headers.get("host", "")
    try:
        hostname = urlsplit(f"http://{host}").hostname
    except ValueError:
        hostname = None
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(status_code=403, detail="AI settings require a localhost Host")
    origin = request.headers.get("origin")
    allowed_origins = {f"{request.url.scheme}://{host}"}
    if settings.APP_ENV == "development":
        allowed_origins.add("http://127.0.0.1:5173")
    if origin and origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="AI settings require a same-origin request")


def _view() -> AISettingsResponse:
    return AISettingsResponse(
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL,
        gemini_key_configured=bool(settings.GEMINI_API_KEY),
        openai_key_configured=bool(settings.OPENAI_API_KEY),
        anthropic_key_configured=bool(settings.ANTHROPIC_API_KEY),
        google_cloud_project=settings.GOOGLE_CLOUD_PROJECT,
        google_cloud_location=settings.GOOGLE_CLOUD_LOCATION,
    )


@router.get("/ai", response_model=AISettingsResponse)
def get_ai_settings(request: Request):
    _local_request(request)
    return _view()


@router.put("/ai", response_model=AISettingsResponse)
def update_ai_settings(payload: AISettingsUpdate, request: Request):
    _local_request(request)
    if any(name in os.environ for name in ("AI_PROVIDER", "AI_MODEL", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")):
        raise HTTPException(status_code=409, detail="AI settings are controlled by process environment variables")

    model = payload.model.strip()
    keys = {
        "GEMINI_API_KEY": payload.gemini_api_key,
        "OPENAI_API_KEY": payload.openai_api_key,
        "ANTHROPIC_API_KEY": payload.anthropic_api_key,
    }
    key_values = {name: secret.get_secret_value().strip() for name, secret in keys.items() if secret is not None}
    if not model or any(char in model for char in "\r\n"):
        raise HTTPException(status_code=400, detail="Enter a valid model name")
    if any(not value or any(char in value for char in "\r\n") for value in key_values.values()):
        raise HTTPException(status_code=400, detail="Enter a valid API key")
    credential_field = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    selected_key = credential_field.get(payload.provider)
    if selected_key and not (key_values.get(selected_key) or getattr(settings, selected_key)):
        raise HTTPException(status_code=400, detail=f"Enter a {payload.provider} API key before enabling it")

    project = payload.google_cloud_project.strip() if payload.google_cloud_project is not None else settings.GOOGLE_CLOUD_PROJECT
    location = payload.google_cloud_location.strip() if payload.google_cloud_location is not None else settings.GOOGLE_CLOUD_LOCATION
    if payload.provider == "vertex" and not project:
        raise HTTPException(status_code=400, detail="Enter a Google Cloud project before enabling Vertex")
    if any(value is not None and (not value or any(char in value for char in "\r\n=\"")) for value in (
        project if payload.google_cloud_project is not None else None,
        location if payload.google_cloud_location is not None else None,
    )):
        raise HTTPException(status_code=400, detail="Enter a valid Google Cloud project and location")

    values = {"AI_PROVIDER": payload.provider, "AI_MODEL": model}
    values.update(key_values)
    if payload.google_cloud_project is not None:
        values["GOOGLE_CLOUD_PROJECT"] = project
    if payload.google_cloud_location is not None:
        values["GOOGLE_CLOUD_LOCATION"] = location
    with _write_lock:
        try:
            existing = SETTINGS_ENV_PATH.read_text(encoding="utf-8") if SETTINGS_ENV_PATH.exists() else ""
            lines = existing.splitlines()
            seen = set()
            updated = []
            for line in lines:
                name = line.split("=", 1)[0].strip()
                if name in values:
                    if name not in seen:
                        updated.append(f"{name}={json.dumps(values[name])}")
                        seen.add(name)
                else:
                    updated.append(line)
            for name, value in values.items():
                if name not in seen:
                    updated.append(f"{name}={json.dumps(value)}")
            SETTINGS_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=SETTINGS_ENV_PATH.parent,
                prefix=".env.ordermind-settings-", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write("\n".join(updated) + "\n")
            try:
                os.replace(temporary, SETTINGS_ENV_PATH)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            raise HTTPException(status_code=500, detail="Could not save local AI settings") from None

        settings.AI_PROVIDER = payload.provider
        settings.AI_MODEL = model
        for name, value in key_values.items():
            setattr(settings, name, value)
        if payload.google_cloud_project is not None:
            settings.GOOGLE_CLOUD_PROJECT = project
        if payload.google_cloud_location is not None:
            settings.GOOGLE_CLOUD_LOCATION = location
    return _view()
