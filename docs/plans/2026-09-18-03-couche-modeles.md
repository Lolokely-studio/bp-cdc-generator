# Couche modèles — plan d'implémentation

> **Pour les agents d'exécution :** SOUS-COMPÉTENCE REQUISE — utiliser
> `superpowers:subagent-driven-development` (recommandé) ou
> `superpowers:executing-plans` pour dérouler ce plan tâche par tâche.
> Les étapes utilisent des cases à cocher (`- [ ]`) pour le suivi.

**But :** les trois routes de la spec, des compteurs de quota adossés à `llm_usage`, la bascule préventive avant l'ouverture d'un flux, le repli entre cinq fournisseurs gratuits, et un modèle simulé déterministe qui permet au plan 3 de faire tourner le graphe entier sans réseau.

**Architecture :** les cinq fournisseurs exposent tous l'API *Chat Completions* d'OpenAI — vérifié pour chacun. La couche tient donc dans **un seul adaptateur et cinq URL de base**, pas cinq bibliothèques. Trois modules déclaratifs (types, erreurs, catalogue) portent le vocabulaire ; un module de budget interroge `llm_usage` ; un transport parle aux fournisseurs ; une passerelle applique l'ordre des essais du §5.3. Le modèle simulé remplace le transport, jamais la passerelle : la sélection de route et l'écriture de `llm_usage` empruntent les mêmes chemins de code en développement et en production.

**Pile :** Python 3.12, uv, `openai` (client asynchrone, utilisé comme transport générique), psycopg 3, pydantic, pytest, pytest-asyncio, `httpx.MockTransport` pour les tests.

**Spec :** [../spec-implementation.md](../spec-implementation.md) — §2.1 table `llm_usage`, §5 couche modèles, §9.2 instance unique, §11 configuration.
**Feuille de route :** [2026-09-17-feuille-de-route.md](2026-09-17-feuille-de-route.md) — plan 2, dépend du plan 1.

**Branche :** `plan-03-couche-modeles`, fusionnée dans `main` à la fin.

## Contraintes globales

- **Gestionnaire de paquets : `uv`, jamais `pip`.** Toute commande passe par `uv run`. Une dépendance s'ajoute par `uv add`, qui met `uv.lock` à jour ; les deux fichiers sont versionnés.
- **Python 3.12.**
- **Les identifiants du code sont en anglais** : fonctions, classes, fixtures, modules, fichiers, variables et constantes. **Les commentaires et les docstrings restent en français.**
- **Restent en français, ce sont des valeurs de contrat** : les noms de colonnes de `llm_usage` (`fournisseur`, `modele`, `route`, `requetes`, `tokens`, `issue`, `at`), les valeurs de `issue` (`ok`, `quota`, `erreur`, `timeout`) et les noms de routes (`court`, `redaction`, `grand_contexte`).
- **Aucun test de la suite ordinaire ne joint un fournisseur de modèle ni la base de production.** La seule exception est la campagne marquée `network`, exclue par défaut et lancée à la main.
- **`CEREBRAS_CLOUD_API_KEY` reste hors routage.** La clé existe dans le `.env` ; c'est une décision, pas un oubli. Un test l'ancre.
- **Aucun repli automatique du client HTTP.** Le client `openai` est construit avec `max_retries=0` : si le SDK réessayait un 429 tout seul, il brûlerait le quota que la bascule cherche justement à préserver.
- **Les commandes `uv` et `pytest` se lancent depuis `backend/`, les commandes `git` depuis la racine du dépôt.** Les chemins des blocs de commit sont écrits en conséquence.
- **Le pooler Supabase est en mode transaction.** Aucune variable de session ; ce qui doit valoir pour une requête se pose en `SET LOCAL`.

---

## Structure des fichiers

```
backend/
├── app/
│   ├── core/
│   │   └── config.py            MODIFIÉ : cinq clés d'API
│   └── llm/
│       ├── __init__.py          vide, docstring de paquet
│       ├── types.py             Message, Completion, événements de flux
│       ├── errors.py            ModelUnavailable, ProviderUnavailable, NoProviderAvailable
│       ├── tokens.py            estimation haute du coût en jetons
│       ├── providers.py         catalogue des cinq fournisseurs et des trois routes
│       ├── budget.py            fenêtres glissantes sur llm_usage, espacement par seconde
│       ├── fake.py              modèle simulé déterministe
│       ├── transport.py         adaptateur compatible OpenAI, cinq URL de base
│       └── gateway.py           ordre des essais, bascule préventive, repli
└── tests/
    ├── conftest.py              MODIFIÉ : clés de test, sauf campagne réseau
    ├── test_tokens.py
    ├── test_providers.py
    ├── test_budget.py
    ├── test_fake.py
    ├── test_transport.py
    ├── test_gateway.py
    └── test_network_providers.py   marqué `network`, exclu par défaut
```

**Découpage.** `types`, `errors`, `tokens` et `providers` sont purs et sans dépendance : ils forment le vocabulaire et vivent dans une seule tâche. Les trois modules qui s'en servent — `budget` (base), `fake` (hors ligne), `transport` (réseau) — ne partagent aucun fichier et se dispatchent **en parallèle**. `gateway` les assemble et vient en dernier.

---

## Ordre d'exécution

```
Tâche 1  ─┬─ Tâche 2  (budget)     ─┐
          ├─ Tâche 3  (simulé)     ─┼─ Tâche 5  (passerelle)
          └─ Tâche 4  (transport)  ─┘
```

Les tâches 2, 3 et 4 se dispatchent dans le même message. Elles ne créent aucun fichier commun et ne consomment de la tâche 1 que des signatures figées par les blocs **Interfaces**.

---

## Tâche 1 : le vocabulaire de la couche modèles

**Fichiers :**
- Créer : `backend/app/llm/__init__.py`, `backend/app/llm/types.py`, `backend/app/llm/errors.py`, `backend/app/llm/tokens.py`, `backend/app/llm/providers.py`
- Modifier : `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/render.yaml`, `docs/mockup.html`, `README.md`
- Tests : `backend/tests/test_tokens.py`, `backend/tests/test_providers.py`

**Interfaces :**
- Consomme : `app.core.config.settings()` (plan 1).
- Produit :
  - `Message(role: Role, content: str)`, `Completion(text, provider, model, tokens, parsed)`, `TextDelta(text)`, `StreamRestart(provider, model, reason)`, `StreamDone(provider, model, tokens)`, alias `StreamEvent`
  - `ModelUnavailable(model, reason)` avec attributs `.model`, `.reason`
  - `ProviderUnavailable(provider, issue, reason)` avec attributs `.provider`, `.issue`, `.reason`
  - `NoProviderAvailable(route, attempts)` avec attributs `.route`, `.attempts`
  - `estimate_tokens(messages: Iterable[Message]) -> int`, constante `CHARS_PER_TOKEN`
  - `Limits(rpm, tpm, rpd, tpd, rps)`, `Provider(name, base_url, key_setting, models, limits)`, `PROVIDERS: dict[str, Provider]`, `ROUTES: dict[str, tuple[str, ...]]`, `providers_for_route(route) -> tuple[Provider, ...]`, `api_key_for(provider) -> str`, `is_configured(provider) -> bool`
  - `Settings` gagne `gemini_api_key`, `mistral_ai_api_key`, `openrouter_api_key`, `nvidia_api_key`, `groq_cloud_api_key`
  - `backend/render.yaml` déclare les cinq clés côté production

**Pourquoi tout cela dans une seule tâche.** Ce sont cinq fichiers déclaratifs, sans branche ni entrée-sortie. Les séparer donnerait cinq relectures qui ne peuvent rien rejeter indépendamment — et retarderait le seul point de synchronisation dont les trois tâches suivantes ont besoin.

- [ ] **Étape 1 : écrire les tests d'estimation**

`backend/tests/test_tokens.py` :

```python
from app.llm.tokens import CHARS_PER_TOKEN, estimate_tokens
from app.llm.types import Message


def test_estimate_grows_with_the_text():
    short = estimate_tokens([Message("user", "a" * 100)])
    long = estimate_tokens([Message("user", "a" * 1000)])
    assert long > short


def test_estimate_sums_every_message():
    one = estimate_tokens([Message("user", "a" * 300)])
    two = estimate_tokens([Message("system", "a" * 300), Message("user", "a" * 300)])
    assert two > one


def test_estimate_stays_above_a_real_tokenizer():
    # Un tokeniseur réel sort du français autour de quatre caractères par
    # jeton. L'estimation doit rester au-dessus : elle sert à décider d'une
    # bascule, et se tromper vers le bas coupe une rédaction au milieu.
    text = "Le dispositif retenu couvre le périmètre décrit au cadrage. " * 20
    assert estimate_tokens([Message("user", text)]) > len(text) / 4
    assert CHARS_PER_TOKEN < 4


def test_empty_messages_cost_nothing_absurd():
    assert 0 < estimate_tokens([Message("user", "")]) < 5
```

- [ ] **Étape 2 : écrire les tests du catalogue**

`backend/tests/test_providers.py` :

```python
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.llm import providers as providers_module
from app.llm.providers import (
    PROVIDERS,
    ROUTES,
    api_key_for,
    is_configured,
    providers_for_route,
)


def test_the_three_routes_match_the_spec():
    # L'ordre est le contrat : c'est lui qui décide quel fournisseur
    # encaisse quelle contrainte (§5.1).
    assert ROUTES == {
        "court": ("groq", "nvidia", "mistral"),
        "redaction": ("gemini", "mistral", "nvidia"),
        "grand_contexte": ("openrouter", "gemini"),
    }


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_every_route_names_known_providers(route):
    assert all(name in PROVIDERS for name in ROUTES[route])


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_every_provider_has_a_model_and_a_base_url(name):
    provider = PROVIDERS[name]
    assert provider.models
    assert provider.base_url.startswith("https://")
    assert provider.name == name


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_every_key_setting_exists_on_settings(name):
    # `api_key_for` lit l'attribut sans valeur par défaut : une faute de
    # frappe ici rendrait le fournisseur éternellement « non configuré »
    # sans qu'aucune erreur ne le dise.
    assert PROVIDERS[name].key_setting in Settings.model_fields


def test_cerebras_stays_out_of_routing():
    # Décision explicite, pas un oubli : la clé existe dans le `.env`.
    assert "cerebras" not in PROVIDERS
    assert not any("cerebras" in p.base_url for p in PROVIDERS.values())


def test_gemini_base_url_keeps_its_trailing_slash():
    # Sans la barre finale, le client OpenAI construit une URL que Google
    # refuse. Le détail est invisible à la relecture, un test le tient.
    assert PROVIDERS["gemini"].base_url.endswith("/")


def test_providers_for_route_returns_objects_in_order():
    assert [p.name for p in providers_for_route("court")] == ["groq", "nvidia", "mistral"]


def test_unknown_route_is_refused():
    with pytest.raises(KeyError):
        providers_for_route("inexistante")


def test_provider_without_key_is_not_configured(monkeypatch):
    # On remplace `settings` dans `app.llm.providers`, pas dans
    # `app.core.config` : `providers` a importé le nom, corriger la source
    # n'atteindrait plus la référence déjà liée.
    #
    # Et on passe un objet quelconque plutôt qu'un `Settings` : construire un
    # `Settings` en test rejouerait la lecture de l'environnement et les
    # alias de champs, deux choses sans rapport avec ce qu'on vérifie ici.
    keys = {provider.key_setting: "cle-de-test" for provider in PROVIDERS.values()}
    keys["gemini_api_key"] = ""
    monkeypatch.setattr(providers_module, "settings", lambda: SimpleNamespace(**keys))
    assert api_key_for(PROVIDERS["gemini"]) == ""
    assert not is_configured(PROVIDERS["gemini"])


def test_a_typo_in_a_key_setting_raises_instead_of_lying(monkeypatch):
    # Sans cette garantie, une faute de frappe dans `key_setting` rendrait le
    # fournisseur « non configuré » pour toujours, sans un mot.
    monkeypatch.setattr(providers_module, "settings", lambda: SimpleNamespace())
    with pytest.raises(AttributeError):
        api_key_for(PROVIDERS["gemini"])


def test_provider_with_a_key_is_configured():
    # conftest pose une clé de test pour les cinq fournisseurs.
    assert is_configured(PROVIDERS["gemini"])
```

- [ ] **Étape 3 : lancer les deux fichiers et vérifier qu'ils échouent**

Run : `uv run pytest tests/test_tokens.py tests/test_providers.py -v`
Attendu : ÉCHEC à la collecte, `ModuleNotFoundError: No module named 'app.llm'`.

- [ ] **Étape 4 : écrire `app/llm/__init__.py`**

```python
"""Couche modèles d'Esquisse.

Les cinq fournisseurs gratuits exposent tous l'API Chat Completions
d'OpenAI : un seul adaptateur suffit, seule l'URL de base change. Le point
d'entrée est `app.llm.gateway`, qui applique l'ordre des essais du §5.3 de
la spec. Rien n'est réexporté ici, pour qu'un import de paquet ne tire pas
le transport réseau quand seul le vocabulaire est nécessaire.
"""
```

- [ ] **Étape 5 : écrire `app/llm/types.py`**

```python
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    """Un tour de conversation, dans la forme commune aux cinq fournisseurs."""

    role: Role
    content: str


@dataclass(frozen=True)
class Completion:
    """Réponse d'un appel non diffusé.

    `provider` et `model` disent qui a répondu : la spec demande que le
    modèle retenu soit noté sur la trace, parce qu'un modèle gratuit peut
    disparaître entre deux projets et qu'on veut savoir lequel a écrit quoi.
    `parsed` ne vaut `None` que si l'appel n'a demandé aucun schéma.
    """

    text: str
    provider: str
    model: str
    tokens: int
    parsed: object | None = None


@dataclass(frozen=True)
class TextDelta:
    """Un fragment de texte à afficher tel quel."""

    text: str


@dataclass(frozen=True)
class StreamRestart:
    """Le flux s'est rompu après avoir déjà émis du texte.

    La section repart entière sur le fournisseur suivant (§5.2). Le
    consommateur doit vider ce qu'il a affiché : c'est cet événement que
    l'API traduira en `section_restart` au plan 4.
    """

    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class StreamDone:
    """Fin normale d'un flux, avec le coût constaté."""

    provider: str
    model: str
    tokens: int


StreamEvent = TextDelta | StreamRestart | StreamDone
```

- [ ] **Étape 6 : écrire `app/llm/errors.py`**

```python
class LlmError(Exception):
    """Racine des erreurs de la couche modèles."""


class ModelUnavailable(LlmError):
    """Ce modèle-là est inutilisable : retiré, inconnu, ou sortie hors schéma.

    L'essai suivant se fait sur le modèle suivant du **même** fournisseur.
    Les paliers gratuits retirent des modèles sans prévenir ; changer de
    fournisseur pour cela abandonnerait les modèles encore valides du
    fournisseur courant.
    """

    def __init__(self, model: str, reason: str) -> None:
        super().__init__(f"modèle {model} inutilisable : {reason}")
        self.model = model
        self.reason = reason


class ProviderUnavailable(LlmError):
    """Le fournisseur entier refuse ou ne répond pas.

    L'essai suivant se fait sur le fournisseur suivant de la route. `issue`
    prend une des valeurs de la colonne `llm_usage.issue` — `quota`,
    `erreur`, `timeout` — et part telle quelle en base.
    """

    def __init__(self, provider: str, issue: str, reason: str) -> None:
        super().__init__(f"fournisseur {provider} indisponible ({issue}) : {reason}")
        self.provider = provider
        self.issue = issue
        self.reason = reason


class NoProviderAvailable(LlmError):
    """La route entière est épuisée.

    Rien n'est perdu : le point de reprise reste intact, le projet passe en
    `run_status = 'failed'` et l'utilisateur voit un bouton « Reprendre »
    (§5.3). `attempts` retient ce qui a été tenté et pourquoi chacun a
    échoué — sans cette liste, un échec de route ne se diagnostique pas.
    """

    def __init__(self, route: str, attempts: list[str]) -> None:
        detail = " ; ".join(attempts) if attempts else "aucun essai possible"
        super().__init__(f"route {route} épuisée après {len(attempts)} essais : {detail}")
        self.route = route
        self.attempts = attempts
```

- [ ] **Étape 7 : écrire `app/llm/tokens.py`**

```python
from collections.abc import Iterable
from math import ceil

from app.llm.types import Message

# Rapport caractères/jeton retenu pour le français. Les cinq fournisseurs
# n'ont pas le même tokeniseur ; aucun de leurs comptes exacts n'est juste
# pour les quatre autres, et les embarquer tous coûterait cinq dépendances
# pour une décision binaire. Le diviseur est volontairement bas : surestimer
# fait basculer un peu tôt, ce qui ne se voit pas ; sous-estimer coupe une
# rédaction au milieu du flux, ce qui se voit.
CHARS_PER_TOKEN = 3

# Chaque API rembale le contenu dans un objet avec son rôle. Le surcoût est
# petit mais il se multiplie par le nombre de messages d'un prompt de section.
_MESSAGE_OVERHEAD_CHARS = 4


def estimate_tokens(messages: Iterable[Message]) -> int:
    """Estimation haute du coût d'un ensemble de messages.

    Sert à décider d'une bascule avant l'appel, pas à facturer : le compte
    réel remonte ensuite du fournisseur quand il le publie.
    """
    return sum(
        ceil((len(message.content) + _MESSAGE_OVERHEAD_CHARS) / CHARS_PER_TOKEN)
        for message in messages
    )
```

- [ ] **Étape 8 : écrire `app/llm/providers.py`**

```python
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
        # Relevé à la main sur la clé du compte : toute la famille
        # `mistral-small*` — y compris `mistral-small-latest` et
        # `magistral-small-latest` — est exposée par `/v1/models` mais refuse
        # chaque appel en 429, dès le premier, sans rien avoir consommé. Les
        # trois ci-dessous répondent. L'ordre compte doublement : un 429 est
        # classé au niveau du fournisseur, donc un premier modèle qui refuse
        # toujours ferait sauter Mistral des deux routes où il figure, sans
        # qu'aucun modèle vivant ne soit jamais essayé.
        models=("open-mistral-nemo", "ministral-8b-latest", "ministral-3b-latest"),
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
```

- [ ] **Étape 9 : ajouter les cinq clés à `app/core/config.py`**

Dans la classe `Settings`, après `session_ttl_hours` :

```python
    # Paliers gratuits des cinq fournisseurs de modèles. Le nom d'attribut
    # donne la variable d'environnement en majuscules : `gemini_api_key` lit
    # `GEMINI_API_KEY`, conformément au §11 de la spec. Valeur vide par
    # défaut, ce qui vaut « non configuré » et fait sauter le fournisseur.
    gemini_api_key: str = ""
    mistral_ai_api_key: str = ""
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    groq_cloud_api_key: str = ""
```

`CEREBRAS_CLOUD_API_KEY` n'est pas déclarée : `extra="ignore"` la laisse passer sans erreur, et son absence ici dit qu'elle n'est routée nulle part.

- [ ] **Étape 10 : neutraliser les vraies clés dans `tests/conftest.py`**

Juste après le bloc d'affectation des variables `SUPABASE_DB_*` :

```python
# Les clés des fournisseurs de modèles subissent le même traitement, pour la
# même raison : le `.env` en contient de vraies. Aucun test de la suite
# ordinaire ne joint un fournisseur, mais une valeur fixe rend aussi les
# assertions déterministes — sans elle, « ce fournisseur est configuré »
# dépendrait du poste sur lequel la suite tourne.
#
# L'exception est la campagne marquée `network`, qui vérifie à la demande que
# les URL de base et les noms de modèles sont encore valides. Elle réclame
# les vraies clés et se lance explicitement :
#     ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network
if os.environ.get("ESQUISSE_NETWORK_TESTS") != "1":
    for _provider_key in (
        "GEMINI_API_KEY",
        "MISTRAL_AI_API_KEY",
        "OPENROUTER_API_KEY",
        "NVIDIA_API_KEY",
        "GROQ_CLOUD_API_KEY",
    ):
        os.environ[_provider_key] = "cle-de-test"
```

- [ ] **Étape 11 : déclarer les cinq clés côté production**

Sans elles, `is_configured` répondra « non » pour les cinq fournisseurs sur
Render et la première rédaction lèvera `NoProviderAvailable` — un échec muet
et parfaitement inutile, puisque les clés existent.

Dans `backend/render.yaml`, à la fin du bloc `envVars` du service
`esquisse-api` :

```yaml
      # Paliers gratuits des fournisseurs de modèles. `sync: false` veut dire
      # « saisie dans le tableau de bord, jamais dans le dépôt ».
      - key: GEMINI_API_KEY
        sync: false
      - key: MISTRAL_AI_API_KEY
        sync: false
      - key: OPENROUTER_API_KEY
        sync: false
      - key: NVIDIA_API_KEY
        sync: false
      - key: GROQ_CLOUD_API_KEY
        sync: false
      # Explicite plutôt qu'implicite : en production le modèle simulé doit
      # être éteint, et le lire dans le fichier vaut mieux que le déduire.
      - key: ESQUISSE_FAKE_LLM
        value: "false"
```

- [ ] **Étape 12 : corriger l'arborescence de la maquette**

`docs/mockup.html`, onglet Stack, bloc `<pre class="s-tree">` (vers la ligne
668) : l'arborescence date d'avant la restructuration. Elle montre `api/`,
un `agent/` qui contient `llm/` et `templates/`, et place `render.yaml` et
`docker-compose.yml` à la racine — trois choses fausses depuis la
restructuration. Remplacer le contenu du bloc par :

```
esquisse/
├── backend/                Backend FastAPI (Render)
│   ├── app/
│   │   ├── core/           Configuration, base, sécurité, garde-fous
│   │   ├── auth/           Inscription, connexion, jetons, contrôle d'activation
│   │   ├── projects/       Projets et cloisonnement par propriétaire
│   │   ├── llm/            Cinq fournisseurs gratuits, trois routes, repli
│   │   ├── agent/          Graphe principal, sous-graphe de section, outils
│   │   ├── templates/      Cahier des charges, business plan, catalogue de faits
│   │   └── export/         Modèle Word, graphiques, appel à Gotenberg
│   ├── migrations/         Alembic : schéma de la base Supabase
│   ├── tests/              Suite pytest, graphe avec modèle simulé
│   ├── pyproject.toml      Dépendances, verrouillées dans uv.lock
│   ├── Dockerfile          Image du service, uv sync --frozen
│   ├── docker-compose.yml  Base jetable et Gotenberg en local, uniquement
│   ├── render.yaml         Les deux services de production
│   └── .env.example        Variables attendues
├── web/                    Front Next.js (Vercel)
│   ├── app/                Projets, parcours guidé, rédaction, exports
│   └── components/         Cartes d'interaction, éditeur, mémoire du projet
├── evals/                  Jeux d'évaluation LangSmith
├── docs/                   Analyses, spec d'implémentation, plans, maquette
└── .github/workflows/      Intégration continue sur uv sync --frozen
```

`web/`, `evals/`, `agent/` et `export/` n'existent pas encore : c'est une
arborescence cible, et elle le restera jusqu'aux plans 3, 5 et 6. Ce qui
était faux, c'est le reste.

- [ ] **Étape 13 : documenter le déploiement dans le README**

`render.yaml` vit dans `backend/`, et Render cherche le Blueprint à la racine
du dépôt par défaut. Sans ce réglage, le déploiement échoue avec un message
qui ne dit pas pourquoi. Ajouter en fin de `README.md` :

```markdown
## Déploiement sur Render

Le Blueprint est `backend/render.yaml`, pas `render.yaml` : Render le cherche
à la racine par défaut, il faut donc renseigner **Blueprint Path** =
`backend/render.yaml` à la création du Blueprint.

Les chemins qu'il contient — `dockerfilePath`, `dockerContext` — restent
relatifs à la **racine du dépôt** et non au fichier : c'est pourquoi ils
commencent par `./backend/`.

Les variables marquées `sync: false` se saisissent dans le tableau de bord du
service. Aucun identifiant de production ne vit dans le dépôt.
```

- [ ] **Étape 14 : lancer la suite entière**

Run : `uv run pytest -v`
Attendu : les 59 tests du plan 1 passent toujours, plus ceux de
`test_tokens.py` et `test_providers.py`.

Vérifier aussi que la maquette s'ouvre sans dégât : `open docs/mockup.html`,
onglet Stack, l'arborescence s'affiche d'un bloc.

- [ ] **Étape 15 : commit**

```bash
git add backend/app/llm backend/app/core/config.py backend/tests/conftest.py \
        backend/tests/test_tokens.py backend/tests/test_providers.py \
        backend/render.yaml docs/mockup.html README.md
git commit -m "feat(llm): catalogue des fournisseurs, routes et vocabulaire de la couche modèles"
```

---

## Tâche 2 : les compteurs de quota

**Dispatchable en parallèle des tâches 3 et 4. Aucun fichier commun.**

**Fichiers :**
- Créer : `backend/app/llm/budget.py`
- Test : `backend/tests/test_budget.py`

**Interfaces :**
- Consomme (tâche 1) : `Provider`, `Limits` de `app.llm.providers`, `PROVIDERS`.
- Consomme (plan 1) : `app.core.db.connection`.
- Produit :
  - `async record_usage(conn, *, provider: str, model: str, route: str, project_id: UUID | None, tokens: int, issue: str) -> None`
  - `async budget_available(conn, provider: Provider, estimated_tokens: int) -> bool`
  - `class Pacer` avec `async wait() -> None`
  - `pacer_for(provider: Provider) -> Pacer | None`, `reset_pacers() -> None`

**Ce que la tâche décide.** La spec demande des fenêtres glissantes « minute, jour ». Deux choix s'y ajoutent, et ils sont le cœur de la tâche :

1. **Une bascule préventive n'écrit aucune ligne.** Elle n'a rien consommé ; une ligne à zéro requête fausserait la fenêtre autant qu'une ligne manquante. `llm_usage` reste le registre des appels réellement émis.
2. **La limite par seconde de Mistral ne passe pas par la base.** L'aller-retour SQL dure lui-même quelques millisecondes et deux tâches concurrentes liraient le même compteur avant que l'une ait écrit. L'espacement se tient en mémoire du processus, sous verrou — correct tant qu'il n'y a qu'une instance, ce qui est le cas sur l'hébergement gratuit (§9.2).

- [ ] **Étape 1 : écrire les tests**

`backend/tests/test_budget.py` :

```python
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


async def test_a_refused_budget_writes_nothing():
    # La première des deux décisions de cette tâche, et la seule chose qui
    # l'empêche de se perdre : une bascule préventive n'a rien consommé, donc
    # elle n'écrit pas. Sans ce test, un `insert` glissé un jour dans
    # `budget_available` ne ferait échouer aucune assertion.
    await _seed("gemini", rows=15)
    async with connection() as conn:
        assert not await budget_available(conn, PROVIDERS["gemini"], 1_000)
        assert await budget_available(conn, PROVIDERS["groq"], 1_000)
        async with conn.cursor() as cur:
            await cur.execute("select count(*) from llm_usage")
            assert (await cur.fetchone())[0] == 15


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
```

- [ ] **Étape 2 : lancer et vérifier l'échec**

Run : `uv run pytest tests/test_budget.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.llm.budget'`.

- [ ] **Étape 3 : écrire `app/llm/budget.py`**

```python
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
```

- [ ] **Étape 4 : lancer et vérifier le succès**

Run : `uv run pytest tests/test_budget.py -v`
Attendu : tous verts. Le conteneur `esquisse-db-1` doit tourner (`docker compose up -d` depuis `backend/`).

- [ ] **Étape 5 : commit**

```bash
git add backend/app/llm/budget.py backend/tests/test_budget.py
git commit -m "feat(llm): fenêtres glissantes de quota et espacement par seconde"
```

---

## Tâche 3 : le modèle simulé

**Dispatchable en parallèle des tâches 2 et 4. Aucun fichier commun.**

**Fichiers :**
- Créer : `backend/app/llm/fake.py`
- Test : `backend/tests/test_fake.py`

**Interfaces :**
- Consomme (tâche 1) : `Message`, `Completion` de `app.llm.types` ; `estimate_tokens` de `app.llm.tokens` ; `Provider` de `app.llm.providers`.
- Produit :
  - `FAKE_PROVIDER = "fake"`
  - `class FakeUnsupportedType(Exception)`
  - `class FakeTransport` avec `async chat(provider, model, messages, *, schema=None) -> Completion` et `async stream_chat(provider, model, messages) -> AsyncIterator[str]` — **mêmes signatures que `app.llm.transport`**, c'est ce qui permet à la passerelle de substituer l'un à l'autre.

**Ce qu'on attend de lui.** Le plan 3 fera tourner le graphe entier — une trentaine de sections, soixante-dix appels — sans réseau ni quota. Deux exigences en découlent :

- **Déterminisme.** La réponse ne dépend que des messages et du nom du modèle. Deux exécutions sur la même idée produisent le même document, sinon aucun test de graphe n'est comparable d'un tour à l'autre.
- **Bruyant sur ce qu'il ne sait pas faire.** Un simulé qui rendrait silencieusement `None` pour un champ qu'il ne sait pas fabriquer ferait passer des tests de graphe sur des données que le vrai modèle ne produira jamais. Il lève `FakeUnsupportedType` en nommant le champ et son type.

- [ ] **Étape 1 : écrire les tests**

`backend/tests/test_fake.py` :

```python
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


async def test_the_stream_rebuilds_the_same_text():
    transport = FakeTransport()
    chunks = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert len(chunks) > 1
    assert all(chunks)
    rebuilt = "".join(chunks)
    again = [chunk async for chunk in transport.stream_chat(PROVIDER, MODEL, _messages())]
    assert "".join(again) == rebuilt
```

- [ ] **Étape 2 : lancer et vérifier l'échec**

Run : `uv run pytest tests/test_fake.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.llm.fake'`.

- [ ] **Étape 3 : écrire `app/llm/fake.py`**

```python
import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from enum import Enum
from types import UnionType
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel

from app.llm.providers import Provider
from app.llm.tokens import estimate_tokens
from app.llm.types import Completion, Message

# Les lignes de `llm_usage` écrites hors ligne portent ce nom : les compteurs
# des vrais fournisseurs restent intacts, et les dizaines d'appels d'une
# exécution de graphe ne consomment aucun budget réel.
FAKE_PROVIDER = "fake"

# Découpage du flux simulé. Assez fin pour que l'interface ait quelque chose
# à afficher progressivement, assez gros pour ne pas noyer les tests.
_CHUNK_CHARS = 24


class FakeUnsupportedType(Exception):
    """Le modèle simulé ne sait pas fabriquer de valeur pour ce champ.

    Volontairement bruyant. Un simulé qui inventerait `None` en silence
    ferait passer des tests de graphe sur des données que le vrai modèle ne
    produira jamais : le défaut ne se verrait qu'au premier appel réel.
    """


# Phrases de remplissage, en français et de longueur voisine : le simulé doit
# produire un texte plausible pour que les longueurs cibles des sections et
# les découpages en flux se testent sur quelque chose de réaliste.
_SENTENCES = (
    "L'atelier retient cette orientation pour la suite du projet.",
    "Le périmètre couvre les usages décrits par le client lors du cadrage.",
    "Cette hypothèse sera confirmée par les chiffres du marché visé.",
    "La contrainte principale reste le délai annoncé au comité de pilotage.",
    "Le dispositif s'appuie sur les moyens déjà en place chez l'agence.",
    "Un premier jalon permettra de vérifier l'adhésion des utilisateurs.",
    "Le budget proposé reste compatible avec l'enveloppe annuelle prévue.",
    "Les indicateurs de suivi seront relevés à chaque fin de mois.",
)


def _seed(messages: Sequence[Message], model: str) -> int:
    """Empreinte stable de la question. `sort_keys` et `ensure_ascii=False`
    figent la sérialisation : sans cela, la graine dépendrait de détails
    d'encodage et le déterminisme serait une illusion."""
    payload = json.dumps(
        {"messages": [[m.role, m.content] for m in messages], "model": model},
        sort_keys=True,
        ensure_ascii=False,
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _paragraph(seed: int, sentences: int) -> str:
    return " ".join(
        _SENTENCES[(seed >> (index * 5)) % len(_SENTENCES)] for index in range(sentences)
    )


def _value_for(annotation, seed: int, path: str):
    """Une valeur plausible pour une annotation de champ pydantic.

    L'ordre des tests compte : `Literal` et les unions se reconnaissent par
    leur origine, jamais par `issubclass`, qui lèverait sur un objet de
    typing. Et `bool` passe avant `int`, puisque `bool` est un sous-type
    d'`int` en Python.
    """
    origin = get_origin(annotation)

    if origin is Literal:
        return get_args(annotation)[0]

    if origin in (Union, UnionType):
        branches = [arg for arg in get_args(annotation) if arg is not type(None)]
        if not branches:
            raise FakeUnsupportedType(f"{path} : union sans branche exploitable")
        # On remplit toujours l'optionnel : un champ laissé à `None` ne teste
        # rien en aval, alors qu'une valeur présente traverse le graphe.
        return _value_for(branches[0], seed, path)

    if origin in (list, set, frozenset, tuple):
        arguments = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        item = arguments[0] if arguments else str
        return [_value_for(item, seed + index + 1, f"{path}[{index}]") for index in range(2)]

    if origin is dict:
        arguments = get_args(annotation)
        value_type = arguments[1] if len(arguments) == 2 else str
        return {"cle": _value_for(value_type, seed + 1, f"{path}[cle]")}

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return _object_for(annotation, seed, path)
        if issubclass(annotation, Enum):
            return list(annotation)[0].value
        if annotation is bool:
            return bool(seed % 2)
        if annotation is int:
            return 1_000 + seed % 99_000
        if annotation is float:
            return round(1_000 + seed % 99_000 + (seed % 100) / 100, 2)
        if annotation is str:
            return _SENTENCES[seed % len(_SENTENCES)]

    raise FakeUnsupportedType(
        f"{path} : le modèle simulé ne sait pas fabriquer un {annotation!r}. "
        "Ajouter le cas dans app/llm/fake.py plutôt que de contourner."
    )


def _object_for(schema: type[BaseModel], seed: int, path: str) -> dict:
    """Décale la graine par champ : sans cela, tous les champs de même type
    porteraient la même valeur et un test d'interversion passerait."""
    return {
        name: _value_for(field.annotation, seed + index + 1, f"{path}.{name}")
        for index, (name, field) in enumerate(schema.model_fields.items())
    }


class FakeTransport:
    """Transport hors ligne, interface identique à `app.llm.transport`.

    C'est le transport qui est remplacé, pas la passerelle : la sélection de
    route, l'ordre des modèles et l'écriture de `llm_usage` restent les mêmes
    chemins de code en développement et en production.
    """

    async def chat(
        self,
        provider: Provider,
        model: str,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
    ) -> Completion:
        seed = _seed(messages, model)
        if schema is None:
            text = _paragraph(seed, sentences=6)
            parsed = None
        else:
            payload = _object_for(schema, seed, schema.__name__)
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            parsed = schema.model_validate(payload)
        tokens = estimate_tokens(messages) + estimate_tokens([Message("assistant", text)])
        return Completion(
            text=text, provider=FAKE_PROVIDER, model=model, tokens=tokens, parsed=parsed
        )

    async def stream_chat(
        self, provider: Provider, model: str, messages: Sequence[Message]
    ) -> AsyncIterator[str]:
        """Douze phrases : une section de la vraie longueur cible passerait
        mal en test, mais un flux d'un seul fragment ne vérifierait pas
        grand-chose du réassemblage."""
        text = _paragraph(_seed(messages, model), sentences=12)
        for start in range(0, len(text), _CHUNK_CHARS):
            yield text[start : start + _CHUNK_CHARS]
```

- [ ] **Étape 4 : lancer et vérifier le succès**

Run : `uv run pytest tests/test_fake.py -v`
Attendu : tous verts.

- [ ] **Étape 5 : commit**

```bash
git add backend/app/llm/fake.py backend/tests/test_fake.py
git commit -m "feat(llm): modèle simulé déterministe pour le graphe hors ligne"
```

---

## Tâche 4 : le transport compatible OpenAI

**Dispatchable en parallèle des tâches 2 et 3. Aucun fichier commun.**

**Fichiers :**
- Créer : `backend/app/llm/transport.py`, `backend/tests/test_transport.py`, `backend/tests/test_network_providers.py`
- Modifier : `backend/pyproject.toml` (dépendance `openai`, marqueur `network`), `backend/uv.lock` (produit par `uv add`), `backend/app/main.py` (fermeture des clients au cycle de vie)

**Interfaces :**
- Consomme (tâche 1) : `Provider`, `api_key_for`, `PROVIDERS` ; `ModelUnavailable`, `ProviderUnavailable` ; `estimate_tokens` ; `Message`, `Completion`.
- Produit :
  - `REQUEST_TIMEOUT_SECONDS = 60.0`, `STREAM_TIMEOUT_SECONDS = 180.0`
  - `client_for(provider, *, http_client=None) -> AsyncOpenAI` — mémoïsé par fournisseur
  - `async close_clients() -> None`
  - `async chat(provider, model, messages, *, schema=None, http_client=None) -> Completion`
  - `async stream_chat(provider, model, messages, *, http_client=None) -> AsyncIterator[str]`

**Les cinq fournisseurs, une seule interface.** Vérifié pour chacun : Gemini expose `…/v1beta/openai/`, Mistral `api.mistral.ai/v1`, Groq `api.groq.com/openai/v1`, NVIDIA `integrate.api.nvidia.com/v1`, OpenRouter `openrouter.ai/api/v1`. Tous parlent *Chat Completions*. Un adaptateur, cinq URL de base.

**Quatre décisions à porter dans le code, avec leur raison :**

1. **Un client par fournisseur, mémoïsé, fermé au cycle de vie.** Un client neuf par appel rouvrirait une connexion TLS à chaque fois — une soixantaine de poignées de main par projet — et laisserait derrière lui un pool de connexions que personne ne ferme. C'est le même raisonnement que `app.core.db.pool()`, et la même forme. Conséquence : le délai ne vit plus dans le client mais sur chaque appel, les deux usages n'ayant pas la même patience.

2. **`max_retries=0`.** Par défaut le client `openai` réessaie un 429 tout seul. Il brûlerait le quota que la bascule cherche à préserver, et masquerait au passage l'information dont la passerelle a besoin pour changer de fournisseur.

3. **Un 400, un 404 ou un 410 accuse le modèle, pas le fournisseur.** Le pseudo-code du §5.3 range tous les échecs au niveau du fournisseur. C'est trop grossier : un modèle gratuit retiré du catalogue — le cas explicitement prévu dans les parades — répond 404 ou 410, et basculer de fournisseur abandonnerait les modèles suivants encore valides. 429 et 5xx restent au niveau du fournisseur.

   Le 410 vient de la campagne réseau, qui a trouvé `minimaxai/minimax-m3` répondant « Gone » : c'est littéralement « cette ressource a disparu définitivement », donc exactement le cas que cette règle existe pour traiter.


4. **Tout échec sort d'ici classé.** La passerelle ne sait agir que sur `ModelUnavailable` et `ProviderUnavailable` ; une exception d'une autre nature qui remonterait brute ne lui laisserait rien à quoi se raccrocher. Le flux se garde déjà des trames sans choix ; l'appel simple doit en faire autant, sinon un 200 au `choices` vide sort en `IndexError`.**Ce qu'on n'envoie pas.** Pas de `response_format={"type": "json_object"}`. Les cinq paliers gratuits ne le gèrent pas de la même façon et un refus se traduirait par un 400, c'est-à-dire un modèle déclaré mort à tort. Le plus petit dénominateur commun est le texte ; la consigne « réponds en JSON » vit dans le prompt et la validation de schéma rattrape le reste — c'est exactement ce que la spec appelle « sortie hors schéma → modèle suivant ».

**Les tests exercent le vrai client.** Un `MockTransport` est branché **sous** `AsyncOpenAI` : le découpage des flux, l'analyse des réponses et la classification des statuts passent par le code réel du SDK, pas par une imitation.

**Et il doit venir de la bonne bibliothèque.** `openai` 3.x s'appuie sur **`httpx2`**, pas sur le `httpx` 0.x que la suite utilise par ailleurs pour le transport ASGI de FastAPI. Les deux cohabitent dans le verrou, et le SDK accepte sans broncher un client `httpx` 0.x qu'on lui injecte — ce qui ferait tester une pile HTTP que la production n'emprunte jamais. Le transport et ses tests utilisent donc `httpx2` ; `conftest.py` garde `httpx` pour l'ASGI, ce n'est pas le même usage.

- [ ] **Étape 1 : ajouter la dépendance et le marqueur**

```bash
cd backend && uv add openai
```

Puis dans `backend/pyproject.toml`, remplacer le bloc `[tool.pytest.ini_options]` par :

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "network: joint réellement les fournisseurs de modèles ; exclu par défaut",
]
# Les tests réseau consomment du quota et dépendent de la disponibilité de
# cinq services tiers : ils ne peuvent pas décider de la couleur de la suite.
# Ils se lancent à la demande, avec les vraies clés :
#     ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network
addopts = "-m 'not network'"
```

- [ ] **Étape 2 : écrire les tests**

`backend/tests/test_transport.py` :

```python
import json

import httpx2
import pytest
import pytest_asyncio
from pydantic import BaseModel

from app.llm.errors import ModelUnavailable, ProviderUnavailable
from app.llm.providers import PROVIDERS
from app.llm.transport import chat, client_for, close_clients, stream_chat
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


@pytest_asyncio.fixture(autouse=True)
async def _close_shared_clients():
    """Les clients partagés vivent dans le module : sans fermeture entre deux
    cas, un test en laisserait un ouvert au suivant et le processus finirait
    avec cinq pools de connexions inutiles."""
    yield
    await close_clients()


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


async def test_an_answer_without_choices_blames_the_model():
    # Un 200 avec une liste de choix vide arrive sur les paliers gratuits. Il
    # doit sortir classé comme tout le reste, pas en IndexError.
    handler = _replying(200, {
        "id": "cmpl-1", "object": "chat.completion", "created": 0,
        "model": MODEL, "choices": [],
    })
    with pytest.raises(ModelUnavailable):
        await chat(PROVIDER, MODEL, MESSAGES, http_client=_client(handler))


async def test_the_client_never_retries_on_its_own():
    # Un repli interne au SDK brûlerait le quota que la bascule préserve, et
    # cacherait à la passerelle l'information qui lui sert à décider.
    assert client_for(PROVIDER).max_retries == 0


async def test_the_same_provider_reuses_one_client():
    # Un client neuf par appel rouvrirait une connexion TLS à chaque fois et
    # laisserait un pool que personne ne ferme.
    assert client_for(PROVIDER) is client_for(PROVIDER)


async def test_an_injected_transport_is_never_shared():
    # Le client d'un test lui appartient : le mettre en cache le ferait fuiter
    # dans le cas suivant.
    handler = _replying(200, _answer("Une phrase."))
    assert client_for(PROVIDER, http_client=_client(handler)) is not client_for(PROVIDER)


async def test_every_base_url_is_carried_to_the_client():
    for provider in PROVIDERS.values():
        assert str(client_for(provider).base_url).startswith(
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
```

`backend/tests/test_network_providers.py` :

```python
"""Vérification à la demande des URL de base et des noms de modèles.

Rien d'autre ne peut dire qu'un modèle gratuit a disparu ou qu'une URL a
changé : ces deux choses bougent sans préavis et aucun test hors ligne ne
les voit. Exclu de la suite ordinaire — il consomme du quota et dépend de
cinq services tiers.

    ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network -v
"""
import pytest

from app.llm.providers import PROVIDERS, is_configured
from app.llm.transport import chat
from app.llm.types import Message

QUESTION = [Message("user", "Réponds exactement : OK")]


@pytest.mark.network
@pytest.mark.parametrize("name", sorted(PROVIDERS))
async def test_every_configured_model_still_answers(name):
    provider = PROVIDERS[name]
    if not is_configured(provider):
        pytest.skip(f"{name} : pas de clé dans l'environnement")
    failures = []
    for model in provider.models:
        try:
            completion = await chat(provider, model, QUESTION)
        except Exception as error:  # noqa: BLE001 — on veut le rapport complet
            failures.append(f"{model} : {error}")
            continue
        if not completion.text.strip():
            failures.append(f"{model} : réponse vide")
    assert not failures, f"{name} — modèles à revoir : " + " ; ".join(failures)
```

- [ ] **Étape 3 : lancer et vérifier l'échec**

Run : `uv run pytest tests/test_transport.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.llm.transport'`.

- [ ] **Étape 4 : écrire `app/llm/transport.py`**

```python
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
    Le 410 n'est pas théorique : la campagne réseau a trouvé
    `minimaxai/minimax-m3` répondant « Gone » alors que deux autres modèles
    NVIDIA marchaient.

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
```

- [ ] **Étape 5 : fermer les clients à l'arrêt de l'application**

Sans cela, les pools de connexions des cinq fournisseurs survivent au processus
qui les a ouverts. `backend/app/main.py` a déjà le point d'accroche : son
`lifespan` ferme le pool PostgreSQL dans un `finally`. Ajouter la fermeture des
clients dans le même `finally` :

```python
    try:
        yield
    finally:
        await close_clients()
        await connection_pool.close()
```

et l'import correspondant en tête de fichier :

```python
from app.llm.transport import close_clients
```

- [ ] **Étape 6 : lancer et vérifier le succès**

Run : `uv run pytest tests/test_transport.py -v`
Attendu : tous verts, `test_network_providers.py` non collecté (`addopts` l'exclut).

Vérifier aussi que la campagne réseau se lance bien, sans exiger qu'elle passe — des modèles gratuits peuvent avoir disparu, et c'est précisément ce qu'elle sert à découvrir :

Run : `ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network -v`
Attendu : les cinq cas sont collectés. **Reporter le résultat tel quel dans le compte rendu de tâche** — un modèle mort est une information pour le catalogue, pas un échec de la tâche.

- [ ] **Étape 7 : commit**

```bash
git add backend/app/llm/transport.py backend/app/main.py \
        backend/tests/test_transport.py backend/tests/test_network_providers.py \
        backend/pyproject.toml backend/uv.lock
git commit -m "feat(llm): adaptateur compatible OpenAI pour les cinq fournisseurs"
```

---

## Tâche 5 : la passerelle

**À dispatcher après les tâches 2, 3 et 4.**

**Fichiers :**
- Créer : `backend/app/llm/gateway.py`
- Test : `backend/tests/test_gateway.py`
- Modifier : `README.md` (section « La couche modèles »)

**Interfaces :**
- Consomme : tout ce que produisent les tâches 1 à 4.
- Produit :
  - `async complete(route, messages, *, project_id=None, schema=None, expected_output_tokens=1024, transport=None) -> Completion`
  - `async stream(route, messages, *, project_id=None, expected_output_tokens=4096, transport=None) -> AsyncIterator[StreamEvent]`

**L'ordre des essais (§5.3), avec les deux précisions apportées par les tâches précédentes :**

```
pour fournisseur dans route:
    pas de clé            → fournisseur suivant, sans écrire de ligne
    budget insuffisant    → fournisseur suivant, sans écrire de ligne
    pour modele dans fournisseur.modeles:
        espacer si le fournisseur limite par seconde
        essayer
        modèle mort ou hors schéma → ligne 'erreur', modèle suivant
        429                        → ligne 'quota',  fournisseur suivant
        5xx ou timeout             → ligne d'issue,  fournisseur suivant
        succès                     → ligne 'ok', rendre
tous épuisés → NoProviderAvailable(route, attempts)
```

**Le flux a une règle de plus.** Une rupture **avant le premier fragment** est un essai raté ordinaire : on suit l'ordre ci-dessus. Une rupture **après** un fragment déjà émis fait repartir la section entière sur le **fournisseur suivant** (§5.2) et émet un `StreamRestart` — le consommateur a du texte à l'écran, il doit le vider. C'est cet événement que le plan 4 traduira en `section_restart`.

**Le mode simulé remplace le transport, pas la passerelle.** Il saute les clés, le budget et l'espacement — soixante-dix appels hors ligne ne doivent consommer aucun quota réel — mais il traverse la même sélection de route, le même ordre de modèles et la même écriture de `llm_usage`, sous le nom de fournisseur `fake`.

- [ ] **Étape 1 : écrire les tests**

`backend/tests/test_gateway.py` :

```python
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.db import connection
from app.llm import gateway, providers as providers_module
from app.llm.budget import reset_pacers
from app.llm.errors import ModelUnavailable, NoProviderAvailable, ProviderUnavailable
from app.llm.gateway import complete, stream
from app.llm.providers import PROVIDERS
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
        ("mistral", "open-mistral-nemo"): ["Tout ", "depuis le début."],
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
        ("mistral", "open-mistral-nemo"): ["Une section."],
    })
    events = [event async for event in stream("redaction", MESSAGES, transport=stub)]
    assert not any(isinstance(e, StreamRestart) for e in events)
    assert events[-1].provider == "mistral"


async def test_a_broken_stream_records_what_was_already_emitted():
    stub = _StreamStub({
        ("gemini", "gemini-3.1-flash-lite"): [
            "Un début de section déjà affiché à l'écran.",
            ProviderUnavailable("gemini", "erreur", "flux rompu"),
        ],
        ("mistral", "open-mistral-nemo"): ["Tout depuis le début."],
    })
    [event async for event in stream("redaction", MESSAGES, transport=stub)]
    rows = await _usage_rows()
    assert rows[0][0] == "gemini"
    assert rows[0][4] == "erreur"
    assert rows[0][3] > 0  # les jetons consommés avant la rupture sont payés


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
```

- [ ] **Étape 2 : lancer et vérifier l'échec**

Run : `uv run pytest tests/test_gateway.py -v`
Attendu : ÉCHEC, `ModuleNotFoundError: No module named 'app.llm.gateway'`.

- [ ] **Étape 3 : écrire `app/llm/gateway.py`**

```python
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
                await _record(
                    route=route, provider=provider, model=model, project_id=project_id,
                    tokens=estimate_tokens([Message("assistant", written)]),
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
```

- [ ] **Étape 4 : lancer la suite entière**

Run : `uv run pytest -v`
Attendu : tous verts — les 59 tests du plan 1 et ceux des tâches 1 à 5.

- [ ] **Étape 5 : documenter la couche dans le README**

Ajouter une section « La couche modèles » après la section sur la configuration :

````markdown
## La couche modèles

Cinq fournisseurs gratuits, tous compatibles avec l'API Chat Completions
d'OpenAI : un seul adaptateur, cinq URL de base. Un appelant demande une
**capacité**, pas un fournisseur :

```python
from app.llm.gateway import complete, stream
from app.llm.types import Message

reponse = await complete("court", [Message("user", "…")], schema=MonSchema)
async for evenement in stream("redaction", messages, project_id=pid):
    ...
```

Les trois routes — `court`, `redaction`, `grand_contexte` — et les quotas de
chaque palier vivent dans `app/llm/providers.py`. Ce sont des réglages : les
offres gratuites bougent, et les quotas plus vite que le reste.

**Développer sans réseau.** `ESQUISSE_FAKE_LLM=true` dans le `.env` remplace
le transport par un modèle simulé déterministe. La sélection de route et
l'écriture de `llm_usage` restent les mêmes ; les lignes s'écrivent sous le
nom de fournisseur `fake`, sans toucher aux compteurs réels.

**Vérifier que les modèles existent encore.** Un modèle gratuit peut
disparaître sans préavis. La campagne réseau, exclue de la suite ordinaire,
interroge chaque modèle du catalogue :

```bash
ESQUISSE_NETWORK_TESTS=1 uv run pytest -m network -v
```
````

- [ ] **Étape 6 : commit**

```bash
git add backend/app/llm/gateway.py backend/tests/test_gateway.py README.md
git commit -m "feat(llm): passerelle de repli entre les cinq fournisseurs"
```

---

## Fin de plan

- [ ] Cocher le plan 2 dans [2026-09-17-feuille-de-route.md](2026-09-17-feuille-de-route.md), avec le nombre de tests.
- [ ] Reporter dans ce fichier, sous « Ce que l'exécution a appris », ce que la campagne réseau a révélé sur les noms de modèles.
- [ ] Fusionner `plan-03-couche-modeles` dans `main` en local.

## Ce que ce plan ne fait pas

- **Aucun prompt.** Les consignes de rédaction, les schémas de sortie et les grilles appartiennent au graphe, donc au plan 3. La couche modèles transporte des messages, elle n'en écrit pas.
- **Aucun classifieur d'injection.** `meta-llama/llama-prompt-guard-2-86m` filtre l'idée saisie **avant** qu'elle n'entre dans les prompts : sa place est en amont du graphe, pas dans le routage.
- **Aucune trace LangSmith.** `LANGSMITH_API_KEY` reste inutilisée ici ; l'instrumentation suit le graphe.
- **Aucun plafond par compte.** C'est une question ouverte du §12 de la spec, pas une tâche en attente.
