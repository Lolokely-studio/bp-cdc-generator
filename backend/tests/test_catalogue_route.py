import json

import pytest_asyncio

from app.agent.templates import load_catalogue
from tests.test_project_routes import _active_account


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "catalogue")


async def test_the_catalogue_requires_a_session(client):
    assert (await client.get("/catalogue")).status_code == 401


async def test_the_catalogue_carries_titles_profiles_and_fact_shapes(client, account):
    body = (await client.get("/catalogue", headers=account)).json()
    catalogue = load_catalogue()

    for document, template in (("cdc", catalogue.cdc), ("bp", catalogue.bp)):
        exposed = body["documents"][document]
        assert exposed["profils"] == dict(template.profils_disponibles)
        assert [s["id"] for s in exposed["sections"]] == [s.id for s in template.sections]
        assert [s["titre"] for s in exposed["sections"]] == [s.titre for s in template.sections]
        assert [s["profils"] for s in exposed["sections"]] == [s.profils for s in template.sections]

    assert set(body["faits"]) == set(catalogue.facts)
    choice = next(f for f in catalogue.facts.values() if f.type == "choix")
    assert body["faits"][choice.id] == {
        "libelle": choice.libelle, "type": "choix", "unite": choice.unite,
        "options": list(choice.options), "exemple": choice.exemple,
    }


async def test_the_catalogue_never_exposes_prompts(client, account):
    # `ensure_ascii=False` : sans lui, les accents sortent échappés et un
    # extrait de consigne en français ne serait jamais retrouvé, fuite ou non.
    text = json.dumps((await client.get("/catalogue", headers=account)).json(),
                      ensure_ascii=False)
    section = load_catalogue().cdc.sections[0]
    # Les clés entre guillemets : un titre comme « Contexte et objectifs »
    # contient le mot, pas la clé.
    for secret in ('"consignes"', '"grille"', '"objectif"', '"faits_requis"',
                   section.consignes[:40], section.objectif[:40]):
        assert secret not in text
