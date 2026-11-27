"""Fail closed on Azure (2026-11-26): on App Service the app refuses to start
without sign-in, and the session cookie is Secure by default. Local runs are
untouched."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.auth import AuthMode, log_security_warnings, startup_refusal
from backend.config import APP_SERVICE_MARKERS, Settings, settings


@pytest.fixture
def local(monkeypatch):
    for name in APP_SERVICE_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "auth_allow_disabled_on_azure", False)


@pytest.fixture(params=APP_SERVICE_MARKERS)
def azure(request, local, monkeypatch):
    """Either marker alone is App Service."""
    monkeypatch.setenv(request.param, "technical-marketing-hub")
    return request.param


# ─────────────────────────────────────────────────────────── refusing to start
@pytest.mark.parametrize("mode", ["disabled", "", "oicd", "DISABLED"])
def test_on_app_service_without_sign_in_the_app_refuses_to_start(azure, monkeypatch, caplog,
                                                                 capsys, mode):
    monkeypatch.setattr(settings, "auth_mode", mode)
    assert "AUTH_MODE" in startup_refusal()
    with caplog.at_level(logging.WARNING, logger="backend.auth"), \
            pytest.raises(RuntimeError, match="Refusing to start"):
        log_security_warnings()
    # The reasons are out before it stops: the warning, then the refusal.
    assert "AUTH IS DISABLED ON APP SERVICE" in caplog.text
    assert "Refusing to start" in caplog.text
    assert "AUTH_ALLOW_DISABLED_ON_AZURE" in capsys.readouterr().out


@pytest.mark.parametrize("mode", [AuthMode.OIDC.value, AuthMode.EASYAUTH.value])
def test_on_app_service_with_sign_in_it_starts(azure, monkeypatch, mode):
    monkeypatch.setattr(settings, "auth_mode", mode)
    assert startup_refusal() is None
    log_security_warnings()


def test_the_escape_hatch_starts_it_and_still_says_so(azure, monkeypatch, caplog):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.setattr(settings, "auth_allow_disabled_on_azure", True)
    assert startup_refusal() is None
    with caplog.at_level(logging.WARNING, logger="backend.auth"):
        log_security_warnings()
    assert "AUTH_ALLOW_DISABLED_ON_AZURE is set" in caplog.text


@pytest.mark.parametrize("mode", ["disabled", "oidc", "easyauth", "anything"])
def test_a_local_run_is_never_refused(local, monkeypatch, mode):
    monkeypatch.setattr(settings, "auth_mode", mode)
    assert startup_refusal() is None
    log_security_warnings()


def test_the_refusal_stops_the_app_starting(azure, monkeypatch):
    """Through the real lifespan: the app does not come up."""
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        with TestClient(app):
            pass


def test_a_local_app_starts_in_disabled_mode(local, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    with TestClient(app) as client:
        assert client.get("/api/version").status_code == 200


def test_either_marker_counts_in_the_warnings_too(local, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "abc123")
    assert any("AUTH IS DISABLED ON APP SERVICE" in w for w in auth.security_warnings())


# ────────────────────────────────────────────────────────── https_only default
def fresh_settings():
    return Settings(_env_file=None)


def test_https_only_defaults_to_true_on_app_service(azure, monkeypatch):
    monkeypatch.delenv("HTTPS_ONLY", raising=False)
    assert fresh_settings().https_only is True


def test_https_only_defaults_to_false_locally(local, monkeypatch):
    monkeypatch.delenv("HTTPS_ONLY", raising=False)
    assert fresh_settings().https_only is False


def test_https_only_can_still_be_set_either_way(azure, monkeypatch):
    monkeypatch.setenv("HTTPS_ONLY", "false")
    assert fresh_settings().https_only is False
    for name in APP_SERVICE_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_ONLY", "true")
    assert fresh_settings().https_only is True
