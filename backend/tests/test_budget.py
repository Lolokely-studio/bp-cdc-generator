import pytest
import pytest_asyncio

from app.core.db import connection
from app.llm.budget import Pacer, budget_available, pacer_for, record_usage, reset_pacers
from app.llm.providers import PROVIDERS


@pytest_asyncio.fixture(autouse=True)
async def _empty_usage(migrated_db):
    """Les fenêtres se lisent sur une table partagée : sans vidage, l'ordre
    des tests déciderait de leur résultat."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("delete from llm_usage")
    reset_pacers()
    yield


async def _seed(provider: str, *, rows: int, tokens: int = 0, minutes_ago: int = 0):
    async with connection() as conn:
        async with conn.cursor() as cur:
            for _ in range(rows):
                await cur.execute(
                    """
                    insert into llm_usage (fournisseur, modele, route, requetes, tokens, issue, at)
                    values (%s, 'm', 'court', 1, %s, 'ok', now() - make_interval(mins => %s))
                    """,
                    (provider, tokens, minutes_ago),
                )


async def test_budget_allows_when_nothing_was_recorded():
    async with connection() as conn:
        assert await budget_available(conn, PROVIDERS["gemini"], 1_000)


async def test_requests_per_minute_ceiling_refuses():
    await _seed("gemini", rows=15)
    async with connection() as conn:
        assert not await budget_available(conn, PROVIDERS["gemini"], 1_000)


async def test_tokens_per_minute_ceiling_looks_at_the_call_to_come():
    # 240 000 déjà consommés sur 250 000 : un petit appel passe, la section
    # entière ne passe pas. C'est exactement la décision du §5.2.
    await _seed("gemini", rows=1, tokens=240_000)
    async with connection() as conn:
        assert await budget_available(conn, PROVIDERS["gemini"], 5_000)
        assert not await budget_available(conn, PROVIDERS["gemini"], 20_000)


async def test_one_provider_does_not_spend_the_budget_of_another():
    await _seed("gemini", rows=15)
    async with connection() as conn:
        assert await budget_available(conn, PROVIDERS["groq"], 1_000)


async def test_rows_older_than_the_minute_leave_the_window():
    await _seed("gemini", rows=15, minutes_ago=2)
    async with connection() as conn:
        assert await budget_available(conn, PROVIDERS["gemini"], 1_000)


async def test_the_daily_window_still_counts_them():
    # OpenRouter plafonne à 50 requêtes par jour : sorties de la minute,
    # elles pèsent encore.
    await _seed("openrouter", rows=50, minutes_ago=90)
    async with connection() as conn:
        assert not await budget_available(conn, PROVIDERS["openrouter"], 1_000)


async def test_daily_token_ceiling_refuses():
    await _seed("groq", rows=1, tokens=499_000, minutes_ago=120)
    async with connection() as conn:
        assert not await budget_available(conn, PROVIDERS["groq"], 5_000)


async def test_a_provider_without_published_ceiling_always_passes():
    # NVIDIA ne publie pas de plafond de jetons : rien à comparer, on laisse
    # passer plutôt que d'inventer un chiffre.
    await _seed("nvidia", rows=1, tokens=10_000_000)
    async with connection() as conn:
        assert await budget_available(conn, PROVIDERS["nvidia"], 100_000)


async def test_record_usage_writes_one_row():
    async with connection() as conn:
        await record_usage(
            conn, provider="groq", model="groq/compound", route="court",
            project_id=None, tokens=1_234, issue="ok",
        )
        async with conn.cursor() as cur:
            await cur.execute(
                "select fournisseur, modele, route, requetes, tokens, issue from llm_usage"
            )
            rows = await cur.fetchall()
    assert rows == [("groq", "groq/compound", "court", 1, 1_234, "ok")]


async def test_recorded_usage_is_visible_to_the_window():
    async with connection() as conn:
        for _ in range(15):
            await record_usage(
                conn, provider="gemini", model="gemini-3.1-flash-lite", route="redaction",
                project_id=None, tokens=0, issue="ok",
            )
        assert not await budget_available(conn, PROVIDERS["gemini"], 1)


class _Clock:
    """Horloge et sommeil factices : l'attente est vérifiée sans être subie."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_pacer_lets_the_first_call_through():
    clock = _Clock()
    pacer = Pacer(1.0, clock=clock.time, sleep=clock.sleep)
    await pacer.wait()
    assert clock.slept == []


async def test_pacer_delays_a_call_that_comes_too_soon():
    clock = _Clock()
    pacer = Pacer(1.0, clock=clock.time, sleep=clock.sleep)
    await pacer.wait()
    clock.now += 0.25
    await pacer.wait()
    assert clock.slept == [pytest.approx(0.75)]


async def test_pacer_does_not_delay_a_call_that_comes_late():
    clock = _Clock()
    pacer = Pacer(1.0, clock=clock.time, sleep=clock.sleep)
    await pacer.wait()
    clock.now += 3.0
    await pacer.wait()
    assert clock.slept == []


def test_only_mistral_needs_a_pacer():
    assert pacer_for(PROVIDERS["mistral"]) is not None
    assert pacer_for(PROVIDERS["groq"]) is None


def test_the_same_provider_shares_one_pacer():
    # Deux instances laisseraient passer deux requêtes dans la même seconde.
    assert pacer_for(PROVIDERS["mistral"]) is pacer_for(PROVIDERS["mistral"])
