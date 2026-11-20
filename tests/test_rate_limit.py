"""M7: per-IP and daily rate limits on POST /api/chat, run on a fake clock.

No test calls a real model: the model client is replaced by a canned fake.
``backend.rate_limit`` is imported inside fixtures so that, while the feature is
missing, each test fails on its own instead of the whole module failing to collect.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.model_client import ModelResult, get_model_client

FORM_URL = "https://cadre.ai/contact"
EMAIL = "hello@gocadre.ai"

# A real UTC instant, midday, so the daily reset only matters when a test wants it.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC).timestamp()


def utc(*args: int) -> float:
    return datetime(*args, tzinfo=UTC).timestamp()


class FakeClock:
    """A controllable ``() -> float`` of UTC epoch seconds."""

    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeModel:
    """A ModelClient stand-in that always returns a valid smalltalk Reply."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls = 0

    async def complete(
        self, system_prompt: str, history: list[dict], message: str
    ) -> ModelResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return ModelResult(
            outcome="smalltalk",
            answer="Hello!",
            citations=[],
            served_model="fake/model",
            tokens_in=10,
            tokens_out=5,
        )


@pytest.fixture
def clock(monkeypatch) -> Iterator[FakeClock]:
    """Fresh limiter state, a fake clock, a fake model, and default limits."""
    from backend.rate_limit import get_clock, get_limiter

    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("DAILY_REQUEST_CAP", raising=False)
    app.dependency_overrides.clear()
    get_limiter.cache_clear()
    fake_clock = FakeClock(T0)
    app.dependency_overrides[get_clock] = lambda: fake_clock
    app.dependency_overrides[get_model_client] = lambda: FakeModel()
    yield fake_clock
    app.dependency_overrides.clear()
    get_limiter.cache_clear()


@pytest.fixture
def client(clock) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def set_limits(monkeypatch, per_minute: int = 1000, daily: int = 100000) -> None:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", str(per_minute))
    monkeypatch.setenv("DAILY_REQUEST_CAP", str(daily))


def chat(client: TestClient, ip: str | None = None, **overrides) -> httpx.Response:
    """POST a valid chat request. ``ip`` becomes the X-Forwarded-For header."""
    payload = {"message": "Hello there"} | overrides
    headers = {"X-Forwarded-For": ip} if ip is not None else {}
    return client.post("/api/chat", json=payload, headers=headers)


def assert_limited(response: httpx.Response, code: str) -> int:
    """Assert a 429 error envelope with this code; return the Retry-After seconds."""
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error", "message", "contact"}
    assert body["error"] == code
    assert isinstance(body["message"], str)
    assert body["message"].strip() != ""
    assert body["contact"]["form_url"] == FORM_URL
    assert body["contact"]["email"] == EMAIL
    assert set(body["contact"]) == {"text", "form_url", "email"}
    retry_after = response.headers["retry-after"]
    assert retry_after.isdigit()  # a decimal integer string, no sign or fraction
    assert int(retry_after) >= 1
    return int(retry_after)


# --- per-IP limit: the headline behavior ---


def test_eleventh_request_in_a_minute_is_rate_limited_with_retry_after(client):
    for _ in range(10):
        assert chat(client, ip="198.51.100.1").status_code == 200

    response = chat(client, ip="198.51.100.1")

    assert_limited(response, "rate_limited")


def test_rate_limit_per_minute_is_read_from_the_environment(client, monkeypatch):
    set_limits(monkeypatch, per_minute=3)

    for _ in range(3):
        assert chat(client, ip="198.51.100.1").status_code == 200

    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")


def test_rate_limit_per_minute_is_re_read_on_every_request(client, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "5")

    assert chat(client, ip="198.51.100.1").status_code == 200


def test_rate_limited_message_is_distinct_from_daily_limit_message(client, monkeypatch):
    set_limits(monkeypatch, per_minute=1, daily=2)
    assert chat(client, ip="198.51.100.1").status_code == 200
    rate_response = chat(client, ip="198.51.100.1")
    assert_limited(rate_response, "rate_limited")
    assert chat(client, ip="198.51.100.2").status_code == 200
    daily_response = chat(client, ip="198.51.100.3")
    assert_limited(daily_response, "daily_limit")

    assert rate_response.json()["message"] != daily_response.json()["message"]


def test_rate_limited_message_does_not_leak_the_client_ip(client, monkeypatch):
    set_limits(monkeypatch, per_minute=1)
    chat(client, ip="198.51.100.77")

    body = chat(client, ip="198.51.100.77").json()

    assert "198.51.100.77" not in body["message"]


# --- Retry-After values ---


def test_retry_after_is_seconds_until_the_oldest_request_leaves_the_window(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=3)
    for _ in range(3):
        assert chat(client, ip="198.51.100.1").status_code == 200
        clock.advance(10)
    # Requests were at T0, T0+10, T0+20; now T0+30. The oldest leaves at T0+60.

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert retry_after == 30


def test_retry_after_rounds_fractional_seconds_up(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=1)
    chat(client, ip="198.51.100.1")
    clock.advance(30.5)

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert retry_after == 30  # ceil(29.5)


def test_retry_after_is_at_least_one_second(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=1)
    chat(client, ip="198.51.100.1")
    clock.advance(59.8)

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert retry_after == 1  # ceil(0.2)


def test_retry_after_for_a_full_window_is_sixty(client, monkeypatch):
    set_limits(monkeypatch, per_minute=1)
    chat(client, ip="198.51.100.1")

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert retry_after == 60


# --- rolling window ---


def test_request_is_still_limited_just_before_the_window_rolls_over(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        chat(client, ip="198.51.100.1")
    clock.advance(59.9)

    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")


def test_request_exactly_sixty_seconds_later_no_longer_counts(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        chat(client, ip="198.51.100.1")
    clock.advance(60.0)

    assert chat(client, ip="198.51.100.1").status_code == 200


def test_window_is_rolling_not_a_fixed_minute(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    assert chat(client, ip="198.51.100.1").status_code == 200  # T0
    clock.advance(30)
    assert chat(client, ip="198.51.100.1").status_code == 200  # T0+30
    clock.advance(30)  # T0+60: only the first request has left the window

    assert chat(client, ip="198.51.100.1").status_code == 200  # fills the window again
    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert retry_after == 30  # the T0+30 request leaves at T0+90


def test_rate_limited_requests_do_not_extend_the_window(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        chat(client, ip="198.51.100.1")  # both at T0
    for _ in range(5):
        clock.advance(10)
        assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")
    clock.advance(10)  # T0+60

    assert chat(client, ip="198.51.100.1").status_code == 200


# --- client IP: distinct IPs, spoofing, fallback ---


def test_distinct_ips_have_independent_limits(client, monkeypatch):
    set_limits(monkeypatch, per_minute=3)
    for _ in range(3):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    assert chat(client, ip="198.51.100.2").status_code == 200


def test_spoofed_left_most_forwarded_for_entry_does_not_evade_the_limit(
    client, monkeypatch
):
    set_limits(monkeypatch, per_minute=3)
    for i in range(3):
        spoofed = f"10.0.0.{i}, 203.0.113.9"
        assert chat(client, ip=spoofed).status_code == 200

    response = chat(client, ip="10.0.0.99, 203.0.113.9")

    assert_limited(response, "rate_limited")


def test_client_ip_is_the_right_most_entry_of_a_long_chain(client, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    for i in range(2):
        assert chat(client, ip=f"1.1.1.{i}, 2.2.2.{i}, 203.0.113.9").status_code == 200

    assert_limited(chat(client, ip="3.3.3.3, 4.4.4.4, 203.0.113.9"), "rate_limited")


def test_entries_with_different_right_most_values_are_different_clients(
    client, monkeypatch
):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        assert chat(client, ip="10.0.0.1, 203.0.113.9").status_code == 200

    # Same left-most entry, different right-most entry: a different client.
    assert chat(client, ip="10.0.0.1, 203.0.113.10").status_code == 200


def test_whitespace_around_forwarded_for_entries_is_ignored(client, monkeypatch):
    set_limits(monkeypatch, per_minute=3)
    assert chat(client, ip="203.0.113.9").status_code == 200
    assert chat(client, ip="1.1.1.1,203.0.113.9").status_code == 200
    assert chat(client, ip="2.2.2.2 ,   203.0.113.9  ").status_code == 200

    assert_limited(chat(client, ip="203.0.113.9"), "rate_limited")


def test_requests_without_forwarded_for_share_the_socket_peer_bucket(
    client, monkeypatch
):
    set_limits(monkeypatch, per_minute=3)
    for _ in range(3):
        assert chat(client).status_code == 200

    assert_limited(chat(client), "rate_limited")


def test_socket_peer_bucket_is_separate_from_forwarded_for_clients(client, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        assert chat(client).status_code == 200
    assert_limited(chat(client), "rate_limited")

    assert chat(client, ip="198.51.100.1").status_code == 200


# --- global daily cap ---


def test_daily_cap_rejects_requests_over_the_cap_with_retry_after(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=100, daily=3)
    clock.now = utc(2026, 3, 1, 23, 59, 30)
    for _ in range(3):
        assert chat(client, ip="198.51.100.1").status_code == 200

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    assert retry_after == 30  # until 00:00 UTC


def test_daily_cap_is_global_across_ips(client, monkeypatch):
    set_limits(monkeypatch, per_minute=100, daily=3)
    for i in range(3):
        assert chat(client, ip=f"198.51.100.{i}").status_code == 200

    assert_limited(chat(client, ip="198.51.100.200"), "daily_limit")


def test_daily_cap_is_read_from_the_environment_on_every_request(client, monkeypatch):
    set_limits(monkeypatch, per_minute=100, daily=2)
    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    monkeypatch.setenv("DAILY_REQUEST_CAP", "5")

    assert chat(client, ip="198.51.100.1").status_code == 200


def test_daily_retry_after_rounds_fractional_seconds_up(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=100, daily=1)
    clock.now = utc(2026, 3, 1, 23, 59, 30) + 0.5
    chat(client, ip="198.51.100.1")

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    assert retry_after == 30  # ceil(29.5)


def test_daily_retry_after_early_in_the_day_counts_to_the_next_midnight(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=100, daily=1)
    clock.now = utc(2026, 3, 1, 0, 0, 0)  # just after a reset: 24h to go
    chat(client, ip="198.51.100.1")

    retry_after = assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    assert retry_after == 86400


def test_daily_cap_resets_at_utc_midnight(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=100, daily=2)
    clock.now = utc(2026, 3, 1, 23, 59, 50)
    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    clock.now = utc(2026, 3, 2, 0, 0, 0)

    assert chat(client, ip="198.51.100.1").status_code == 200
    assert chat(client, ip="198.51.100.2").status_code == 200
    assert_limited(chat(client, ip="198.51.100.3"), "daily_limit")


def test_daily_cap_does_not_reset_one_second_before_midnight(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=100, daily=1)
    clock.now = utc(2026, 3, 1, 23, 59, 0)
    chat(client, ip="198.51.100.1")
    clock.now = utc(2026, 3, 1, 23, 59, 59)

    assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")


def test_daily_cap_counts_per_utc_day_not_per_rolling_24_hours(
    client, clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=100, daily=1)
    clock.now = utc(2026, 3, 1, 23, 0, 0)
    assert chat(client, ip="198.51.100.1").status_code == 200

    clock.now = utc(2026, 3, 2, 0, 30, 0)  # only 90 minutes later, new UTC day

    assert chat(client, ip="198.51.100.1").status_code == 200


# --- how the two limits interact with quota ---


def test_rate_limited_requests_do_not_consume_the_daily_cap(client, monkeypatch):
    set_limits(monkeypatch, per_minute=2, daily=3)
    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    for _ in range(5):
        assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    # Only 2 of the 3 daily requests are used, so another IP still gets one.
    assert chat(client, ip="198.51.100.2").status_code == 200
    assert_limited(chat(client, ip="198.51.100.3"), "daily_limit")


def test_daily_limited_requests_do_not_consume_per_ip_quota(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=3, daily=2)
    clock.now = utc(2026, 3, 1, 23, 59, 50)
    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    for _ in range(5):
        assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")

    clock.now = utc(2026, 3, 2, 0, 0, 5)  # new day, still within 60s of the first two

    # The window holds only the 2 accepted requests, so this is the 3rd of 3.
    assert chat(client, ip="198.51.100.1").status_code == 200


# --- validation runs before limits count ---

INVALID_PAYLOADS = [
    pytest.param({"message": ""}, id="empty-message"),
    pytest.param({"message": "   "}, id="blank-message"),
    pytest.param({"message": "x" * 501}, id="too-long-message"),
    pytest.param({"message": "hi", "surprise": 1}, id="unknown-field"),
    pytest.param({}, id="missing-message"),
    pytest.param(
        {
            "message": "hi",
            "history": [{"role": "user", "content": "hi"}] * 7,
        },
        id="too-much-history",
    ),
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_invalid_requests_do_not_consume_the_per_ip_limit(client, monkeypatch, payload):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(5):
        response = client.post(
            "/api/chat", json=payload, headers={"X-Forwarded-For": "198.51.100.1"}
        )
        assert response.status_code == 422
        assert response.json()["error"] == "invalid_request"

    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_invalid_requests_do_not_consume_the_daily_cap(client, monkeypatch, payload):
    set_limits(monkeypatch, per_minute=100, daily=2)
    for i in range(5):
        response = client.post(
            "/api/chat", json=payload, headers={"X-Forwarded-For": f"198.51.100.{i}"}
        )
        assert response.status_code == 422

    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "daily_limit")


def test_malformed_json_does_not_consume_quota(client, monkeypatch):
    set_limits(monkeypatch, per_minute=1, daily=1)
    response = client.post(
        "/api/chat",
        content=b"{not json",
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": "198.51.100.1",
        },
    )
    assert response.status_code == 422

    assert chat(client, ip="198.51.100.1").status_code == 200


# --- /api/health is never limited ---


def test_health_is_never_rate_limited(client, monkeypatch):
    set_limits(monkeypatch, per_minute=1)

    for _ in range(25):
        response = client.get(
            "/api/health", headers={"X-Forwarded-For": "198.51.100.1"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_health_still_answers_when_the_ip_and_daily_limits_are_exhausted(
    client, monkeypatch
):
    set_limits(monkeypatch, per_minute=1, daily=1)
    assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.2"), "daily_limit")
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")

    response = client.get("/api/health", headers={"X-Forwarded-For": "198.51.100.1"})

    assert response.status_code == 200


def test_health_requests_do_not_consume_chat_quota(client, monkeypatch):
    set_limits(monkeypatch, per_minute=2, daily=2)
    for _ in range(10):
        client.get("/api/health", headers={"X-Forwarded-For": "198.51.100.1"})

    for _ in range(2):
        assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")


# --- bounded memory ---


def test_stale_ips_are_pruned_so_memory_stays_bounded(client, clock, monkeypatch):
    from backend.rate_limit import get_limiter

    set_limits(monkeypatch, per_minute=3)
    for i in range(50):
        assert chat(client, ip=f"198.51.100.{i}").status_code == 200
    assert get_limiter().tracked_ips() == 50

    clock.advance(61)
    assert chat(client, ip="203.0.113.1").status_code == 200

    assert get_limiter().tracked_ips() == 1


def test_ips_with_requests_still_in_the_window_are_not_pruned(
    client, clock, monkeypatch
):
    from backend.rate_limit import get_limiter

    set_limits(monkeypatch, per_minute=3)
    assert chat(client, ip="198.51.100.1").status_code == 200
    clock.advance(30)
    assert chat(client, ip="198.51.100.2").status_code == 200
    clock.advance(31)  # the first IP is now stale, the second is not

    assert chat(client, ip="198.51.100.3").status_code == 200

    assert get_limiter().tracked_ips() == 2


def test_a_pruned_ip_starts_with_a_fresh_quota(client, clock, monkeypatch):
    set_limits(monkeypatch, per_minute=2)
    for _ in range(2):
        chat(client, ip="198.51.100.1")
    clock.advance(61)
    chat(client, ip="203.0.113.1")  # triggers pruning of the stale IP

    assert chat(client, ip="198.51.100.1").status_code == 200
    assert chat(client, ip="198.51.100.1").status_code == 200
    assert_limited(chat(client, ip="198.51.100.1"), "rate_limited")


# --- concurrency ---


def _concurrent_chats(headers_for) -> list[httpx.Response]:
    """Fire many chat requests at once through the ASGI app, on one event loop."""

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            return await asyncio.gather(
                *(
                    async_client.post(
                        "/api/chat", json={"message": "Hello"}, headers=headers
                    )
                    for headers in headers_for
                )
            )

    return asyncio.run(run())


def test_concurrent_requests_from_one_ip_admit_exactly_the_limit(clock, monkeypatch):
    set_limits(monkeypatch, per_minute=5)
    app.dependency_overrides[get_model_client] = lambda: FakeModel(delay=0.01)

    responses = _concurrent_chats([{"X-Forwarded-For": "198.51.100.1"}] * 40)

    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == 5
    assert statuses.count(429) == 35
    assert all(
        r.json()["error"] == "rate_limited" for r in responses if r.status_code == 429
    )


def test_concurrent_requests_from_many_ips_admit_exactly_the_daily_cap(
    clock, monkeypatch
):
    set_limits(monkeypatch, per_minute=100, daily=7)
    app.dependency_overrides[get_model_client] = lambda: FakeModel(delay=0.01)

    responses = _concurrent_chats(
        [{"X-Forwarded-For": f"198.51.100.{i}"} for i in range(40)]
    )

    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == 7
    assert statuses.count(429) == 33
    assert all(
        r.json()["error"] == "daily_limit" for r in responses if r.status_code == 429
    )
