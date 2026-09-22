import base64
from html import escape

from app.agent.state import BulletList, Paragraph, Placeholder, Table
from app.export.charts import Chart
from app.export.document import ExportDocument
from app.export.word import DRAFT_NOTICE

_STYLE = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; }
h1.title { text-align: center; font-size: 22pt; }
p.draft { text-align: center; color: #b03030; }
h2 { font-size: 15pt; margin-top: 18pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th, td { border: 1px solid #555; padding: 3pt; text-align: left; }
p.caption { font-style: italic; }
"""


def render_html(document: ExportDocument, charts: list[Chart]) -> str:
    """Le même document que le Word, en HTML, pour le repli PDF.

    Tout texte passe par `escape` : c'est du texte rédigé par un modèle, et un
    chevron dedans ne doit jamais devenir une balise.
    """
    parts = [f"<html><head><meta charset='utf-8'><style>{_STYLE}</style>"
             f"</head><body>",
             f"<h1 class='title'>{escape(document.title)}</h1>"]
    if document.draft:
        parts.append(f"<p class='draft'>{escape(DRAFT_NOTICE)}</p>")

    for section in document.sections:
        parts.append(f"<h2>{escape(section.title)}</h2>")
        for block in section.blocks:
            if isinstance(block, Paragraph):
                parts.append(f"<p>{escape(block.text)}</p>")
            elif isinstance(block, Table):
                parts.append(f"<p class='caption'>Tableau {block.number} — "
                             f"{escape(block.title)}</p><table><tr>")
                parts.extend(f"<th>{escape(c)}</th>" for c in block.columns)
                parts.append("</tr>")
                for row in block.rows:
                    parts.append("<tr>" + "".join(
                        f"<td>{escape(v)}</td>" for v in row) + "</tr>")
                parts.append("</table>")
            elif isinstance(block, BulletList):
                parts.append("<ul>" + "".join(
                    f"<li>{escape(i)}</li>" for i in block.items) + "</ul>")
            elif isinstance(block, Placeholder):
                parts.append(f"<p>[Donnée à compléter : {escape(block.label)}]</p>")

    if charts:
        parts.append("<h2>Graphiques</h2>")
        for chart in charts:
            encoded = base64.b64encode(chart.png).decode("ascii")
            parts.append(f"<p class='caption'>{escape(chart.title)}</p>"
                         f"<img src='data:image/png;base64,{encoded}' width='480'/>")

    if document.missing:
        parts.append("<h2>Données à compléter</h2><ul>" + "".join(
            f"<li>{escape(label)}</li>" for label in document.missing) + "</ul>")

    parts.append("</body></html>")
    return "".join(parts)
