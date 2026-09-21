import asyncio

import pytest

from app.runs.events import (
    LAGGED,
    SUBSCRIBER_QUEUE_SIZE,
    RunEvent,
    publish,
    subscribe,
)


async def _drain(iterator, count):
    """Les `count` premiers événements, avec un délai : un test qui attend
    indéfiniment sur une file vide ne dit pas ce qui ne va pas."""
    collected = []
    for _ in range(count):
        collected.append(await asyncio.wait_for(anext(iterator), timeout=1))
    return collected


async def test_publishing_without_a_subscriber_does_nothing_and_does_not_block():
    # Le cas normal : le run tourne, aucun navigateur n'est connecté.
    publish("projet-sans-public", RunEvent("progress", {"cursor": 1}))


async def test_a_subscriber_receives_what_is_published_after_it_arrives():
    async with subscribe("projet-a") as events:
        publish("projet-a", RunEvent("token", {"text": "Bonjour"}))
        publish("projet-a", RunEvent("token", {"text": " monde"}))
        received = await _drain(events, 2)
    assert [e.name for e in received] == ["token", "token"]
    assert "".join(e.data["text"] for e in received) == "Bonjour monde"


async def test_a_late_subscriber_misses_what_came_before():
    # Voulu : le bus n'a pas d'historique. Le front qui se reconnecte
    # rappelle `/state`, qui lit le point de reprise.
    publish("projet-b", RunEvent("token", {"text": "perdu"}))
    async with subscribe("projet-b") as events:
        publish("projet-b", RunEvent("token", {"text": "reçu"}))
        received = await _drain(events, 1)
    assert received[0].data["text"] == "reçu"


async def test_two_subscribers_both_receive_everything():
    async with subscribe("projet-c") as premier:
        async with subscribe("projet-c") as second:
            publish("projet-c", RunEvent("score", {"score": 8}))
            assert (await _drain(premier, 1))[0].data["score"] == 8
            assert (await _drain(second, 1))[0].data["score"] == 8


async def test_a_subscriber_of_another_project_receives_nothing():
    async with subscribe("projet-d") as events:
        publish("projet-e", RunEvent("token", {"text": "pas pour toi"}))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(events), timeout=0.05)


async def test_a_subscriber_that_falls_behind_is_dropped_with_an_error():
    """Le débordement ne jette pas des événements en silence : il coupe
    l'abonné en lui disant de se reconnecter. Un texte amputé sans avertir
    serait pire qu'une coupure franche."""
    async with subscribe("projet-f") as events:
        for index in range(SUBSCRIBER_QUEUE_SIZE + 10):
            publish("projet-f", RunEvent("token", {"text": str(index)}))
        received = []
        async for event in events:
            received.append(event)
    assert received[-1].name == "error"
    assert received[-1].data == LAGGED.data
    assert len(received) == SUBSCRIBER_QUEUE_SIZE


async def test_the_channel_disappears_when_its_last_subscriber_leaves():
    from app.runs.events import _channels

    async with subscribe("projet-g"):
        assert "projet-g" in _channels
    assert "projet-g" not in _channels, (
        "un canal survivant à ses abonnés est une fuite : un run par projet, "
        "sur la durée de vie du processus"
    )
