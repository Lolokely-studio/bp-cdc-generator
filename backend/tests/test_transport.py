import json

import httpx2
import pytest
from pydantic import BaseModel

from app.llm.errors import ModelUnavailable, ProviderUnavailable
from app.llm.providers import PROVIDERS
from app.llm.transport import chat, client_for, stream_chat
from app.llm.types import Message

PROVIDER = PROVIDERS["groq"]
MODEL = "groq/compound"
MESSAGES = [Message("user", "Résume l'idée en une phrase.")]


class Analysis(BaseModel):
    title: str
    confidence: float


def _answer(content: str, usage: dict | None = None) -> dict:
    body = {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _client(handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _replying(status: int, body: dict):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return handler


async def test_chat_returns_the_text_and_the_reported_token_count():
    handler = _replying(200, _answer("Une phrase.", usage={"total_tokens": 42}))
    completion = await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert completion.text == "Une phrase."
    assert completion.tokens == 42
    assert completion.provider == "groq"
    assert completion.model == MODEL


async def test_chat_estimates_the_cost_when_the_provider_reports_none():
    # Plusieurs paliers gratuits omettent `usage`. Sans estimation de repli,
    # la fenêtre de jetons ne verrait jamais passer ces appels.
    handler = _replying(200, _answer("Une phrase un peu plus longue que la précédente."))
    completion = await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert completion.tokens > 0


async def test_chat_parses_a_schema():
    content = json.dumps({"title": "Coaching à domicile", "confidence": 0.8})
    handler = _replying(200, _answer(content))
    completion = await chat(PROVIDER, MODEL, MESSAGES, schema=Analysis, http_client=_client(handler))
    assert isinstance(completion.parsed, Analysis)
    assert completion.parsed.title == "Coaching à domicile"


async def test_chat_accepts_a_fenced_answer():
    # Plusieurs modèles gratuits entourent le JSON d'une clôture Markdown
    # malgré la consigne. Le refuser coûterait un modèle par section.
    content = '```json\n{"title": "Place de marché", "confidence": 0.5}\n```'
    handler = _replying(200, _answer(content))
    completion = await chat(PROVIDER, MODEL, MESSAGES, schema=Analysis, http_client=_client(handler))
    assert completion.parsed.title == "Place de marché"


async def test_an_answer_outside_the_schema_blames_the_model():
    handler = _replying(200, _answer("Je ne suis pas du JSON."))
    with pytest.raises(ModelUnavailable):
        await chat(PROVIDER, MODEL, MESSAGES, schema=Analysis, http_client=_client(handler))


async def test_a_quota_refusal_blames_the_provider():
    handler = _replying(429, {"error": {"message": "rate limit"}})
    with pytest.raises(ProviderUnavailable) as error:
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert error.value.issue == "quota"
    assert error.value.provider == "groq"


async def test_a_missing_model_blames_the_model_not_the_provider():
    # Un modèle gratuit retiré du catalogue répond 404. Basculer de
    # fournisseur pour cela abandonnerait ses autres modèles, encore valides.
    handler = _replying(404, {"error": {"message": "model not found"}})
    with pytest.raises(ModelUnavailable) as error:
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert error.value.model == MODEL


async def test_a_withdrawn_model_blames_the_model():
    # 410 Gone : « cette ressource a disparu définitivement ». Constaté en vrai
    # sur minimaxai/minimax-m3 pendant la campagne réseau. Le traiter au niveau
    # du fournisseur ferait abandonner ses autres modèles, encore vivants.
    handler = _replying(410, {"error": {"message": "model retired"}})
    with pytest.raises(ModelUnavailable) as error:
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert error.value.model == MODEL


async def test_a_bad_request_blames_the_model():
    handler = _replying(400, {"error": {"message": "unsupported parameter"}})
    with pytest.raises(ModelUnavailable):
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))


async def test_a_server_error_blames_the_provider():
    handler = _replying(503, {"error": {"message": "overloaded"}})
    with pytest.raises(ProviderUnavailable) as error:
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert error.value.issue == "erreur"


async def test_an_unreachable_host_blames_the_provider():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("injoignable", request=request)

    with pytest.raises(ProviderUnavailable) as error:
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    assert error.value.issue == "erreur"


async def test_the_client_never_retries_on_its_own():
    # Un repli interne au SDK brûlerait le quota que la bascule préserve, et
    # cacherait à la passerelle l'information qui lui sert à décider.
    assert client_for(PROVIDER, timeout=1.0).max_retries == 0


async def test_every_base_url_is_carried_to_the_client():
    for provider in PROVIDERS.values():
        assert str(client_for(provider, timeout=1.0).base_url).startswith(
            provider.base_url.rstrip("/")
        )


async def test_the_stream_yields_the_deltas_in_order():
    chunks = ["Le ", "dispositif ", "retenu."]
    events = "".join(
        "data: "
        + json.dumps(
            {
                "id": "1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": MODEL,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
        )
        + "\n\n"
        for piece in chunks
    ) + "data: [DONE]\n\n"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=events.encode()
        )

    received = [
        piece async for piece in stream_chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))
    ]
    assert received == chunks


async def test_a_stream_refused_before_it_opens_blames_the_provider():
    handler = _replying(429, {"error": {"message": "rate limit"}})
    with pytest.raises(ProviderUnavailable):
        async for _ in stream_chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler)):
            pass
