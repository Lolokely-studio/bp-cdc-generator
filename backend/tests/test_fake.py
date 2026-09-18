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


async def test_the_stream_rebuilds_the_same_text():
    transport = FakeTransport()
    chunks = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert len(chunks) > 1
    assert all(chunks)
    rebuilt = "".join(chunks)
    again = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert "".join(again) == rebuilt
