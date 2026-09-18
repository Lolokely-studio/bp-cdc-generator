import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from enum import Enum
from types import UnionType
from typing import Literal, Union, get_args, get_origin

from annotated_types import Ge, Gt, Le, Lt
from pydantic import BaseModel

from app.llm.providers import Provider
from app.llm.tokens import estimate_tokens
from app.llm.types import Completion, Message

# Les lignes de `llm_usage` écrites hors ligne portent ce nom : les compteurs
# des vrais fournisseurs restent intacts, et les dizaines d'appels d'une
# exécution de graphe ne consomment aucun budget réel.
FAKE_PROVIDER = "fake"

# Découpage du flux simulé. Assez fin pour que l'interface ait quelque chose
# à afficher progressivement, assez gros pour ne pas noyer les tests.
_CHUNK_CHARS = 24


class FakeUnsupportedType(Exception):
    """Le modèle simulé ne sait pas fabriquer de valeur pour ce champ.

    Volontairement bruyant. Un simulé qui inventerait `None` en silence
    ferait passer des tests de graphe sur des données que le vrai modèle ne
    produira jamais : le défaut ne se verrait qu'au premier appel réel.
    """


# Phrases de remplissage, en français et de longueur voisine : le simulé doit
# produire un texte plausible pour que les longueurs cibles des sections et
# les découpages en flux se testent sur quelque chose de réaliste.
_SENTENCES = (
    "L'atelier retient cette orientation pour la suite du projet.",
    "Le périmètre couvre les usages décrits par le client lors du cadrage.",
    "Cette hypothèse sera confirmée par les chiffres du marché visé.",
    "La contrainte principale reste le délai annoncé au comité de pilotage.",
    "Le dispositif s'appuie sur les moyens déjà en place chez l'agence.",
    "Un premier jalon permettra de vérifier l'adhésion des utilisateurs.",
    "Le budget proposé reste compatible avec l'enveloppe annuelle prévue.",
    "Les indicateurs de suivi seront relevés à chaque fin de mois.",
)


def _seed(messages: Sequence[Message], model: str) -> int:
    """Empreinte stable de la question. `sort_keys` et `ensure_ascii=False`
    figent la sérialisation : sans cela, la graine dépendrait de détails
    d'encodage et le déterminisme serait une illusion."""
    payload = json.dumps(
        {"messages": [[m.role, m.content] for m in messages], "model": model},
        sort_keys=True,
        ensure_ascii=False,
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _paragraph(seed: int, sentences: int) -> str:
    return " ".join(
        _SENTENCES[(seed >> (index * 5)) % len(_SENTENCES)] for index in range(sentences)
    )


def _bounds(metadata, low: float, high: float) -> tuple[float, float]:
    """Les bornes déclarées sur le champ, à défaut celles par défaut.

    pydantic range les contraintes dans `FieldInfo.metadata` sous la forme
    d'objets `annotated_types`. Les ignorer ferait produire au simulé des
    valeurs que le schéma refuse — et l'erreur sortirait du transport sans
    être classée.
    """
    for constraint in metadata:
        if isinstance(constraint, Ge):
            low = float(constraint.ge)
        elif isinstance(constraint, Gt):
            low = float(constraint.gt) + 1
        elif isinstance(constraint, Le):
            high = float(constraint.le)
        elif isinstance(constraint, Lt):
            high = float(constraint.lt) - 1
    return low, high


def _value_for(annotation, seed: int, path: str, metadata=()):
    """Une valeur plausible pour une annotation de champ pydantic.

    L'ordre des tests compte : `Literal` et les unions se reconnaissent par
    leur origine, jamais par `issubclass`, qui lèverait sur un objet de
    typing. Et `bool` passe avant `int`, puisque `bool` est un sous-type
    d'`int` en Python.
    """
    origin = get_origin(annotation)

    if origin is Literal:
        return get_args(annotation)[0]

    if origin in (Union, UnionType):
        branches = [arg for arg in get_args(annotation) if arg is not type(None)]
        if not branches:
            raise FakeUnsupportedType(f"{path} : union sans branche exploitable")
        # On remplit toujours l'optionnel : un champ laissé à `None` ne teste
        # rien en aval, alors qu'une valeur présente traverse le graphe.
        return _value_for(branches[0], seed, path, metadata)

    if origin in (list, set, frozenset, tuple):
        arguments = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        item = arguments[0] if arguments else str
        return [
            _value_for(item, seed + index + 1, f"{path}[{index}]", metadata)
            for index in range(2)
        ]

    if origin is dict:
        arguments = get_args(annotation)
        value_type = arguments[1] if len(arguments) == 2 else str
        return {"cle": _value_for(value_type, seed + 1, f"{path}[cle]", metadata)}

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return _object_for(annotation, seed, path)
        if issubclass(annotation, Enum):
            return list(annotation)[0].value
        if annotation is bool:
            return bool(seed % 2)
        if annotation is int:
            low, high = _bounds(metadata, 1_000, 100_000)
            return int(low) + seed % max(1, int(high) - int(low) + 1)
        if annotation is float:
            low, high = _bounds(metadata, 1_000.0, 100_000.0)
            return round(low + (seed % 10_000) / 10_000 * (high - low), 2)
        if annotation is str:
            return _SENTENCES[seed % len(_SENTENCES)]

    raise FakeUnsupportedType(
        f"{path} : le modèle simulé ne sait pas fabriquer un {annotation!r}. "
        "Ajouter le cas dans app/llm/fake.py plutôt que de contourner."
    )


def _object_for(schema: type[BaseModel], seed: int, path: str) -> dict:
    """Décale la graine par champ : sans cela, tous les champs de même type
    porteraient la même valeur et un test d'interversion passerait."""
    return {
        name: _value_for(field.annotation, seed + index + 1, f"{path}.{name}", field.metadata)
        for index, (name, field) in enumerate(schema.model_fields.items())
    }


class FakeTransport:
    """Transport hors ligne, interface identique à `app.llm.transport`.

    C'est le transport qui est remplacé, pas la passerelle : la sélection de
    route, l'ordre des modèles et l'écriture de `llm_usage` restent les mêmes
    chemins de code en développement et en production.
    """

    async def chat(
        self,
        provider: Provider,
        model: str,
        messages: Sequence[Message],
        *,
        schema: type[BaseModel] | None = None,
    ) -> Completion:
        seed = _seed(messages, model)
        if schema is None:
            text = _paragraph(seed, sentences=6)
            parsed = None
        else:
            payload = _object_for(schema, seed, schema.__name__)
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            parsed = schema.model_validate(payload)
        tokens = estimate_tokens(messages) + estimate_tokens([Message("assistant", text)])
        return Completion(
            text=text, provider=FAKE_PROVIDER, model=model, tokens=tokens, parsed=parsed
        )

    async def stream_chat(
        self, provider: Provider, model: str, messages: Sequence[Message]
    ) -> AsyncIterator[str]:
        """Douze phrases : une section de la vraie longueur cible passerait
        mal en test, mais un flux d'un seul fragment ne vérifierait pas
        grand-chose du réassemblage."""
        text = _paragraph(_seed(messages, model), sentences=12)
        for start in range(0, len(text), _CHUNK_CHARS):
            yield text[start : start + _CHUNK_CHARS]
