from collections.abc import AsyncIterator, Sequence
from uuid import UUID

from pydantic import BaseModel

from app.core.config import settings
from app.core.db import connection
from app.llm import transport as network_transport
from app.llm.budget import budget_available, pacer_for, record_usage
from app.llm.errors import ModelUnavailable, NoProviderAvailable, ProviderUnavailable
from app.llm.fake import FAKE_PROVIDER, FakeTransport
from app.llm.providers import Provider, is_configured, providers_for_route
from app.llm.tokens import estimate_tokens
from app.llm.types import (
    Completion,
    Message,
    StreamDone,
    StreamEvent,
    StreamRestart,
    TextDelta,
)

# Un appel court tient dans quelques centaines de jetons de sortie ; une
# section en demande beaucoup plus. Ce ne sont que des valeurs par défaut :
# le graphe passera l'estimation qu'il connaît, section par section.
DEFAULT_OUTPUT_TOKENS = 1_024
DEFAULT_SECTION_TOKENS = 4_096


def _default_transport():
    """Le simulé remplace le transport, jamais la passerelle. Les deux
    exposent `chat` et `stream_chat` avec les mêmes signatures ; c'est tout
    ce que la passerelle leur demande."""
    return FakeTransport() if settings().fake_llm else network_transport


async def _record(
    *,
    route: str,
    provider: Provider,
    model: str,
    project_id: UUID | None,
    tokens: int,
    issue: str,
    fake: bool,
) -> None:
    """En mode simulé, la ligne s'écrit sous le nom `fake` : les compteurs des
    vrais fournisseurs restent intacts et une exécution hors ligne ne consomme
    aucun budget réel — tout en traversant le même code."""
    async with connection() as conn:
        await record_usage(
            conn,
            provider=FAKE_PROVIDER if fake else provider.name,
            model=model,
            route=route,
            project_id=project_id,
            tokens=tokens,
            issue=issue,
        )


async def _usable(provider: Provider, estimated_tokens: int, fake: bool) -> str | None:
    """`None` si le fournisseur est utilisable, sinon la raison du saut.

    Ni l'absence de clé ni un budget insuffisant n'écrivent de ligne : rien
    n'a été consommé, et une ligne à zéro requête fausserait la fenêtre.
    """
    if fake:
        return None
    if not is_configured(provider):
        return "pas de clé"
    async with connection() as conn:
        if not await budget_available(conn, provider, estimated_tokens):
            return "budget insuffisant"
    return None


async def _pace(provider: Provider, fake: bool) -> None:
    if fake:
        return
    pacer = pacer_for(provider)
    if pacer is not None:
        await pacer.wait()


async def complete(
    route: str,
    messages: Sequence[Message],
    *,
    project_id: UUID | None = None,
    schema: type[BaseModel] | None = None,
    expected_output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    transport=None,
) -> Completion:
    """Un appel non diffusé, sur la première combinaison qui répond.

    `transport` n'est renseigné que par les tests. La valeur par défaut est
    résolue à l'appel et non à l'import, pour que le mode simulé se décide
    sur la configuration du moment.
    """
    transport = transport if transport is not None else _default_transport()
    fake = settings().fake_llm
    estimated = estimate_tokens(messages) + expected_output_tokens
    attempts: list[str] = []

    for provider in providers_for_route(route):
        skip = await _usable(provider, estimated, fake)
        if skip is not None:
            attempts.append(f"{provider.name} : {skip}")
            continue

        for model in provider.models:
            await _pace(provider, fake)
            try:
                result = await transport.chat(provider, model, messages, schema=schema)
            except ModelUnavailable as error:
                await _record(route=route, provider=provider, model=model,
                              project_id=project_id, tokens=0, issue="erreur", fake=fake)
                attempts.append(f"{provider.name}/{model} : {error.reason}")
                continue
            except ProviderUnavailable as error:
                await _record(route=route, provider=provider, model=model,
                              project_id=project_id, tokens=0, issue=error.issue, fake=fake)
                attempts.append(f"{provider.name}/{model} : {error.reason}")
                break

            await _record(route=route, provider=provider, model=model,
                          project_id=project_id, tokens=result.tokens, issue="ok", fake=fake)
            return result

    raise NoProviderAvailable(route, attempts)


async def stream(
    route: str,
    messages: Sequence[Message],
    *,
    project_id: UUID | None = None,
    expected_output_tokens: int = DEFAULT_SECTION_TOKENS,
    transport=None,
) -> AsyncIterator[StreamEvent]:
    """Une section en flux.

    Le budget porte sur la section **entière**, prompt et sortie comprise
    (§5.2) : une bascule décidée ici se fait avant d'ouvrir le flux, ce qui
    évite qu'un paragraphe déjà affiché s'efface.
    """
    transport = transport if transport is not None else _default_transport()
    fake = settings().fake_llm
    prompt_tokens = estimate_tokens(messages)
    estimated = prompt_tokens + expected_output_tokens
    attempts: list[str] = []

    for provider in providers_for_route(route):
        skip = await _usable(provider, estimated, fake)
        if skip is not None:
            attempts.append(f"{provider.name} : {skip}")
            continue

        for model in provider.models:
            await _pace(provider, fake)
            emitted: list[str] = []
            try:
                async for delta in transport.stream_chat(provider, model, messages):
                    emitted.append(delta)
                    yield TextDelta(delta)
            except (ModelUnavailable, ProviderUnavailable) as error:
                issue = error.issue if isinstance(error, ProviderUnavailable) else "erreur"
                written = "".join(emitted)
                # Le prompt entier est parti et le fournisseur l'a traité,
                # même si le flux s'est rompu ensuite. Ne compter que le texte
                # reçu sous-estimerait la consommation réelle — et c'est la
                # fenêtre de budget qui se nourrit de ce chiffre, donc
                # l'erreur se paierait en 429 plus tard.
                await _record(
                    route=route, provider=provider, model=model, project_id=project_id,
                    tokens=prompt_tokens + estimate_tokens([Message("assistant", written)]),
                    issue=issue, fake=fake,
                )
                attempts.append(f"{provider.name}/{model} : {error.reason}")
                if emitted:
                    # Le flux avait commencé. La section repart entière sur le
                    # fournisseur suivant (§5.2), jamais sur le modèle suivant :
                    # le consommateur a du texte à l'écran et doit le vider.
                    yield StreamRestart(provider.name, model, error.reason)
                    break
                # Rien n'avait été émis : essai raté ordinaire, on suit l'ordre
                # du §5.3 — modèle suivant si le modèle est en cause,
                # fournisseur suivant sinon.
                if isinstance(error, ProviderUnavailable):
                    break
                continue

            written = "".join(emitted)
            tokens = prompt_tokens + estimate_tokens([Message("assistant", written)])
            await _record(route=route, provider=provider, model=model,
                          project_id=project_id, tokens=tokens, issue="ok", fake=fake)
            yield StreamDone(provider.name, model, tokens)
            return

    raise NoProviderAvailable(route, attempts)
