"""`idee` sur `projects`, pour reconstruire un état de départ sans elle

Revision ID: 0004
Revises: 0003

Trouvé par la revue finale du plan : un run qui échoue avant d'écrire son
premier point de reprise (un délai d'attente du pool, par exemple) ne
pouvait jamais repartir. `/resume` appelait alors `advance(..., None)`,
LangGraph répondait « Received no input for __start__ », et la ligne
repassait à `failed` avec `reprenable: true` — un `failed` présenté comme
reprenable qui se répète à chaque tentative. Il en va de même d'un
processus tué entre l'insertion de la ligne et le démarrage de la tâche :
la ligne reste `idle` pour toujours.

Le correctif fait reconstruire `initial_state` par `/resume` quand le point
de reprise est vide, depuis `documents`, les profils et l'idée de la ligne.
Les trois premiers y étaient déjà ; l'idée, elle, n'était passée qu'en
mémoire à `initial_state` au moment de la création, jamais stockée.

`idee` est nullable : les lignes déjà écrites n'ont pas d'idée à répartir,
et `/resume` refuse de repartir sur une idée vide plutôt que d'inventer un
état de départ tronqué — mieux vaut un projet ancien qui refuse la reprise
qu'un projet relancé sur rien.
"""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute("alter table projects add column idee text")


def downgrade() -> None:
    op.execute("alter table projects drop column idee")
