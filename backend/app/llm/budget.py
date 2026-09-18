import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.llm.providers import Provider


async def record_usage(
    conn,
    *,
    provider: str,
    model: str,
    route: str,
    project_id: UUID | None,
    tokens: int,
    issue: str,
) -> None:
    """Une ligne par essai réellement émis, succès comme échec.

    Les bascules préventives n'en écrivent pas : elles n'ont rien consommé,
    et une ligne à zéro requête fausserait la fenêtre autant qu'une ligne
    manquante. Un 429 en revanche s'écrit — la requête est partie et le
    fournisseur l'a comptée.

    Les paramètres sont nommés obligatoirement : `provider`, `model`, `route`
    et `issue` sont quatre chaînes voisines qu'un appel positionnel pourrait
    intervertir sans qu'aucun typage ne s'en aperçoive.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into llm_usage
                (fournisseur, modele, route, project_id, requetes, tokens, issue)
            values (%s, %s, %s, %s, 1, %s, %s)
            """,
            (provider, model, route, project_id, tokens, issue),
        )


async def budget_available(conn, provider: Provider, estimated_tokens: int) -> bool:
    """Le fournisseur peut-il encaisser un appel de cette taille maintenant ?

    Une seule requête produit les quatre agrégats : la lecture est bornée à
    la journée, ce qui la garde dans l'index `(fournisseur, at desc)`, et les
    deux agrégats de la minute sont des filtres sur cette même lecture.

    `now()` est évalué par instruction, la connexion étant en `autocommit` :
    la fenêtre est bien glissante et non figée sur un début de transaction.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select
              coalesce(sum(requetes) filter (where at > now() - interval '1 minute'), 0),
              coalesce(sum(tokens)   filter (where at > now() - interval '1 minute'), 0),
              coalesce(sum(requetes), 0),
              coalesce(sum(tokens),   0)
            from llm_usage
            where fournisseur = %s and at > now() - interval '1 day'
            """,
            (provider.name,),
        )
        requests_minute, tokens_minute, requests_day, tokens_day = await cur.fetchone()

    limits = provider.limits
    # L'appel à venir compte : on répond « ce coup-ci passe-t-il », pas
    # « où en est-on ». La différence est tout l'intérêt de la bascule
    # préventive.
    if limits.rpm is not None and requests_minute + 1 > limits.rpm:
        return False
    if limits.tpm is not None and tokens_minute + estimated_tokens > limits.tpm:
        return False
    if limits.rpd is not None and requests_day + 1 > limits.rpd:
        return False
    if limits.tpd is not None and tokens_day + estimated_tokens > limits.tpd:
        return False
    return True


class Pacer:
    """Espacement minimal entre deux appels à un même fournisseur.

    Mistral plafonne à une requête par seconde. Une fenêtre en base ne tient
    pas cette échelle : l'aller-retour SQL dure lui-même quelques
    millisecondes, et deux tâches concurrentes liraient le même compteur
    avant que l'une ait écrit. L'espacement se tient donc en mémoire du
    processus, sous verrou — correct tant qu'il n'y a qu'une instance, ce qui
    est le cas sur l'hébergement gratuit (§9.2). Plusieurs instances le
    rendraient inopérant, comme le compteur de `app.core.rate_limit`.

    `clock` et `sleep` sont injectables pour que les tests vérifient l'attente
    sans la subir.
    """

    def __init__(
        self,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval = interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def wait(self) -> None:
        # Le verrou couvre l'attente elle-même : le relâcher avant de dormir
        # laisserait deux appelants calculer le même créneau et partir
        # ensemble, ce qui est précisément ce qu'on empêche.
        async with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self.interval - (now - self._last)
                if remaining > 0:
                    await self._sleep(remaining)
                    now = self._clock()
            self._last = now


_pacers: dict[str, Pacer] = {}


def pacer_for(provider: Provider) -> Pacer | None:
    """`None` quand le fournisseur ne publie pas de limite par seconde :
    l'appelant n'attend pas.

    L'instance est partagée par nom de fournisseur : deux instances
    laisseraient passer deux requêtes dans la même seconde.
    """
    rps = provider.limits.rps
    if rps is None:
        return None
    if provider.name not in _pacers:
        _pacers[provider.name] = Pacer(1.0 / rps)
    return _pacers[provider.name]


def reset_pacers() -> None:
    """Remise à zéro entre deux tests : l'espacement vit dans le processus."""
    _pacers.clear()
