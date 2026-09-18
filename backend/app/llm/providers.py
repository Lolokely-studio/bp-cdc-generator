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
        models=("mistral-small-latest", "open-mistral-nemo"),
        # 200 000 est la borne basse de la fourchette 200 000 – 315 000
        # relevée sur le palier gratuit. On retient la borne basse : un
        # budget qui sous-estime le plafond bascule trop tôt, l'inverse
        # coupe une rédaction au milieu.
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
