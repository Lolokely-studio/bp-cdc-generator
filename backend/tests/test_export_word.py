import io

from docx import Document

from app.agent.state import BulletList, Paragraph, Placeholder, Table
from app.export.charts import Chart
from app.export.document import ExportDocument, ExportSection
from app.export.word import render_word


def _png():
    import matplotlib.pyplot as plt
    from app.export import charts  # impose le moteur Agg

    figure, axis = plt.subplots()
    axis.plot([1, 2])
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    return buffer.getvalue()


def _document(draft=False, missing=()):
    return ExportDocument(
        document="bp", title="Business plan — CoachDom", draft=draft,
        missing=list(missing),
        sections=[
            ExportSection("Résumé", [Paragraph(text="Un résumé clair.")]),
            ExportSection("Finances", [
                Table(number=1, title="Compte de résultat", columns=["Année", "CA"],
                      rows=[["1", "100 000,00 €"]]),
                BulletList(items=["premier point", "second point"]),
                Placeholder(label="taux d'emprunt"),
            ]),
        ],
    )


def _read(data: bytes) -> Document:
    return Document(io.BytesIO(data))


def test_the_word_file_carries_every_section_and_block():
    word = _read(render_word(_document(), []))
    text = "\n".join(p.text for p in word.paragraphs)
    assert "Business plan — CoachDom" in text
    assert "Résumé" in text and "Finances" in text
    assert "Un résumé clair." in text
    assert "premier point" in text
    assert len(word.tables) == 1
    assert word.tables[0].cell(1, 1).text == "100 000,00 €"


def test_tables_carry_their_document_number_in_the_caption():
    word = _read(render_word(_document(), []))
    captions = [p.text for p in word.paragraphs if p.text.startswith("Tableau ")]
    assert captions == ["Tableau 1 — Compte de résultat"]


def test_a_draft_says_so_and_a_final_document_does_not():
    draft = "\n".join(p.text for p in _read(render_word(_document(draft=True), [])).paragraphs)
    final = "\n".join(p.text for p in _read(render_word(_document(draft=False), [])).paragraphs)
    assert "Brouillon" in draft
    assert "Brouillon" not in final


def test_missing_data_are_gathered_in_an_appendix():
    word = _read(render_word(_document(missing=["taux d'emprunt"]), []))
    text = [p.text for p in word.paragraphs]
    assert "Données à compléter" in text
    assert "taux d'emprunt" in "\n".join(text)


def test_no_appendix_when_nothing_is_missing():
    word = _read(render_word(_document(missing=[]), []))
    assert "Données à compléter" not in [p.text for p in word.paragraphs]


def test_charts_are_embedded_as_images():
    word = _read(render_word(_document(), [Chart("Trésorerie", _png())]))
    assert len(word.inline_shapes) == 1


def test_no_template_tag_survives_the_rendering():
    """Une balise restée telle quelle est un modèle et un rendu qui ne se
    sont pas compris : on la verrait imprimée dans le document."""
    word = _read(render_word(_document(), []))
    text = "\n".join(p.text for p in word.paragraphs)
    footer = word.sections[0].footer.paragraphs[0].text
    assert "{{" not in text and "{{" not in footer


def test_a_project_name_with_xml_characters_renders():
    document = _document()
    document.title = "Business plan — Café & Associés <SARL>"
    word = _read(render_word(document, []))
    assert "Business plan — Café & Associés <SARL>" in [p.text for p in word.paragraphs]


def test_a_misspelled_template_tag_fails_loudly(tmp_path, monkeypatch):
    """Un modèle refait à la main avec `{{ titel }}` doit lever, pas rendre
    un titre vide."""
    import jinja2
    from docx import Document as NewDocument

    from app.export import word as word_module

    model = tmp_path / "model.docx"
    handmade = NewDocument()
    handmade.add_paragraph("{{ titel }}")
    handmade.add_paragraph("{{p body }}")
    handmade.save(model)
    monkeypatch.setattr(word_module, "MODEL", model)
    import pytest

    with pytest.raises(jinja2.UndefinedError):
        render_word(_document(), [])


def test_section_titles_are_first_level_headings():
    word = _read(render_word(_document(), []))
    styles = {p.text: p.style.name for p in word.paragraphs}
    assert styles["Résumé"] == "Heading 1"
    assert styles["Finances"] == "Heading 1"


def test_an_inline_placeholder_keeps_its_label():
    """Le libellé doit figurer dans le texte, là où la donnée manque, et pas
    seulement dans l'annexe : on vide l'annexe pour que le test ne puisse pas
    s'appuyer sur elle."""
    word = _read(render_word(_document(missing=[]), []))
    assert "[Donnée à compléter : taux d'emprunt]" in [p.text for p in word.paragraphs]


def test_charts_come_after_the_sections():
    word = _read(render_word(_document(), [Chart("Trésorerie", _png())]))
    texts = [p.text for p in word.paragraphs]
    assert texts.index("Graphiques") > texts.index("Finances")
