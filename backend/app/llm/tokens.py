from collections.abc import Iterable
from math import ceil

from app.llm.types import Message

# Rapport caractères/jeton retenu pour le français. Les cinq fournisseurs
# n'ont pas le même tokeniseur ; aucun de leurs comptes exacts n'est juste
# pour les quatre autres, et les embarquer tous coûterait cinq dépendances
# pour une décision binaire. Le diviseur est volontairement bas : surestimer
# fait basculer un peu tôt, ce qui ne se voit pas ; sous-estimer coupe une
# rédaction au milieu du flux, ce qui se voit.
CHARS_PER_TOKEN = 3

# Chaque API rembale le contenu dans un objet avec son rôle. Le surcoût est
# petit mais il se multiplie par le nombre de messages d'un prompt de section.
_MESSAGE_OVERHEAD_CHARS = 4


def estimate_tokens(messages: Iterable[Message]) -> int:
    """Estimation haute du coût d'un ensemble de messages.

    Sert à décider d'une bascule avant l'appel, pas à facturer : le compte
    réel remonte ensuite du fournisseur quand il le publie.
    """
    return sum(
        ceil((len(message.content) + _MESSAGE_OVERHEAD_CHARS) / CHARS_PER_TOKEN)
        for message in messages
    )
