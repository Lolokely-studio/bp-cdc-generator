import json

import pytest
from pydantic import BaseModel

from app.llm.fake import FAKE_PROVIDER, FakeTransport, FakeUnsupportedType
from app.llm.providers import PROVIDERS
from app.llm.types import Message

PROVIDER = PROVIDERS["groq"]
MODEL = "groq/compound"


class Assumption(BaseModel):
    label: str
    amount: float


class Analysis(BaseModel):
    title: str
    confidence: float
    accepted: bool
    steps: list[str]
    assumption: Assumption


def _messages(text: str = "Une plateforme de coaching à domicile."):
    return [Message("system", "Tu rédiges un cahier des charges."), Message("user", text)]


async def test_free_text_answer_is_not_empty():
    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages())
    assert len(completion.text) > 50
    assert completion.provider == FAKE_PROVIDER
    assert completion.model == MODEL
    assert completion.tokens > 0
    assert completion.parsed is None


async def test_the_same_question_always_gets_the_same_answer():
    first = await FakeTransport().chat(PROVIDER, MODEL, _messages())
    second = await FakeTransport().chat(PROVIDER, MODEL, _messages())
    assert first.text == second.text


async def test_a_different_question_gets_a_different_answer():
    first = await FakeTransport().chat(PROVIDER, MODEL, _messages("Une place de marché."))
    second = await FakeTransport().chat(PROVIDER, MODEL, _messages("Un logiciel de paie."))
    assert first.text != second.text


async def test_the_model_name_changes_the_answer():
    first = await FakeTransport().chat(PROVIDER, "groq/compound", _messages())
    second = await FakeTransport().chat(PROVIDER, "qwen/qwen3.8-27b", _messages())
    assert first.text != second.text


async def test_a_schema_answer_validates():
    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Analysis)
    assert isinstance(completion.parsed, Analysis)
    assert isinstance(completion.parsed.assumption, Assumption)
    assert len(completion.parsed.steps) >= 1
    # Le texte reste la réponse brute : le graphe pourra le tracer tel quel.
    assert json.loads(completion.text)["title"] == completion.parsed.title


async def test_a_schema_answer_is_deterministic_too():
    first = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Analysis)
    second = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Analysis)
    assert first.parsed == second.parsed


async def test_optional_and_literal_fields_are_filled():
    from typing import Literal

    class WithOptions(BaseModel):
        profile: Literal["banque", "investisseur"]
        comment: str | None

    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=WithOptions)
    assert completion.parsed.profile in ("banque", "investisseur")
    assert completion.parsed.comment is not None


async def test_an_unsupported_field_type_is_announced_loudly():
    class Unsupported(BaseModel):
        when: complex

    with pytest.raises(FakeUnsupportedType) as error:
        await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Unsupported)
    assert "when" in str(error.value)


async def test_a_bounded_integer_stays_within_its_bounds():
    # Sans cela, une note sur dix sortirait à 43 000 et la ValidationError
    # remonterait brute à travers la passerelle.
    from pydantic import Field

    class Note(BaseModel):
        score: int = Field(ge=0, le=10)

    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Note)
    assert 0 <= completion.parsed.score <= 10


async def test_a_bounded_float_stays_within_its_bounds():
    from pydantic import Field

    class Confiance(BaseModel):
        value: float = Field(ge=0, le=1)

    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Confiance)
    assert 0 <= completion.parsed.value <= 1


def _prompt_offering(*fact_ids: str) -> list[Message]:
    lines = "\n".join(f"- {fact_id} (Libellé quelconque) : « Une question ? »"
                      for fact_id in fact_ids)
    return [Message("system", "Tu poses des questions."), Message("user", lines)]


async def test_a_field_named_fact_id_gets_an_identifier_from_the_prompt():
    class ProposedQuestion(BaseModel):
        fact_id: str
        question: str

    class ProposedQuestions(BaseModel):
        questions: list[ProposedQuestion]

    offered = ("prix_moyen_unite", "volume_ventes_an1")
    completion = await FakeTransport().chat(
        PROVIDER, MODEL, _prompt_offering(*offered), schema=ProposedQuestions
    )
    assert all(q.fact_id in offered for q in completion.parsed.questions)


async def test_a_field_merely_named_like_fact_id_is_left_alone():
    # `fact_identifier` ressemble à `fact_id` mais n'en est pas un : il doit
    # recevoir le remplissage générique, jamais un identifiant du catalogue.
    class WithLookalikeField(BaseModel):
        fact_identifier: str

    offered = ("prix_moyen_unite", "volume_ventes_an1")
    completion = await FakeTransport().chat(
        PROVIDER, MODEL, _prompt_offering(*offered), schema=WithLookalikeField
    )
    assert completion.parsed.fact_identifier not in offered


async def test_fact_id_falls_back_to_filler_without_offered_identifiers():
    class ProposedQuestion(BaseModel):
        fact_id: str

    completion = await FakeTransport().chat(
        PROVIDER, MODEL, _messages(), schema=ProposedQuestion
    )
    # Aucun identifiant offert dans le prompt : le remplissage générique
    # s'applique, comme pour n'importe quel autre champ `str`.
    assert completion.parsed.fact_id not in (
        "prix_moyen_unite", "volume_ventes_an1"
    )


async def test_a_question_list_follows_the_number_of_facts_offered():
    """Sans cela, un lot de six revenait avec deux questions et la règle du
    lot n'avait aucun effet."""
    from app.agent.prompts import ProposedQuestions, questions_prompt
    from app.agent.templates import load_catalogue

    catalogue = load_catalogue()
    section = catalogue.section("bp.besoin_financement")
    demandes = ["emprunt_montant", "emprunt_duree", "aides_subventions"]
    messages = questions_prompt(section, demandes, catalogue)

    completion = await FakeTransport().chat(PROVIDER, MODEL, messages,
                                            schema=ProposedQuestions)
    assert len(completion.parsed.questions) == len(demandes)
    assert {q.fact_id for q in completion.parsed.questions} <= set(demandes)


async def test_another_list_still_gets_two_items():
    # La règle ne vaut que pour les questions : ailleurs, deux suffit.
    from app.agent.prompts import Critique

    completion = await FakeTransport().chat(PROVIDER, MODEL, _messages(), schema=Critique)
    assert len(completion.parsed.problems) == 2


async def test_the_stream_rebuilds_the_same_text():
    transport = FakeTransport()
    chunks = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert len(chunks) > 1
    assert all(chunks)
    rebuilt = "".join(chunks)
    again = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert "".join(again) == rebuilt
