"""un PDF dit s'il est fidèle au Word, et un fichier par document et format

Revision ID: 0005
Revises: 0004

Quand Gotenberg échoue, le PDF vient du repli HTML : il dit la même chose que
le Word sans lui ressembler. La spec veut que l'utilisateur le sache plutôt
qu'on le lui cache (§7). `true` par défaut : un Word est toujours fidèle à
lui-même, et un PDF converti par Gotenberg l'est aussi.

Réécrite par la relecture de la tâche 6, et non complétée par une 0006 :
cette migration n'a jamais touché la base réelle. Elle ajoute aussi l'index
unique qui manquait — le chemin de stockage suppose déjà un seul fichier par
document et par format, mais rien en base ne le garantissait.
"""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        "alter table exports add column fidele boolean not null default true")
    # Un fichier par document et par format : c'est ce que le chemin de
    # stockage suppose déjà. L'index le garantit en base, là où le registre
    # en mémoire ne voit qu'un processus.
    op.execute("create unique index exports_document_format_key "
               "on exports (project_id, document, format)")


def downgrade() -> None:
    # `if exists` : la première version de cette migration, sans index, a
    # déjà été appliquée à la base de test. La suite redescend les migrations
    # avec CE code avant de remonter, et ne doit pas buter sur un index qui
    # n'a jamais été créé.
    op.execute("drop index if exists exports_document_format_key")
    op.execute("alter table exports drop column fidele")
