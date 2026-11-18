"""Modèles Pydantic : un modèle par type de diagramme.

Les validateurs « before » rendent l'analyse tolérante : le LLM peut renvoyer des
synonymes (« héritage », « generalization »…), des chaînes au lieu d'objets ou des
attributs sous forme de dictionnaires sans que la génération n'échoue.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from utils import clean_text, fold, normalize_cardinality


# --------------------------------------------------------------------------- #
# Outils de normalisation
# --------------------------------------------------------------------------- #
def _pick(value: Any, mapping: Dict[str, str], default: str) -> str:
    return mapping.get(fold(value), default)


def _opt_text(value: Any) -> Optional[str]:
    return clean_text(value) or None


def _text_list(value: Any) -> List[str]:
    """Liste de chaînes ; accepte aussi une chaîne seule ou des dictionnaires {name, type}."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    out: List[str] = []
    for item in value:
        if isinstance(item, dict):
            name = clean_text(item.get("name") or item.get("nom") or item.get("label") or item.get("value"))
            typ = clean_text(item.get("type") or item.get("datatype"))
            text = f"{name}: {typ}" if name and typ else name
        else:
            text = clean_text(item)
        if text:
            out.append(text)
    return out


def _named_list(value: Any) -> List[Any]:
    """Liste d'objets ; une simple chaîne devient {"name": chaîne}."""
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    return [{"name": v} if isinstance(v, str) else v for v in value]


class BaseDiagram(BaseModel):
    """Champs communs à tous les diagrammes."""

    model_config = ConfigDict(extra="ignore")

    # {champ attendu: (noms alternatifs que le LLM pourrait employer)}
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {}

    title: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _apply_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for target, names in cls.ALIASES.items():
            if target not in data:
                for name in names:
                    if name in data:
                        data[target] = data[name]
                        break
        return data

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v: Any) -> Optional[str]:
        return _opt_text(v)

    @field_validator("assumptions", mode="before")
    @classmethod
    def _assumptions(cls, v: Any) -> List[str]:
        return _text_list(v)


class _Edge(BaseModel):
    """Lien orienté source → cible (relation, transition, message…)."""

    model_config = ConfigDict(extra="ignore")

    source: str = ""
    target: str = ""

    @model_validator(mode="before")
    @classmethod
    def _edge_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for std, alts in (("source", ("from", "src", "origine")), ("target", ("to", "dst", "destination"))):
            if std not in data:
                for alt in alts:
                    if alt in data:
                        data[std] = data[alt]
                        break
        return data

    @field_validator("source", "target", mode="before")
    @classmethod
    def _endpoint(cls, v: Any) -> str:
        return clean_text(v)


# --------------------------------------------------------------------------- #
# 1. Diagramme de classes
# --------------------------------------------------------------------------- #
ClassKind = Literal["class", "abstract", "interface", "enumeration"]
RelationType = Literal["association", "inheritance", "composition", "aggregation", "dependency", "realization"]

_CLASS_KINDS = {
    "class": "class", "classe": "class",
    "abstract": "abstract", "abstraite": "abstract", "abstractclass": "abstract", "classeabstraite": "abstract",
    "interface": "interface",
    "enum": "enumeration", "enumeration": "enumeration", "enumere": "enumeration",
}
_RELATION_TYPES = {
    "association": "association", "assoc": "association",
    "inheritance": "inheritance", "heritage": "inheritance", "generalisation": "inheritance",
    "generalization": "inheritance", "extends": "inheritance", "herite": "inheritance",
    "composition": "composition",
    "aggregation": "aggregation", "agregation": "aggregation",
    "dependency": "dependency", "dependance": "dependency", "uses": "dependency", "usage": "dependency",
    "realization": "realization", "realisation": "realization", "implements": "realization",
    "implementation": "realization",
}


class UMLClass(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: ClassKind = "class"
    attributes: List[str] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return _pick(v, _CLASS_KINDS, "class")

    @field_validator("attributes", "methods", mode="before")
    @classmethod
    def _members(cls, v: Any) -> List[str]:
        return _text_list(v)


class UMLRelation(_Edge):
    """Pour l'héritage et la réalisation : source = classe enfant, target = parent / interface.
    Pour la composition et l'agrégation : source = le tout, target = la partie."""

    type: RelationType = "association"
    source_cardinality: str = ""
    target_cardinality: str = ""
    label: Optional[str] = None

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v: Any) -> str:
        return _pick(v, _RELATION_TYPES, "association")

    @field_validator("source_cardinality", "target_cardinality", mode="before")
    @classmethod
    def _card(cls, v: Any) -> str:
        return normalize_cardinality(v)

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> Optional[str]:
        return _opt_text(v)


class UMLModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "classes": ("entities", "entites", "classe"),
        "relations": ("relationships", "associations", "links", "liens"),
    }

    classes: List[UMLClass] = Field(default_factory=list)
    relations: List[UMLRelation] = Field(default_factory=list)

    @field_validator("classes", mode="before")
    @classmethod
    def _classes(cls, v: Any) -> List[Any]:
        return _named_list(v)


# --------------------------------------------------------------------------- #
# 2. Diagramme de cas d'utilisation
# --------------------------------------------------------------------------- #
_ACTOR_KINDS = {
    "human": "human", "humain": "human", "person": "human", "personne": "human", "primary": "human",
    "principal": "human", "user": "human", "utilisateur": "human",
    "system": "system", "systeme": "system", "external": "system", "externe": "system",
    "secondary": "system", "secondaire": "system", "service": "system",
}
_UC_RELATIONS = {
    "association": "association", "assoc": "association",
    "include": "include", "inclusion": "include", "inclut": "include", "includes": "include",
    "extend": "extend", "extension": "extend", "extends": "extend", "etend": "extend",
    "generalization": "generalization", "generalisation": "generalization", "heritage": "generalization",
    "inheritance": "generalization",
}


class Actor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: Literal["human", "system"] = "human"

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return _pick(v, _ACTOR_KINDS, "human")


class UseCase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return clean_text(v)


class UseCaseRelation(_Edge):
    """include : source = cas de base, target = cas inclus.
    extend : source = cas qui étend, target = cas de base. generalization : source = enfant."""

    type: Literal["association", "include", "extend", "generalization"] = "association"
    label: Optional[str] = None

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v: Any) -> str:
        return _pick(v, _UC_RELATIONS, "association")

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> Optional[str]:
        return _opt_text(v)


class UseCaseModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "use_cases": ("usecases", "cas_utilisation", "cas", "cases"),
        "actors": ("acteurs",),
        "relations": ("links", "liens", "relationships"),
    }

    system_name: str = "Système"
    actors: List[Actor] = Field(default_factory=list)
    use_cases: List[UseCase] = Field(default_factory=list)
    relations: List[UseCaseRelation] = Field(default_factory=list)

    @field_validator("system_name", mode="before")
    @classmethod
    def _system(cls, v: Any) -> str:
        return clean_text(v) or "Système"

    @field_validator("actors", "use_cases", mode="before")
    @classmethod
    def _named(cls, v: Any) -> List[Any]:
        return _named_list(v)


# --------------------------------------------------------------------------- #
# 3. Diagramme de séquence
# --------------------------------------------------------------------------- #
_PARTICIPANT_KINDS = {
    "actor": "actor", "acteur": "actor", "utilisateur": "actor", "user": "actor",
    "participant": "participant", "object": "participant", "objet": "participant",
    "service": "participant", "system": "participant", "systeme": "participant",
    "boundary": "boundary", "interface": "boundary", "ui": "boundary", "ihm": "boundary", "frontiere": "boundary",
    "control": "control", "controller": "control", "controleur": "control",
    "entity": "entity", "entite": "entity",
    "database": "database", "db": "database", "bdd": "database", "basededonnees": "database",
    "queue": "queue", "file": "queue", "messagequeue": "queue",
}
_STEP_KINDS = {
    "message": "message", "msg": "message", "call": "message",
    "groupstart": "group_start", "group": "group_start", "fragment": "group_start",
    "groupelse": "group_else", "else": "group_else", "and": "group_else", "sinon": "group_else",
    "groupend": "group_end", "end": "group_end", "endgroup": "group_end",
    "note": "note", "comment": "note",
}
_GROUP_TYPES = {
    "alt": "alt", "condition": "alt", "opt": "opt", "optionnel": "opt", "loop": "loop", "boucle": "loop",
    "par": "par", "parallele": "par", "break": "break",
}
_ARROWS = {
    "sync": "sync", "synchrone": "sync", "call": "sync", "appel": "sync",
    "async": "async", "asynchrone": "async", "asynchronous": "async",
    "return": "return", "retour": "return", "reponse": "return", "response": "return", "reply": "return",
}


class Participant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: Literal["actor", "participant", "boundary", "control", "entity", "database", "queue"] = "participant"

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return _pick(v, _PARTICIPANT_KINDS, "participant")


class SequenceStep(_Edge):
    """Un pas du scénario, dans l'ordre chronologique : message, fragment (alt/opt/loop/par) ou note."""

    kind: Literal["message", "group_start", "group_else", "group_end", "note"] = "message"
    label: str = ""
    arrow: Literal["sync", "async", "return"] = "sync"
    group_type: Literal["alt", "opt", "loop", "par", "break"] = "alt"

    @model_validator(mode="before")
    @classmethod
    def _normalize_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        raw = fold(data.get("kind") or data.get("type") or "message")
        if raw in _ARROWS and "arrow" not in data:
            data["arrow"] = raw
            raw = "message"
        if raw in _GROUP_TYPES:
            data["group_type"] = raw
            raw = "groupstart"
        data["kind"] = _STEP_KINDS.get(raw, "message")
        return data

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("arrow", mode="before")
    @classmethod
    def _arrow(cls, v: Any) -> str:
        return _pick(v, _ARROWS, "sync")

    @field_validator("group_type", mode="before")
    @classmethod
    def _group(cls, v: Any) -> str:
        return _pick(v, _GROUP_TYPES, "alt")


class SequenceModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "participants": ("lifelines", "objets", "acteurs"),
        "steps": ("messages", "interactions", "etapes"),
    }

    participants: List[Participant] = Field(default_factory=list)
    steps: List[SequenceStep] = Field(default_factory=list)

    @field_validator("participants", mode="before")
    @classmethod
    def _participants(cls, v: Any) -> List[Any]:
        return _named_list(v)


# --------------------------------------------------------------------------- #
# 4. Diagramme d'activité
# --------------------------------------------------------------------------- #
_ACTIVITY_KINDS = {
    "start": "start", "debut": "start", "initial": "start", "begin": "start",
    "action": "action", "activity": "action", "activite": "action", "task": "action", "tache": "action",
    "step": "action",
    "if": "if", "decision": "if", "condition": "if", "branch": "if",
    "else": "else", "sinon": "else",
    "endif": "endif", "merge": "endif", "fusion": "endif", "finsi": "endif",
    "while": "while", "loop": "while", "boucle": "while", "tantque": "while", "repeat": "while",
    "endwhile": "endwhile", "endloop": "endwhile", "fintantque": "endwhile", "finboucle": "endwhile",
    "fork": "fork", "parallel": "fork", "parallele": "fork",
    "forkagain": "fork_again", "parallelbranch": "fork_again", "branche": "fork_again",
    "endfork": "end_fork", "join": "end_fork", "synchro": "end_fork",
    "swimlane": "swimlane", "lane": "swimlane", "partition": "swimlane", "couloir": "swimlane",
    "acteur": "swimlane",
    "stop": "stop", "end": "stop", "fin": "stop", "final": "stop", "finish": "stop",
}


class ActivityStep(BaseModel):
    """Liste à plat avec marqueurs : if/else/endif, while/endwhile, fork/fork_again/end_fork."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal[
        "start", "action", "if", "else", "endif", "while", "endwhile",
        "fork", "fork_again", "end_fork", "swimlane", "stop",
    ] = "action"
    label: str = ""     # texte de l'action, condition du if/while, nom du couloir, étiquette du else/endwhile
    branch: str = ""    # étiquette de la branche « oui » (if/while)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return _pick(v, _ACTIVITY_KINDS, "action")

    @field_validator("label", "branch", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return clean_text(v)


class ActivityModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {"steps": ("activities", "etapes", "nodes", "actions")}

    steps: List[ActivityStep] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 5. Diagramme d'états
# --------------------------------------------------------------------------- #
class State(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""

    @field_validator("name", "description", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return clean_text(v)


class Transition(_Edge):
    """Utiliser « [*] » comme source pour l'état initial et comme cible pour l'état final."""

    event: str = ""
    guard: str = ""
    action: str = ""

    @field_validator("event", "guard", "action", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return clean_text(v)


class StateModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "states": ("etats",),
        "transitions": ("links", "liens", "edges"),
    }

    states: List[State] = Field(default_factory=list)
    transitions: List[Transition] = Field(default_factory=list)

    @field_validator("states", mode="before")
    @classmethod
    def _states(cls, v: Any) -> List[Any]:
        return _named_list(v)


# --------------------------------------------------------------------------- #
# 6. Diagramme de composants / architecture
# --------------------------------------------------------------------------- #
_COMPONENT_KINDS = {
    "component": "component", "composant": "component", "service": "component", "module": "component",
    "database": "database", "db": "database", "bdd": "database", "basededonnees": "database",
    "storage": "database",
    "node": "node", "serveur": "node", "server": "node", "device": "node", "appareil": "node",
    "machine": "node",
    "cloud": "cloud", "internet": "cloud", "nuage": "cloud",
    "queue": "queue", "file": "queue", "broker": "queue", "messagequeue": "queue",
    "interface": "interface",
    "actor": "actor", "acteur": "actor", "utilisateur": "actor", "user": "actor",
}
_LINK_STYLES = {
    "sync": "sync", "synchrone": "sync", "solid": "sync",
    "async": "async", "asynchrone": "async", "dashed": "async", "event": "async",
}


class Component(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: Literal["component", "database", "node", "cloud", "queue", "interface", "actor"] = "component"
    group: str = ""

    @field_validator("name", "group", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return _pick(v, _COMPONENT_KINDS, "component")


class ComponentLink(_Edge):
    label: str = ""
    style: Literal["sync", "async"] = "sync"

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("style", mode="before")
    @classmethod
    def _style(cls, v: Any) -> str:
        return _pick(v, _LINK_STYLES, "sync")


class ComponentModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "components": ("composants", "elements", "nodes"),
        "links": ("relations", "liens", "connections", "edges"),
    }

    components: List[Component] = Field(default_factory=list)
    links: List[ComponentLink] = Field(default_factory=list)

    @field_validator("components", mode="before")
    @classmethod
    def _components(cls, v: Any) -> List[Any]:
        return _named_list(v)


# --------------------------------------------------------------------------- #
# 7. Modèle entité-association (tables)
# --------------------------------------------------------------------------- #
_FLAGS = re.compile(r"\((.*?)\)\s*$")


def _parse_er_attribute(text: str) -> Dict[str, Any]:
    """« id: int (PK) » → {"name": "id", "type": "int", "primary_key": True}."""
    raw = clean_text(text)
    flags = ""
    match = _FLAGS.search(raw)
    if match:
        flags = match.group(1).lower()
        raw = raw[: match.start()].strip()
    name, _, typ = raw.partition(":")
    return {
        "name": clean_text(name),
        "type": clean_text(typ),
        "primary_key": "pk" in flags or "primary" in flags,
        "foreign_key": "fk" in flags or "foreign" in flags,
        "required": "not null" in flags or "required" in flags or "obligatoire" in flags,
    }


class ERAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str = ""
    primary_key: bool = False
    foreign_key: bool = False
    required: bool = False

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        if isinstance(data, str):
            return _parse_er_attribute(data)
        if isinstance(data, dict):
            data = dict(data)
            for std, alts in (("primary_key", ("pk", "primarykey")), ("foreign_key", ("fk", "foreignkey"))):
                if std not in data:
                    for alt in alts:
                        if alt in data:
                            data[std] = data[alt]
                            break
        return data

    @field_validator("name", "type", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return clean_text(v)


class EREntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    attributes: List[ERAttribute] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> str:
        return clean_text(v)

    @field_validator("attributes", mode="before")
    @classmethod
    def _attrs(cls, v: Any) -> List[Any]:
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        return list(v)


class ERRelation(_Edge):
    """Cardinalités : « 1 », « 0..1 », « * » (0..*) ou « 1..* »."""

    source_cardinality: str = "1"
    target_cardinality: str = "*"
    label: Optional[str] = None

    @field_validator("source_cardinality", mode="before")
    @classmethod
    def _src_card(cls, v: Any) -> str:
        return normalize_cardinality(v, "1")

    @field_validator("target_cardinality", mode="before")
    @classmethod
    def _tgt_card(cls, v: Any) -> str:
        return normalize_cardinality(v, "*")

    @field_validator("label", mode="before")
    @classmethod
    def _label(cls, v: Any) -> Optional[str]:
        return _opt_text(v)


class ERModel(BaseDiagram):
    ALIASES: ClassVar[Dict[str, Tuple[str, ...]]] = {
        "entities": ("tables", "entites", "classes"),
        "relations": ("relationships", "associations", "links", "liens"),
    }

    entities: List[EREntity] = Field(default_factory=list)
    relations: List[ERRelation] = Field(default_factory=list)

    @field_validator("entities", mode="before")
    @classmethod
    def _entities(cls, v: Any) -> List[Any]:
        return _named_list(v)
