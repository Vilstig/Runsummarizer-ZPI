import time

import pytest

from app.main import app
from app.ratelimiter import (
    RateLimiterStore,
    TokenBucket,
    _auth_store,
    _public_store,
    get_client_ip,
    resolve_rate_limit_key,
)
from tests.helpers import make_request

ACTIVITIES = "/api/v1/activities"


class TestTokenBucket:
    def test_allows_requests_up_to_burst_capacity(self):
        bucket = TokenBucket(max_tokens=3, refill_rate=1, interval=60)

        assert bucket.allow_request() is True
        assert bucket.allow_request() is True
        assert bucket.allow_request() is True
        assert bucket.allow_request() is False

    def test_refills_tokens_after_interval(self):
        bucket = TokenBucket(max_tokens=1, refill_rate=1, interval=0.05)
        assert bucket.allow_request() is True
        assert bucket.allow_request() is False

        time.sleep(0.06)

        assert bucket.allow_request() is True


class TestResolveRateLimitKey:
    def test_uses_auth_store_for_valid_jwt(self, fake_clerk):
        fake_clerk({"test-token": "user-123"})
        request = make_request(headers=[(b"authorization", b"Bearer test-token")])

        store, key = resolve_rate_limit_key(request)

        assert store is _auth_store
        assert key == "user:user-123"

    def test_uses_public_store_for_missing_token(self):
        request = make_request(client_host="10.0.0.5")

        store, key = resolve_rate_limit_key(request)

        assert store is _public_store
        assert key == "ip:10.0.0.5"

    def test_uses_public_store_for_invalid_jwt(self, fake_clerk):
        fake_clerk()
        request = make_request(
            headers=[(b"authorization", b"Bearer not-a-valid-token")],
            client_host="10.0.0.6",
        )

        store, key = resolve_rate_limit_key(request)

        assert store is _public_store
        assert key == "ip:10.0.0.6"


class TestRateLimiterStore:
    def test_returns_the_same_bucket_for_a_key(self):
        store = RateLimiterStore(max_tokens=1, refill_rate=1, interval=60)

        assert store.get_bucket("a") is store.get_bucket("a")

    def test_drops_the_least_recently_used_bucket_past_max_buckets(self):
        store = RateLimiterStore(max_tokens=1, refill_rate=1, interval=60, max_buckets=2)
        first = store.get_bucket("a")
        store.get_bucket("b")
        store.get_bucket("a")  # "b" is now least recently used

        store.get_bucket("c")

        assert len(store) == 2
        assert store.get_bucket("a") is first


def _forwarded(value: bytes, client_host: str = "10.0.0.1"):
    return make_request(headers=[(b"x-forwarded-for", value)], client_host=client_host)


class TestGetClientIp:
    @pytest.fixture(autouse=True)
    def trust_proxy_headers(self, monkeypatch):
        monkeypatch.setattr("app.ratelimiter.TRUST_PROXY_HEADERS", True)

    def test_uses_the_address_the_proxy_appended(self):
        request = _forwarded(b"1.1.1.1, 2.2.2.2, 203.0.113.7")

        assert get_client_ip(request, trusted_hops=1) == "203.0.113.7"

    def test_ignores_addresses_the_client_sent(self):
        spoofed = [_forwarded(f"9.9.9.{n}, 203.0.113.7".encode()) for n in range(3)]

        assert {get_client_ip(request, trusted_hops=1) for request in spoofed} == {"203.0.113.7"}

    def test_skips_one_entry_per_extra_trusted_hop(self):
        request = _forwarded(b"9.9.9.9, 203.0.113.7, 198.51.100.1")

        assert get_client_ip(request, trusted_hops=2) == "203.0.113.7"

    def test_falls_back_to_the_peer_when_the_header_is_too_short(self):
        request = _forwarded(b"203.0.113.7", client_host="10.0.0.9")

        assert get_client_ip(request, trusted_hops=2) == "10.0.0.9"

    def test_ignores_the_header_unless_trusted(self, monkeypatch):
        monkeypatch.setattr("app.ratelimiter.TRUST_PROXY_HEADERS", False)
        request = _forwarded(b"203.0.113.7", client_host="10.0.0.9")

        assert get_client_ip(request) == "10.0.0.9"


@pytest.fixture
def tight_public_store(monkeypatch):
    store = RateLimiterStore(max_tokens=2, refill_rate=1, interval=60)
    monkeypatch.setattr("app.ratelimiter._public_store", store)
    return store


@pytest.fixture
def tight_auth_store(monkeypatch):
    store = RateLimiterStore(max_tokens=2, refill_rate=1, interval=60)
    monkeypatch.setattr("app.ratelimiter._auth_store", store)
    return store


class TestRateLimitMiddleware:
    def test_public_route_returns_429_after_limit(self, tight_public_store):
        from fastapi.testclient import TestClient

        client = TestClient(app)

        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 200
        response = client.get("/")
        assert response.status_code == 429
        assert response.json()["detail"] == "Rate limit exceeded"
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert "Retry-After" in response.headers

    def test_a_rejected_request_logs_a_warning_with_the_client_key_and_limit(
        self, tight_public_store, caplog
    ):
        from fastapi.testclient import TestClient

        caplog.set_level("WARNING", logger="app.ratelimiter")
        client = TestClient(app)

        client.get("/")
        client.get("/")
        client.get("/")

        assert "ip:testclient" in caplog.text
        assert str(tight_public_store.max_tokens) in caplog.text

    def test_authenticated_requests_use_separate_auth_bucket(
        self,
        fake_clerk,
        tight_public_store,
        tight_auth_store,
    ):
        from fastapi.testclient import TestClient

        from app.api.deps import get_activity_service
        from tests.helpers import EmptyActivityService

        fake_clerk({"test-token": "user-456"})
        headers = {"Authorization": "Bearer test-token"}
        app.dependency_overrides[get_activity_service] = lambda: EmptyActivityService()
        try:
            client = TestClient(app)

            # Exhaust the public bucket without a session token.
            for _ in range(2):
                assert client.get("/").status_code == 200
            assert client.get("/").status_code == 429

            # Auth bucket is separate; authenticated requests are not blocked.
            response = client.get(ACTIVITIES, headers=headers)
            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(get_activity_service, None)

    def test_authenticated_activities_use_auth_bucket(
        self,
        fake_clerk,
        tight_auth_store,
    ):
        from fastapi.testclient import TestClient

        from app.api.deps import get_activity_service
        from tests.helpers import EmptyActivityService

        fake_clerk({"test-token": "user-789"})
        headers = {"Authorization": "Bearer test-token"}
        app.dependency_overrides[get_activity_service] = lambda: EmptyActivityService()
        try:
            client = TestClient(app)

            for _ in range(2):
                response = client.get(ACTIVITIES, headers=headers)
                assert response.status_code == 200

            response = client.get(ACTIVITIES, headers=headers)
            assert response.status_code == 429
        finally:
            app.dependency_overrides.pop(get_activity_service, None)

    def test_excluded_webhook_path_bypasses_limit(self, tight_public_store):
        from fastapi.testclient import TestClient

        client = TestClient(app)

        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 429

        response = client.get("/api/webhooks/strava/test-token")
        assert response.status_code != 429
