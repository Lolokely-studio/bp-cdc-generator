from app.agent.state import BulletList, Paragraph, Placeholder, Table
from app.agent.templates import load_catalogue
from app.export.document import assemble

CATALOGUE = load_catalogue()


def _table(number, title="T"):
    return Table(number=number, title=title, columns=["A"], rows=[["1"]])


def _rows(document, profil, blocks_for=None, skip=(), statut="done"):
    """Une ligne `sections` par section du plan, blocs fournis ou génériques."""
    plan = CATALOGUE.plan_for(document,
                              profil if document == "cdc" else None,
                              profil if document == "bp" else None)
    rows = []
    for ref in plan:
        if ref.section_id in skip:
            continue
        blocks = (blocks_for or {}).get(ref.section_id,
                                        [Paragraph(text=ref.section_id)])
        rows.append({"section_id": ref.section_id, "document": document,
                     "statut": statut, "blocks": blocks})
    return rows


def test_sections_follow_the_reading_order_not_the_writing_order():
    """Le résumé exécutif est écrit en dernier et se lit en premier. Trier
    sur `ordre` le mettrait à la fin du document."""
    doc = assemble("bp", "CoachDom", "banque", _rows("bp", "banque"), CATALOGUE)
    expected = [CATALOGUE.section(f"bp.{s.id}").titre
                for s in sorted(
                    (s for s in CATALOGUE.bp.sections if "banque" in s.profils),
                    key=lambda s: s.ordre_lecture)]
    assert [s.title for s in doc.sections] == expected
    # Le témoin qui rend ce test discriminant : les deux ordres divergent.
    by_writing = [CATALOGUE.section(f"bp.{r.section_id}").titre
                  for r in CATALOGUE.plan_for("bp", None, "banque")]
    assert by_writing != expected


def test_tables_are_numbered_across_the_whole_document():
    """Chaque section stockée repart à « Tableau 1 ». L'export numérote dans
    l'ordre du document, de 1 à N."""
    plan = CATALOGUE.plan_for("bp", None, "banque")
    first, second = plan[0].section_id, plan[1].section_id
    rows = _rows("bp", "banque", blocks_for={
        first: [_table(1), _table(2)],
        second: [_table(1)],
    })
    doc = assemble("bp", "CoachDom", "banque", rows, CATALOGUE)
    numbers = [b.number for s in doc.sections for b in s.blocks
               if isinstance(b, Table)]
    assert numbers == list(range(1, len(numbers) + 1))
    assert len(numbers) == 3


def test_the_stored_blocks_are_never_modified():
    """L'export lit, il n'écrit pas. Renuméroter en place modifierait les
    objets que l'appelant détient encore."""
    plan = CATALOGUE.plan_for("bp", None, "banque")
    original = _table(1)
    rows = _rows("bp", "banque", blocks_for={
        plan[0].section_id: [_table(1)],
        plan[1].section_id: [original],
    })
    assemble("bp", "CoachDom", "banque", rows, CATALOGUE)
    assert original.number == 1


def test_a_missing_section_makes_the_document_a_draft():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    rows = _rows("cdc", "consultation", skip={plan[2].section_id})
    doc = assemble("cdc", "CoachDom", "consultation", rows, CATALOGUE)
    assert doc.draft is True
    assert len(doc.sections) == len(plan) - 1


def test_a_section_not_done_makes_the_document_a_draft_and_stays_out():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    rows = _rows("cdc", "consultation")
    rows[0]["statut"] = "reopened"
    doc = assemble("cdc", "CoachDom", "consultation", rows, CATALOGUE)
    assert doc.draft is True
    assert CATALOGUE.section(f"cdc.{plan[0].section_id}").titre not in [
        s.title for s in doc.sections]


def test_a_complete_document_is_not_a_draft():
    doc = assemble("cdc", "CoachDom", "consultation",
                   _rows("cdc", "consultation"), CATALOGUE)
    assert doc.draft is False


def test_placeholders_are_gathered_once_in_order():
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    rows = _rows("cdc", "consultation", blocks_for={
        plan[0].section_id: [Placeholder(label="budget annuel"),
                             Paragraph(text="x"),
                             Placeholder(label="date de lancement")],
        plan[1].section_id: [Placeholder(label="budget annuel"),
                             BulletList(items=["a"])],
    })
    doc = assemble("cdc", "CoachDom", "consultation", rows, CATALOGUE)
    # « budget annuel » apparaît dans les deux sections : quel que soit leur
    # ordre de lecture, il est vu en premier, puis « date de lancement ». Une
    # annexe non dédoublonnée le porterait deux fois.
    assert doc.missing == ["budget annuel", "date de lancement"]


def test_the_title_names_the_project_and_the_document():
    doc = assemble("bp", "CoachDom", "banque", _rows("bp", "banque"), CATALOGUE)
    assert "CoachDom" in doc.title
