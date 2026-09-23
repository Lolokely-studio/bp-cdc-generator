import hashlib
import json
import re
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

# Les repères qu'un prompt de rédaction propose. Volontairement identique à
# l'expression de `app.agent.prompts`, et non importée : le modèle simulé ne
# doit rien savoir de l'agent, il ne fait que lire son prompt comme un vrai
# modèle le ferait.
_OFFERED_TABLE = re.compile(r"\[Tableau:\s*([a-z0-9_]+)\]")

# Les identifiants de faits qu'un prompt propose, en tête de ligne : c'est le
# format commun à `questions_prompt` (« - prix_moyen_unite (Prix moyen…) »)
# et `extraction_prompt` (« - nom_projet (Nom du projet, type texte) »). Un
# vrai modèle recopierait l'identifiant qu'on lui montre dans le JSON qu'on
# lui demande ; un simulé qui l'ignorerait produirait un `fact_id` sans
# rapport avec ce qui a été demandé, et aucune réponse — même chiffrée — ne
# pourrait jamais être rattachée au bon fait.
_OFFERED_FACT = re.compile(r"^- ([a-z0-9_]+) \(", re.MULTILINE)

# Les sections qu'un prompt de cohérence présente, une par titre `### cdc.x`.
# Troisième cas où le simulé recopie ce que le prompt offre plutôt que
# d'inventer, pour la même raison que les deux autres : un vrai modèle nomme
# les sections qu'on lui a montrées.
_OFFERED_SECTION = re.compile(r"^### ((?:cdc|bp)\.[a-z0-9_]+)$", re.MULTILINE)
_SECTION_PATH = re.compile(r"\.sections\[\d+\]$")


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


def _value_for(
    annotation, seed: int, path: str, metadata=(),
    facts: tuple[str, ...] = (), sections: tuple[str, ...] = (),
):
    """Une valeur plausible pour une annotation de champ pydantic.

    L'ordre des tests compte : `Literal` et les unions se reconnaissent par
    leur origine, jamais par `issubclass`, qui lèverait sur un objet de
    typing. Et `bool` passe avant `int`, puisque `bool` est un sous-type
    d'`int` en Python.

    `facts` ne change la sortie qu'à deux endroits, et dans les deux cas
    parce que le prompt contient la réponse à recopier plutôt qu'à inventer —
    le raisonnement qui vaut déjà pour les repères de tableau dans
    `stream_chat` :
    - un champ nommé `fact_id` reçoit un identifiant offert ;
    - une liste dont le chemin finit par `.questions` prend la longueur du
      lot offert, voir le commentaire de la branche concernée plus bas.
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
        return _value_for(branches[0], seed, path, metadata, facts, sections)

    if origin in (list, set, frozenset, tuple):
        arguments = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        item = arguments[0] if arguments else str
        # Une liste de questions suit le nombre de faits que le prompt offre :
        # la consigne dit « sans en ajouter ni en retirer », et c'est ce qu'un
        # vrai modèle fait. Deux éléments quoi qu'il arrive tronquaient chaque
        # lot à deux, et la règle du lot devenait sans effet.
        #
        # Second et dernier cas où ce simulé regarde le nom d'un champ, après
        # `fact_id`. Les deux se justifient de la même façon : le prompt donne
        # la réponse à recopier, et un simulé qui l'ignore est moins fidèle
        # qu'un vrai modèle, pas plus.
        count = len(facts) if facts and path.endswith(".questions") else 2
        return [
            _value_for(item, seed + index + 1, f"{path}[{index}]", metadata, facts, sections)
            for index in range(count)
        ]

    if origin is dict:
        arguments = get_args(annotation)
        value_type = arguments[1] if len(arguments) == 2 else str
        return {"cle": _value_for(value_type, seed + 1, f"{path}[cle]", metadata,
                                  facts, sections)}

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return _object_for(annotation, seed, path, facts, sections)
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
            if facts and path.endswith(".fact_id"):
                return facts[seed % len(facts)]
            if sections and _SECTION_PATH.search(path):
                return sections[seed % len(sections)]
            return _SENTENCES[seed % len(_SENTENCES)]

    raise FakeUnsupportedType(
        f"{path} : le modèle simulé ne sait pas fabriquer un {annotation!r}. "
        "Ajouter le cas dans app/llm/fake.py plutôt que de contourner."
    )


def _object_for(
    schema: type[BaseModel], seed: int, path: str,
    facts: tuple[str, ...] = (), sections: tuple[str, ...] = (),
) -> dict:
    """Décale la graine par champ : sans cela, tous les champs de même type
    porteraient la même valeur et un test d'interversion passerait."""
    return {
        name: _value_for(
            field.annotation, seed + index + 1, f"{path}.{name}", field.metadata,
            facts, sections,
        )
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
            joined = "\n".join(m.content for m in messages)
            facts = tuple(_OFFERED_FACT.findall(joined))
            sections = tuple(_OFFERED_SECTION.findall(joined))
            payload = _object_for(schema, seed, schema.__name__, facts, sections)
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            parsed = schema.model_validate(payload)
        tokens = estimate_tokens(messages) + estimate_tokens([Message("assistant", text)])
        return Completion(
            text=text, provider=FAKE_PROVIDER, model=model, tokens=tokens, parsed=parsed
        )

    async def stream_chat(
        self, provider: Provider, model: str, messages: Sequence[Message]
    ) -> AsyncIterator[str]:
        """Douze phrases, et les repères de tableau que le prompt propose.

        Un simulé qui n'écrit que de la prose ne permet pas d'éprouver la
        seule consigne de format qu'un modèle puisse suivre mécaniquement :
        placer un repère plutôt que recopier des chiffres. Sans cela, aucune
        exécution hors ligne ne fait jamais apparaître un tableau, et la
        chaîne qui va du fait chiffré au bloc `Table` reste sans test.

        Les repères sont relevés dans le prompt, jamais inventés : c'est
        exactement ce qu'on attend d'un vrai modèle.
        """
        text = _paragraph(_seed(messages, model), sentences=12)
        markers = _OFFERED_TABLE.findall("\n".join(m.content for m in messages))
        if markers:
            text += "\n\n" + "\n\n".join(f"[Tableau: {name}]" for name in markers)
        for start in range(0, len(text), _CHUNK_CHARS):
            yield text[start : start + _CHUNK_CHARS]
