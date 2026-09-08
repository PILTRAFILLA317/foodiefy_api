import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.acquisition.jobs import minimal_env
from src.config import Settings
from src.fastapi_app import create_app


@pytest.mark.parametrize("name", ["ENABLE_MOCKS", "BYPASS_AUTH", "ALLOW_INSECURE_HTTP", "ENABLE_LEGACY_IMPORT", "IMPORT_ALLOW_LOCAL_SOCIAL"])
def test_production_rejects_unsafe_flags(name):
    with pytest.raises(ValidationError):
        Settings(APP_ENV="production", **{name: True})


def test_https_configuration_and_no_secret_in_errors():
    with pytest.raises(ValidationError) as error:
        Settings(APP_ENV="staging", SUPABASE_URL="http://private.invalid", OPENAI_API_KEY="private-test-sentinel")
    assert "private-test-sentinel" not in str(error.value)


def test_liveness_offline_and_readiness_db_failure(monkeypatch):
    app = create_app(Settings())
    monkeypatch.setattr(app.state.jwt_verifier, "ready", lambda: True)
    def unavailable():
        raise OSError("private-db-sentinel")
    monkeypatch.setattr(app.state.import_store, "ready", unavailable)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "private-db-sentinel" not in response.text


def test_safe_logs_correlation_and_private_metrics(caplog, monkeypatch):
    app = create_app(Settings(OPS_TOKEN="test-ops-token"))
    caplog.set_level(logging.INFO, logger="foodiefy.http")
    monkeypatch.setattr(app.state.import_store, "metrics", lambda: {"queued": 2, "live_workers": 1})
    with TestClient(app) as client:
        response = client.get("/health/live?secret=private-sentinel", headers={"Authorization": "Bearer private-sentinel", "X-Request-ID": "private-sentinel"})
        UUID(response.headers["X-Request-ID"])
        assert client.get("/ops/metrics").status_code == 404
        assert client.get("/ops/metrics", headers={"X-Ops-Token":"test-ops-token"}).json()["queued"] == 2
    records = [r.message for r in caplog.records if r.name == "foodiefy.http"]
    assert records and all("private-sentinel" not in r and "test-ops-token" not in r for r in records)
    assert json.loads(records[0])["route"] == "/health/live"


def test_downloader_never_inherits_provider_or_db_secrets(tmp_path, monkeypatch):
    for key in ["OPENAI_API_KEY", "GEMINI_API_KEY", "IMPORT_DATABASE_URL", "OPS_TOKEN", "SUPABASE_JWT_SECRET"]:
        monkeypatch.setenv(key,"secret-test-sentinel")
    env = minimal_env(tmp_path)
    assert set(env) == {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONPATH"}
    assert "secret-test-sentinel" not in str(env)
