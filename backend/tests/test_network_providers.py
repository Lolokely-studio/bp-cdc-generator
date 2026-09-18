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
