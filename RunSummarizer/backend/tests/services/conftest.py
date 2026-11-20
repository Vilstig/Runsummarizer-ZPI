import pytest

from tests.helpers import configure_strava, stub_classifier
from tests.services.fakes import FakeDatabase, FakeStrava


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def strava_app(monkeypatch):
    configure_strava(monkeypatch, client_id="client-id", client_secret="client-secret")


@pytest.fixture(autouse=True)
def classifier(monkeypatch):
    stub_classifier(monkeypatch)


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def strava() -> FakeStrava:
    return FakeStrava()
