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
