import pytest
from esquisse.rate_limit import SlidingWindowCounter


def test_allows_up_to_limit():
    counter = SlidingWindowCounter(maximum=3, window_seconds=900)
    assert [counter.allow("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_keys_are_independent():
    counter = SlidingWindowCounter(maximum=1, window_seconds=900)
    assert counter.allow("1.2.3.4") is True
    assert counter.allow("5.6.7.8") is True
    assert counter.allow("1.2.3.4") is False


def test_window_slides():
    clock_value = [1000.0]
    counter = SlidingWindowCounter(maximum=1, window_seconds=10, clock=lambda: clock_value[0])
    assert counter.allow("ip") is True
    assert counter.allow("ip") is False
    clock_value[0] += 11
    assert counter.allow("ip") is True


async def test_login_is_rate_limited(client, migrated_db):
    for _ in range(10):
        await client.post("/auth/login", json={"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"})
    response = await client.post(
        "/auth/login", json={"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"}
    )
    assert response.status_code == 429
