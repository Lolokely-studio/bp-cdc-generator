import pytest
from app.core.rate_limit import SlidingWindowCounter


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


async def test_rate_limit_ignores_the_caller_supplied_prefix(client, migrated_db):
    """La première entrée de X-Forwarded-For est écrite par l'appelant. Si la
    limite s'y accrochait, il suffirait d'en changer à chaque requête pour ne
    jamais être limité."""
    corps = {"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"}
    for i in range(10):
        await client.post(
            "/auth/login", json=corps,
            headers={"X-Forwarded-For": f"10.0.0.{i}, 9.9.9.9"},
        )
    bloque = await client.post(
        "/auth/login", json=corps,
        headers={"X-Forwarded-For": "10.0.0.99, 9.9.9.9"},
    )
    assert bloque.status_code == 429


async def test_rate_limit_separates_distinct_forwarded_addresses(client, migrated_db):
    """Deux entrées par en-tête, comme pour le test jumeau : une seule entrée
    ne distinguerait pas une implémentation qui retiendrait la première de
    celle qui retient la dernière, puisqu'il n'y en aurait qu'une. Le préfixe
    est constant ici, seule la dernière entrée change : une implémentation qui
    lirait à tort la première verrait toujours la même adresse et bloquerait,
    alors que la bonne implémentation traite ces deux appelants comme
    distincts."""
    corps = {"email": "x@exemple.fr", "mot_de_passe": "motdepasse123"}
    for _ in range(10):
        await client.post(
            "/auth/login", json=corps, headers={"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}
        )
    autre = await client.post(
        "/auth/login", json=corps, headers={"X-Forwarded-For": "9.9.9.9, 2.2.2.2"}
    )
    assert autre.status_code != 429
