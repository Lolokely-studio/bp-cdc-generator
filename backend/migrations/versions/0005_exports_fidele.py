"""un PDF dit s'il est fidèle au Word

Revision ID: 0005
Revises: 0004

Quand Gotenberg échoue, le PDF vient du repli HTML : il dit la même chose que
le Word sans lui ressembler. La spec veut que l'utilisateur le sache plutôt
qu'on le lui cache (§7). `true` par défaut : un Word est toujours fidèle à
lui-même, et un PDF converti par Gotenberg l'est aussi.
"""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        "alter table exports add column fidele boolean not null default true")


def downgrade() -> None:
    op.execute("alter table exports drop column fidele")
