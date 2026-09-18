from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    """Un tour de conversation, dans la forme commune aux cinq fournisseurs."""

    role: Role
    content: str


@dataclass(frozen=True)
class Completion:
    """Réponse d'un appel non diffusé.

    `provider` et `model` disent qui a répondu : la spec demande que le
    modèle retenu soit noté sur la trace, parce qu'un modèle gratuit peut
    disparaître entre deux projets et qu'on veut savoir lequel a écrit quoi.
    `parsed` ne vaut `None` que si l'appel n'a demandé aucun schéma.
    """

    text: str
    provider: str
    model: str
    tokens: int
    parsed: object | None = None


@dataclass(frozen=True)
class TextDelta:
    """Un fragment de texte à afficher tel quel."""

    text: str


@dataclass(frozen=True)
class StreamRestart:
    """Le flux s'est rompu après avoir déjà émis du texte.

    La section repart entière sur le fournisseur suivant (§5.2). Le
    consommateur doit vider ce qu'il a affiché : c'est cet événement que
    l'API traduira en `section_restart` au plan 4.
    """

    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class StreamDone:
    """Fin normale d'un flux, avec le coût constaté."""

    provider: str
    model: str
    tokens: int


StreamEvent = TextDelta | StreamRestart | StreamDone
