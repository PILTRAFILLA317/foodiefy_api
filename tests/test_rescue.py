import importlib.util
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.config import Settings
from src.fastapi_app import create_app


def test_factory_and_health_without_external_dependencies():
    with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
        with TestClient(create_app(Settings())) as client:
            assert client.get("/health/live").json() == {"status": "ok"}
            response = client.post("/api/analyze-recipe", json={"url": "https://example.invalid/video"})
            assert response.status_code == 503
            assert response.json() == {"success": False, "error": "legacy_import_disabled"}
    assert "src.legacy_fastapi" not in sys.modules
    assert "whisper" not in sys.modules
    assert "torch" not in sys.modules


def test_disabled_route_does_not_parse_or_download_input():
    with TestClient(create_app(Settings())) as client:
        assert client.post("/api/analyze-recipe", content="broken json").status_code == 503


def test_import_in_clean_process_has_no_keys_or_optional_packages():
    assert importlib.util.find_spec("whisper") is None
    assert importlib.util.find_spec("torch") is None
    script = """
import sys
from src.fastapi_app import create_app
assert create_app()
assert 'src.legacy_fastapi' not in sys.modules
assert 'whisper' not in sys.modules
assert 'torch' not in sys.modules
"""
    env = {key: value for key, value in os.environ.items()
           if key not in {"GEMINI_API_KEY", "ENABLE_LEGACY_IMPORT", "APP_ENV"}}
    subprocess.run([sys.executable, "-c", script], env=env, check=True, capture_output=True)


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
def test_opt_in_without_keys_or_budget_is_controlled(environment):
    if environment != "local":
        with pytest.raises(ValidationError, match="local_only_features_forbidden"):
            Settings(APP_ENV=environment, ENABLE_LEGACY_IMPORT=True)
        return
    settings = Settings(APP_ENV=environment, ENABLE_LEGACY_IMPORT=True)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/analyze-recipe", json={"url": "https://example.invalid"})
        assert response.status_code == 503
        assert response.json()["error"] == "legacy_import_not_configured"


def test_invalid_environment_is_rejected():
    with pytest.raises(ValidationError):
        Settings(APP_ENV="typo")


def test_factories_are_independent():
    assert create_app() is not create_app()
