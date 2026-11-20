import pytest

from tests.helpers import reset_rate_limit_buckets


@pytest.fixture(autouse=True)
def fresh_rate_limit_buckets(monkeypatch):
    """Start each test with full rate-limit buckets: requests share one client IP."""
    reset_rate_limit_buckets(monkeypatch)
