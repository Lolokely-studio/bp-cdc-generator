"""la clé primaire de `sections` porte le document

Revision ID: 0003
Revises: 0002

Trouvé en écrivant le test du filtre sur `document` de `mark_for_reopening` :
le test échouait parce que les deux sections fabriquées pour l'occasion ne
pouvaient pas coexister. La clé primaire était `(project_id, section_id)`,
sans le document.

Un projet « both » écrit les deux documents dans cette même table. Deux
sections portant le même identifiant dans le CDC et dans le BP s'écrasaient
donc l'une l'autre en silence, par l'`on conflict` de `save_section` — une
section entière perdue, sans erreur, sans trace.

Aucune collision n'existe aujourd'hui : les gabarits nomment `risques_cdc` et
`risques_bp` à part, manifestement à cause de cela. Mais cette discipline de
nommage n'était écrite nulle part et rien ne l'imposait. Ajouter un jour une
section `annexes` aux deux documents aurait suffi.

Le filtre sur `document` de `mark_for_reopening` prend aussi son sens ici :
sa docstring disait « s'en remettre au seul `section_id` marcherait
aujourd'hui par chance ». Avec cette clé, ce n'est plus de la chance.
"""
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("alter table sections drop constraint sections_pkey")
    op.execute(
        "alter table sections add constraint sections_pkey "
        "primary key (project_id, document, section_id)"
    )


def downgrade() -> None:
    # Le retour arrière n'est possible que s'il n'existe aucune collision —
    # sinon la contrainte plus étroite refuserait les lignes que la plus large
    # a permis d'écrire. On laisse PostgreSQL le dire plutôt que de supprimer
    # des données pour faire passer un `downgrade`.
    op.execute("alter table sections drop constraint sections_pkey")
    op.execute(
        "alter table sections add constraint sections_pkey "
        "primary key (project_id, section_id)"
    )
