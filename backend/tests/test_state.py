import json

import pytest
from pydantic import ValidationError

from app.agent.state import (
    BulletList,
    Fact,
    Inconsistency,
    Paragraph,
    Placeholder,
    SectionRef,
    Table,
    dump_blocks,
    parse_blocks,
)


def _one_of_each():
    return [
        Paragraph(text="Le dispositif couvre les usages décrits au cadrage."),
        Table(
            number=2,
            title="Taille du marché adressable",
            columns=["Segment", "Volume", "Valeur"],
            rows=[["Particuliers", "12 000", "3,6 M€"]],
        ),
        BulletList(items=["Premier point", "Deuxième point"]),
        Placeholder(label="Donnée à compléter : source"),
    ]


def test_blocks_survive_a_round_trip_through_json():
    # `sections.contenu` est une colonne jsonb, et l'export Word du plan 5 part
    # de ces blocs. Un aller-retour qui perd le type rendrait le document
    # inexportable sans que rien ne le signale ici.
    blocks = _one_of_each()
    revived = parse_blocks(json.loads(json.dumps(dump_blocks(blocks))))
    assert revived == blocks


def test_every_block_declares_its_kind():
    assert [b.kind for b in _one_of_each()] == ["paragraph", "table", "list", "placeholder"]


def test_an_unknown_block_kind_is_refused():
    # Le modèle rend du JSON : un type inventé doit échouer à la validation,
    # pas se glisser dans la base et ressortir à l'export.
    with pytest.raises(ValidationError):
        parse_blocks([{"kind": "video", "url": "..."}])


def test_a_table_keeps_its_number_and_title():
    # Les templates l'exigent : « Tableau 2 : taille du marché adressable ».
    table = _one_of_each()[1]
    assert (table.number, table.title) == (2, "Taille du marché adressable")


def test_a_fact_accepts_none_as_a_value():
    # « Je ne sais pas » est une réponse, portée par value=None et source=user.
    fact = Fact(fact_id="budget_global", value=None, source="user")
    assert fact.value is None
    assert fact.source == "user"


def test_a_fact_refuses_an_unknown_source():
    with pytest.raises(ValidationError):
        Fact(fact_id="budget_global", value=1000, source="devine")


def test_a_section_ref_carries_its_document():
    ref = SectionRef(document="bp", section_id="marche_cible", order=3)
    assert (ref.document, ref.section_id, ref.order) == ("bp", "marche_cible", 3)


def test_an_inconsistency_names_the_sections_it_spans():
    written = Inconsistency(
        kind="chiffre divergent",
        description="Le prix unitaire diffère entre le modèle économique et le compte de résultat.",
        sections=["bp.modele_economique", "bp.compte_resultat"],
        proposal="Retenir 49 €, valeur du fait saisi.",
    )
    assert len(written.sections) == 2
