"""Probe behaviour: liveness never touches dependencies, readiness reports them."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_readiness_cache(monkeypatch):
    """Stop one test's readiness result from being served to the next."""
    monkeypatch.setattr(health, "_cached_checks", None)


async def _ok() -> None:
    return None


async def _boom() -> None:
    raise ConnectionError("postgresql://secret-host:5432 refused the connection")


def _recorder(calls: list) -> Callable:
    """A passing check that records each time it runs."""

    async def check() -> None:
        calls.append(1)

    return check


def test_liveness_is_ok_even_when_dependencies_fail(client, monkeypatch):
    monkeypatch.setitem(health.CHECKS, "postgres", _boom)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_every_check(client, monkeypatch):
    monkeypatch.setitem(health.CHECKS, "postgres", _ok)
    monkeypatch.setitem(health.CHECKS, "secrets", _ok)

    response = client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {check["name"] for check in body["checks"]} == set(health.CHECKS)
    assert all(check["status"] == "ok" for check in body["checks"])


def test_readiness_is_503_when_a_check_fails(client, monkeypatch):
    monkeypatch.setitem(health.CHECKS, "postgres", _boom)
    monkeypatch.setitem(health.CHECKS, "secrets", _ok)

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    postgres = next(c for c in body["checks"] if c["name"] == "postgres")
    assert postgres["status"] == "error"
    assert postgres["error"] == "ConnectionError"


def test_readiness_does_not_leak_failure_details(client, monkeypatch):
    monkeypatch.setitem(health.CHECKS, "postgres", _boom)

    body = client.get("/api/health/ready").text

    assert "secret-host" not in body


def test_readiness_reuses_a_result_within_the_cache_window(client, monkeypatch):
    calls = []
    monkeypatch.setitem(health.CHECKS, "postgres", _recorder(calls))
    monkeypatch.setitem(health.CHECKS, "secrets", _ok)

    for _ in range(5):
        assert client.get("/api/health/ready").status_code == 200

    assert len(calls) == 1


def test_readiness_reruns_checks_once_the_cache_expires(client, monkeypatch):
    calls = []
    monkeypatch.setitem(health.CHECKS, "postgres", _recorder(calls))
    monkeypatch.setitem(health.CHECKS, "secrets", _ok)
    monkeypatch.setattr(health, "CACHE_TTL_S", 0.0)

    client.get("/api/health/ready")
    client.get("/api/health/ready")

    assert len(calls) == 2


def test_readiness_reports_a_check_that_times_out(client, monkeypatch):
    """A hung dependency must fail the probe rather than hang the request."""

    async def hangs() -> None:
        raise TimeoutError

    monkeypatch.setitem(health.CHECKS, "postgres", hangs)
    monkeypatch.setitem(health.CHECKS, "secrets", _ok)

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    postgres = next(c for c in response.json()["checks"] if c["name"] == "postgres")
    assert postgres["error"] == "TimeoutError"
