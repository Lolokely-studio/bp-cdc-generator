from collections.abc import AsyncIterator, Sequence
from typing import NoReturn

import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.llm.errors import ModelUnavailable, ProviderUnavailable
from app.llm.providers import Provider, api_key_for
from app.llm.tokens import estimate_tokens
from app.llm.types import Completion, Message

REQUEST_TIMEOUT_SECONDS = 60.0
# Une section entière prend plus longtemps qu'un appel court, et le délai
# court sur toute la durée du flux, pas sur le premier octet.
STREAM_TIMEOUT_SECONDS = 180.0


# Un client par fournisseur, gardé pour la durée du processus. Le construire
# à chaque appel rouvrirait une connexion TLS à chaque fois et laisserait
# derrière lui un pool de connexions que personne ne ferme : `close_clients`
# est le pendant de ce dictionnaire, et le cycle de vie de l'application
# l'appelle à l'arrêt.
_clients: dict[str, AsyncOpenAI] = {}


def _build_client(provider: Provider, http_client: httpx2.AsyncClient | None) -> AsyncOpenAI:
    """`max_retries=0` est essentiel. Le client réessaie un 429 par défaut : il
    brûlerait le quota que la bascule préventive cherche à préserver, et
    cacherait à la passerelle l'information qui lui sert à changer de
    fournisseur. Le repli est notre affaire, pas celle du SDK.

    Aucun délai n'est posé ici : un appel court et une rédaction en flux n'ont
    pas la même patience, et le délai se passe donc à chaque requête.
    """
    return AsyncOpenAI(
        api_key=api_key_for(provider),
        base_url=provider.base_url,
        max_retries=0,
        http_client=http_client,
    )


def client_for(
    provider: Provider, *, http_client: httpx2.AsyncClient | None = None
) -> AsyncOpenAI:
    """Un seul adaptateur pour les cinq fournisseurs : tous exposent l'API
    Chat Completions d'OpenAI, seule l'URL de base change.

    `http_client` n'est renseigné que par les tests, qui y branchent un
    transport simulé et exercent ainsi le vrai code du client — découpage des
    flux et classification des statuts compris. Un client ainsi fabriqué n'est
    pas partagé : il appartient au test, qui le jette.
    """
    if http_client is not None:
        return _build_client(provider, http_client)
    if provider.name not in _clients:
        _clients[provider.name] = _build_client(provider, None)
    return _clients[provider.name]


async def close_clients() -> None:
    """Ferme les clients partagés. Appelée à l'arrêt de l'application : sans
    elle, les pools de connexions survivraient au processus qui les a ouverts.
    Les tests s'en servent aussi, pour ne pas se passer un client d'un cas à
    l'autre."""
    while _clients:
        _, client = _clients.popitem()
        await client.close()


def _fail(provider: Provider, model: str, error: Exception) -> NoReturn:
    """Traduit une erreur du client en décision de repli.

    Le pseudo-code du §5.3 range tous les échecs au niveau du fournisseur.
    On y ajoute une distinction que l'exploitation impose : un 400, un 404 ou
    un 410 désigne **ce modèle-là**. Un modèle gratuit retiré du catalogue —
    le cas annoncé dans les parades — répond 404 ou 410, et basculer de
    fournisseur reviendrait à abandonner ses autres modèles, encore valides.
    Le 410 a été constaté en vrai pendant la campagne réseau, sur
    `minimaxai/minimax-m3` chez NVIDIA, pendant que d'autres modèles du même
    fournisseur répondaient normalement.

    `RateLimitError` se teste avant `APIStatusError` : c'en est une
    sous-classe, l'ordre inverse la rendrait inatteignable.
    """
    if isinstance(error, RateLimitError):
        raise ProviderUnavailable(provider.name, "quota", "429 du fournisseur") from error
    if isinstance(error, APITimeoutError):
        raise ProviderUnavailable(provider.name, "timeout", "délai dépassé") from error
    if isinstance(error, APIConnectionError):
        raise ProviderUnavailable(provider.name, "erreur", "connexion impossible") from error
    if isinstance(error, APIStatusError):
        if error.status_code in (400, 404, 410):
            raise ModelUnavailable(model, f"statut {error.status_code}") from error
        raise ProviderUnavailable(
            provider.name, "erreur", f"statut {error.status_code}"
        ) from error
    raise ProviderUnavailable(provider.name, "erreur", repr(error)) from error


def _as_payload(messages: Sequence[Message]) -> list[dict]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _parse(schema: type[BaseModel], text: str, model: str) -> BaseModel:
    """Le contenu arrive parfois entouré d'une clôture Markdown : plusieurs
    modèles gratuits en ajoutent une malgré la consigne du prompt. La retirer
    coûte trois lignes ; la refuser coûterait un modèle par section."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return schema.model_validate_json(cleaned)
    except ValidationError as error:
        raise ModelUnavailable(model, "sortie hors schéma") from error


async def chat(
    provider: Provider,
    model: str,
    messages: Sequence[Message],
    *,
    schema: type[BaseModel] | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> Completion:
    """Un appel non diffusé. Aucun `response_format` n'est envoyé : les cinq
    paliers gratuits ne le gèrent pas de la même façon et un refus se
    traduirait par un 400, c'est-à-dire par un modèle déclaré mort à tort.
    La consigne JSON vit dans le prompt, `_parse` rattrape le reste."""
    client = client_for(provider, http_client=http_client)
    try:
        response = await client.chat.completions.create(
            model=model, messages=_as_payload(messages), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except OpenAIError as error:
        _fail(provider, model, error)

    # Certains paliers gratuits répondent 200 avec une liste de choix vide.
    # Sans ce garde-fou, l'`IndexError` remonterait brute et la passerelle
    # n'aurait rien à quoi se raccrocher : tout échec doit sortir d'ici classé.
    if not response.choices:
        raise ModelUnavailable(model, "réponse sans choix")

    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    # Plusieurs paliers gratuits omettent `usage`. Sans repli, ces appels
    # resteraient invisibles à la fenêtre de jetons.
    tokens = (
        usage.total_tokens
        if usage is not None and usage.total_tokens
        else estimate_tokens(messages) + estimate_tokens([Message("assistant", text)])
    )
    parsed = _parse(schema, text, model) if schema is not None else None
    return Completion(
        text=text, provider=provider.name, model=model, tokens=tokens, parsed=parsed
    )


async def stream_chat(
    provider: Provider,
    model: str,
    messages: Sequence[Message],
    *,
    http_client: httpx2.AsyncClient | None = None,
) -> AsyncIterator[str]:
    """Les fragments, dans l'ordre. Une rupture après le premier fragment est
    traitée par la passerelle, seule à savoir qu'il faut alors repartir sur
    le fournisseur suivant plutôt que sur le modèle suivant."""
    client = client_for(provider, http_client=http_client)
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=_as_payload(messages),
            stream=True,
            timeout=STREAM_TIMEOUT_SECONDS,
        )
    except OpenAIError as error:
        _fail(provider, model, error)

    try:
        async for chunk in stream:
            # Certains fournisseurs émettent des trames de service sans choix,
            # notamment pour publier l'usage en fin de flux.
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except OpenAIError as error:
        _fail(provider, model, error)
