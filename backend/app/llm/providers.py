from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class Limits:
    """Quotas du palier gratuit. `None` signifie « pas de plafond publié ».

    Relevés en septembre 2026. Les offres gratuites bougent souvent et
    celles-là plus vite que les autres : cette table est un réglage, pas une
    vérité. `rps` est à part — une limite par seconde ne se tient pas avec
    une fenêtre en base, voir `app.llm.budget.Pacer`.
    """

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None
    rps: float | None = None


@dataclass(frozen=True)
class Provider:
    """`key_setting` est le nom de l'attribut de `Settings` qui porte la clé,
    pas la clé : le catalogue reste importable et lisible sans secret."""

    name: str
    base_url: str
    key_setting: str
    models: tuple[str, ...]
    limits: Limits


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        name="gemini",
        # La barre finale est obligatoire : sans elle, le client OpenAI
        # construit une URL que Google refuse.
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        key_setting="gemini_api_key",
        models=("gemini-3.1-flash-lite",),
        limits=Limits(rpm=15, tpm=250_000, rpd=1_000),
    ),
    "mistral": Provider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        key_setting="mistral_ai_api_key",
        # Relevé à la main sur la clé du compte, contre les quotas publiés
        # dans la console. Deux choses que la documentation ne dit pas :
        #
        # 1. Chez Mistral les plafonds sont PAR MODÈLE, pas par compte — de
        #    20 000 à 20 000 000 jetons/minute selon le modèle. La structure
        #    `Limits` les porte au niveau du fournisseur ; l'invariant qui
        #    rend cette simplification sûre est que le plafond propre de
        #    chaque modèle listé ici dépasse celui déclaré plus bas.
        # 2. `mistral-small`, `mistral-medium` et `magistral-small` sont
        #    exposés par `/v1/models` mais refusent chaque appel en 429, dès
        #    le premier, sans rien avoir consommé ; `mistral-large` et
        #    `labs-leanstral` répondent 403. Les trois retenus répondent.
        #
        # L'ordre compte doublement : un 429 est classé au niveau du
        # fournisseur, donc un premier modèle qui refuse toujours ferait
        # sauter Mistral des deux routes où il figure sans qu'aucun modèle
        # vivant ne soit jamais essayé.
        #
        #   ministral-8b-latest   625 000 jetons/min   3,13 req/s
        #   ministral-3b-latest 1 300 000 jetons/min  12,50 req/s
        #   open-mistral-nemo    plafonds non publiés, répond
        models=("ministral-8b-latest", "ministral-3b-latest", "open-mistral-nemo"),
        # Un plancher qu'aucun modèle listé ci-dessus ne descend en dessous,
        # et non une moyenne : le budget déclaré doit rester sous le plafond
        # réel du modèle le plus contraint, `open-mistral-nemo` ne publiant
        # pas les siens. Sous-estimer fait basculer un peu tôt, ce qui ne se
        # voit pas ; surestimer coupe une rédaction au milieu, ce qui se voit.
        # Même raisonnement pour `rps=1`, en dessous des 3,13 du 8b et des
        # 12,50 du 3b : l'espacement coûte une seconde par appel sur un
        # fournisseur qui n'est jamais premier de sa route.
        limits=Limits(tpm=200_000, rps=1),
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_setting="openrouter_api_key",
        models=(
            "openrouter/free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "poolside/laguna-s-2.1:free",
            "inclusionai/ling-3.0-flash-fin:free",
        ),
        # Cinquante requêtes par jour : tenu hors des routes courantes et
        # réservé au contrôle de cohérence, seul endroit où le million de
        # jetons de contexte sert à quelque chose.
        limits=Limits(rpm=20, rpd=50),
    ),
    "nvidia": Provider(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        key_setting="nvidia_api_key",
        models=(
            "nvidia/nemotron-3.5-lightning-30b-a3b",
            "deepseek-ai/deepseek-v4-flash-0731",
            "minimaxai/minimax-m3",
            "z-ai/glm-5.3",
            "moonshotai/kimi-k3",
        ),
        limits=Limits(rpm=40),
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        key_setting="groq_cloud_api_key",
        models=("groq/compound", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"),
        limits=Limits(rpm=30, tpm=12_000, rpd=14_400, tpd=500_000),
    ),
}

# Trois routes, jamais un fournisseur nommé dans le graphe : un nœud demande
# une capacité. Changer de route est un réglage, pas une modification du
# graphe (§5.1).
ROUTES: dict[str, tuple[str, ...]] = {
    "court": ("groq", "nvidia", "mistral"),
    "redaction": ("gemini", "mistral", "nvidia"),
    "grand_contexte": ("openrouter", "gemini"),
}


def providers_for_route(route: str) -> tuple[Provider, ...]:
    """Les fournisseurs de la route, dans l'ordre d'essai."""
    if route not in ROUTES:
        raise KeyError(f"route inconnue : {route}")
    return tuple(PROVIDERS[name] for name in ROUTES[route])


def api_key_for(provider: Provider) -> str:
    """`getattr` sans valeur par défaut : une faute de frappe dans
    `key_setting` doit lever, pas rendre une chaîne vide qui ferait passer
    le fournisseur pour « non configuré » jusqu'à la fin des temps."""
    return getattr(settings(), provider.key_setting)


def is_configured(provider: Provider) -> bool:
    """Un fournisseur sans clé est sauté avant tout appel : l'essayer
    coûterait un aller-retour et une ligne d'erreur pour un échec connu."""
    return bool(api_key_for(provider))
