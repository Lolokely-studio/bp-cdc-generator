from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.db import connection
from app.llm import gateway, providers as providers_module
from app.llm.budget import reset_pacers
from app.llm.errors import ModelUnavailable, NoProviderAvailable, ProviderUnavailable
from app.llm.gateway import complete, stream
from app.llm.providers import PROVIDERS
from app.llm.tokens import estimate_tokens
from app.llm.types import Completion, Message, StreamDone, StreamRestart, TextDelta

MESSAGES = [Message("user", "Une plateforme de coaching à domicile.")]


@pytest_asyncio.fixture(autouse=True)
async def _clean(migrated_db):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("delete from llm_usage")
    # L'espacement vit dans le processus : sans remise à zéro, le premier
    # essai Mistral d'un test attendrait la seconde consommée par le test
    # précédent.
    reset_pacers()
    yield


class _Stub:
    """Transport sous contrôle du test : on lui dicte, par couple
    (fournisseur, modèle), ce qu'il rend ou ce qu'il lève."""

    def __init__(self, script: dict, default=None) -> None:
        self.script = script
        self.default = default
        self.calls: list[tuple[str, str]] = []

    async def chat(self, provider, model, messages, *, schema=None):
        self.calls.append((provider.name, model))
        outcome = self.script.get((provider.name, model), self.default)
        if isinstance(outcome, Exception):
            raise outcome
        return Completion(text="réponse", provider=provider.name, model=model, tokens=100)


class _StreamStub:
    """Même principe, en flux : la valeur scriptée est une liste de fragments
    où une exception peut se glisser à n'importe quelle position."""

    def __init__(self, script: dict, default=None) -> None:
        self.script = script
        self.default = default if default is not None else ["texte"]
        self.calls: list[tuple[str, str]] = []

    async def stream_chat(self, provider, model, messages):
        self.calls.append((provider.name, model))
        for item in self.script.get((provider.name, model), self.default):
            if isinstance(item, Exception):
                raise item
            yield item


def _keys_missing_for(name: str) -> SimpleNamespace:
    keys = {provider.key_setting: "cle-de-test" for provider in PROVIDERS.values()}
    keys[PROVIDERS[name].key_setting] = ""
    return SimpleNamespace(**keys)


async def _seed_usage(provider: str, rows: int, tokens: int = 0):
    async with connection() as conn:
        async with conn.cursor() as cur:
            for _ in range(rows):
                await cur.execute(
                    """
                    insert into llm_usage (fournisseur, modele, route, requetes, tokens, issue)
                    values (%s, 'm', 'court', 1, %s, 'ok')
                    """,
                    (provider, tokens),
                )


async def _usage_rows():
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select fournisseur, modele, route, tokens, issue from llm_usage order by id"
            )
            return await cur.fetchall()


async def test_the_first_provider_of_the_route_answers():
    stub = _Stub({})
    result = await complete("court", MESSAGES, transport=stub)
    assert stub.calls == [("groq", "groq/compound")]
    assert result.provider == "groq"


async def test_an_off_schema_answer_tries_the_next_model_of_the_same_provider():
    stub = _Stub({("groq", "groq/compound"): ModelUnavailable("groq/compound", "hors schéma")})
    result = await complete("court", MESSAGES, transport=stub)
    assert stub.calls == [("groq", "groq/compound"), ("groq", "openai/gpt-oss-120b")]
    assert result.model == "openai/gpt-oss-120b"


async def test_a_quota_refusal_abandons_the_remaining_models_of_that_provider():
    # Le quota est du fournisseur, pas du modèle : insister sur ses autres
    # modèles ne ferait qu'ajouter des 429.
    stub = _Stub({("groq", "groq/compound"): ProviderUnavailable("groq", "quota", "429")})
    result = await complete("court", MESSAGES, transport=stub)
    assert stub.calls == [
        ("groq", "groq/compound"),
        ("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    ]
    assert result.provider == "nvidia"


async def test_an_exhausted_route_raises_and_names_every_attempt():
    stub = _Stub({}, default=ProviderUnavailable("x", "erreur", "en panne"))
    with pytest.raises(NoProviderAvailable) as error:
        await complete("grand_contexte", MESSAGES, transport=stub)
    assert error.value.route == "grand_contexte"
    assert len(error.value.attempts) == 2  # un essai par fournisseur, coupé au premier modèle


async def test_a_provider_without_a_key_is_skipped_without_a_call(monkeypatch):
    monkeypatch.setattr(providers_module, "settings", lambda: _keys_missing_for("groq"))
    stub = _Stub({})
    result = await complete("court", MESSAGES, transport=stub)
    assert [name for name, _ in stub.calls] == ["nvidia"]
    assert result.provider == "nvidia"
    assert await _usage_rows() == [("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b",
                                    "court", 100, "ok")]


async def test_an_insufficient_budget_switches_before_any_call():
    await _seed_usage("groq", rows=30)  # plafond : 30 requêtes par minute
    stub = _Stub({})
    result = await complete("court", MESSAGES, transport=stub)
    assert [name for name, _ in stub.calls] == ["nvidia"]
    assert result.provider == "nvidia"


async def test_a_preventive_switch_writes_no_row_for_the_provider_skipped():
    await _seed_usage("groq", rows=30)
    await complete("court", MESSAGES, transport=_Stub({}))
    rows = await _usage_rows()
    assert sum(1 for row in rows if row[0] == "groq") == 30  # les trente semées, pas une de plus


async def test_a_success_writes_one_row_naming_the_model_used():
    await complete("court", MESSAGES, transport=_Stub({}), project_id=None)
    assert await _usage_rows() == [("groq", "groq/compound", "court", 100, "ok")]


async def test_a_failed_attempt_writes_its_issue():
    stub = _Stub({("groq", "groq/compound"): ProviderUnavailable("groq", "quota", "429")})
    await complete("court", MESSAGES, transport=stub)
    rows = await _usage_rows()
    assert rows[0] == ("groq", "groq/compound", "court", 0, "quota")
    assert rows[1][4] == "ok"


async def test_the_stream_yields_its_deltas_then_a_done():
    stub = _StreamStub({("gemini", "gemini-3.1-flash-lite"): ["Le ", "dispositif."]})
    events = [event async for event in stream("redaction", MESSAGES, transport=stub)]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Le ", "dispositif."]
    assert isinstance(events[-1], StreamDone)
    assert events[-1].provider == "gemini"


async def test_a_stream_broken_after_a_delta_restarts_on_the_next_provider():
    stub = _StreamStub({
        ("gemini", "gemini-3.1-flash-lite"): [
            "Le début ", ProviderUnavailable("gemini", "erreur", "flux rompu")
        ],
        ("mistral", "ministral-8b-latest"): ["Tout ", "depuis le début."],
    })
    events = [event async for event in stream("redaction", MESSAGES, transport=stub)]
    restarts = [e for e in events if isinstance(e, StreamRestart)]
    assert len(restarts) == 1
    assert restarts[0].provider == "gemini"
    # Le fournisseur suivant, jamais le modèle suivant : la section repart
    # entière et le consommateur vide ce qu'il a affiché.
    assert [name for name, _ in stub.calls] == ["gemini", "mistral"]
    assert events[-1].provider == "mistral"


async def test_a_stream_that_never_opened_announces_no_restart():
    # Rien n'a été affiché : c'est un essai raté ordinaire, pas une reprise.
    stub = _StreamStub({
        ("gemini", "gemini-3.1-flash-lite"): [ProviderUnavailable("gemini", "quota", "429")],
        ("mistral", "ministral-8b-latest"): ["Une section."],
    })
    events = [event async for event in stream("redaction", MESSAGES, transport=stub)]
    assert not any(isinstance(e, StreamRestart) for e in events)
    assert events[-1].provider == "mistral"


async def test_a_broken_stream_records_the_prompt_and_what_was_emitted():
    stub = _StreamStub({
        ("gemini", "gemini-3.1-flash-lite"): [
            "Un début de section déjà affiché à l'écran.",
            ProviderUnavailable("gemini", "erreur", "flux rompu"),
        ],
        ("mistral", "ministral-8b-latest"): ["Tout depuis le début."],
    })
    [event async for event in stream("redaction", MESSAGES, transport=stub)]
    rows = await _usage_rows()
    assert rows[0][0] == "gemini"
    assert rows[0][4] == "erreur"
    # Strictement plus que le prompt seul : le prompt est parti en entier et le
    # texte reçu avant la rupture s'y ajoute. Un simple `> 0` laisserait passer
    # un compte qui oublierait le prompt.
    assert rows[0][3] > estimate_tokens(MESSAGES)


async def test_an_exhausted_route_in_streaming_raises():
    stub = _StreamStub({}, default=[ProviderUnavailable("x", "erreur", "en panne")])
    with pytest.raises(NoProviderAvailable):
        async for _ in stream("grand_contexte", MESSAGES, transport=stub):
            pass


async def test_fake_mode_records_under_the_fake_provider(monkeypatch):
    # Soixante-dix appels hors ligne ne doivent consommer aucun budget réel.
    monkeypatch.setattr(gateway, "settings", lambda: SimpleNamespace(fake_llm=True))
    result = await complete("court", MESSAGES)
    assert result.provider == "fake"
    rows = await _usage_rows()
    assert rows[0][0] == "fake"
    assert rows[0][2] == "court"


async def test_fake_mode_ignores_an_exhausted_budget(monkeypatch):
    monkeypatch.setattr(gateway, "settings", lambda: SimpleNamespace(fake_llm=True))
    await _seed_usage("groq", rows=30)
    result = await complete("court", MESSAGES)
    assert result.provider == "fake"
