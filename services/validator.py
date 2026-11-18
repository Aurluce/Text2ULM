"""Nettoyage et contrôle de cohérence des modèles produits par le LLM.

Chaque validateur renvoie un modèle propre et une liste d'alertes lisibles : ce qui a été
corrigé automatiquement (doublon fusionné, élément manquant ajouté, relation invalide retirée…).
"""
from __future__ import annotations

import difflib
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from models.uml_model import (
    Actor,
    ActivityModel,
    ActivityStep,
    BaseDiagram,
    Component,
    ComponentModel,
    ERAttribute,
    EREntity,
    ERModel,
    Participant,
    SequenceModel,
    SequenceStep,
    State,
    StateModel,
    UMLClass,
    UMLModel,
    UseCase,
    UseCaseModel,
)
from utils import clean_text, fold, normalize_cardinality


class ModelError(ValueError):
    """Le modèle ne contient aucun élément exploitable."""


# --------------------------------------------------------------------------- #
# Outils communs
# --------------------------------------------------------------------------- #
def _dedupe(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        key = fold(item) or item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


class Resolver:
    """Retrouve le nom canonique d'un élément, malgré la casse, les accents ou un pluriel."""

    def __init__(self, names: Iterable[str] = ()) -> None:
        self._names: Dict[str, str] = {}
        for name in names:
            self.add(name)

    def add(self, name: str) -> None:
        self._names.setdefault(fold(name) or name.lower(), name)

    def find(self, ref: str) -> Optional[str]:
        key = fold(ref)
        if not key:
            return None
        if key in self._names:
            return self._names[key]
        close = difflib.get_close_matches(key, list(self._names), n=1, cutoff=0.88)
        return self._names[close[0]] if close else None


def _reaches(graph: Dict[str, Set[str]], start: str, goal: str) -> bool:
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(graph.get(node, ()))
    return False


# --------------------------------------------------------------------------- #
# Diagramme de classes
# --------------------------------------------------------------------------- #
def _validate_class(model: UMLModel) -> Tuple[UMLModel, List[str]]:
    warnings: List[str] = []
    classes: Dict[str, UMLClass] = {}
    for c in model.classes:
        name = clean_text(c.name)
        key = fold(name)
        if not key:
            continue
        if key in classes:
            prev = classes[key]
            prev.attributes = _dedupe(prev.attributes + c.attributes)
            prev.methods = _dedupe(prev.methods + c.methods)
            warnings.append(f"Classe « {name} » définie plusieurs fois : définitions fusionnées.")
            continue
        classes[key] = UMLClass(name=name, kind=c.kind, attributes=_dedupe(c.attributes), methods=_dedupe(c.methods))
    if not classes:
        raise ModelError("Aucune classe détectée. Décrivez au moins une entité du système.")

    resolver = Resolver(c.name for c in classes.values())

    def ensure(ref: str) -> Optional[str]:
        found = resolver.find(ref)
        if found:
            return found
        name = clean_text(ref)
        if not fold(name):
            return None
        classes[fold(name)] = UMLClass(name=name)
        resolver.add(name)
        warnings.append(f"« {name} » est citée dans une relation sans être définie : classe vide ajoutée.")
        return name

    relations = []
    seen: Set[Tuple[str, str, str, str]] = set()
    parents: Dict[str, Set[str]] = {}
    linked: Set[str] = set()
    for r in model.relations:
        src, tgt = ensure(r.source), ensure(r.target)
        if not src or not tgt:
            warnings.append("Relation incomplète (source ou cible manquante) ignorée.")
            continue
        if src == tgt and r.type != "association" and r.type != "dependency":
            warnings.append(f"Relation « {r.type} » d'une classe sur elle-même (« {src} ») ignorée.")
            continue
        if r.type in ("inheritance", "realization"):
            if _reaches(parents, tgt, src):
                warnings.append(f"Héritage « {src} » → « {tgt} » ignoré : il créerait un cycle.")
                continue
            parents.setdefault(src, set()).add(tgt)
        has_cardinality = r.type in ("association", "composition", "aggregation")
        key = (src, tgt, r.type, fold(r.label or ""))
        if key in seen:
            warnings.append(f"Relation « {src} » → « {tgt} » en double : une seule conservée.")
            continue
        seen.add(key)
        linked.update((src, tgt))
        relations.append(r.model_copy(update={
            "source": src,
            "target": tgt,
            "source_cardinality": normalize_cardinality(r.source_cardinality) if has_cardinality else "",
            "target_cardinality": normalize_cardinality(r.target_cardinality) if has_cardinality else "",
        }))

    if len(classes) > 1:
        for c in classes.values():
            if c.name not in linked and c.kind != "enumeration":
                warnings.append(f"Classe « {c.name} » reliée à aucune autre classe.")
    cleaned = UMLModel(title=model.title, assumptions=_dedupe(model.assumptions),
                       classes=list(classes.values()), relations=relations)
    return cleaned, warnings


# --------------------------------------------------------------------------- #
# Modèle entité-association
# --------------------------------------------------------------------------- #
def _validate_er(model: ERModel) -> Tuple[ERModel, List[str]]:
    warnings: List[str] = []
    names: Dict[str, str] = {}
    attrs: Dict[str, Dict[str, ERAttribute]] = {}

    def add_entity(name: str) -> str:
        key = fold(name)
        names.setdefault(key, name)
        attrs.setdefault(key, {})
        return key

    for e in model.entities:
        name = clean_text(e.name)
        if not fold(name):
            continue
        if fold(name) in names:
            warnings.append(f"Entité « {name} » définie plusieurs fois : définitions fusionnées.")
        key = add_entity(name)
        for a in e.attributes:
            aname = clean_text(a.name)
            if fold(aname):
                attrs[key].setdefault(fold(aname), a.model_copy(update={"name": aname, "type": clean_text(a.type)}))
    if not names:
        raise ModelError("Aucune entité détectée. Décrivez au moins une table du système.")

    resolver = Resolver(names.values())

    def ensure(ref: str) -> Optional[str]:
        found = resolver.find(ref)
        if found:
            return found
        name = clean_text(ref)
        if not fold(name):
            return None
        add_entity(name)
        resolver.add(name)
        warnings.append(f"« {name} » est citée dans une relation sans être définie : entité vide ajoutée.")
        return name

    relations = []
    seen: Set[Tuple[str, str, str]] = set()
    for r in model.relations:
        src, tgt = ensure(r.source), ensure(r.target)
        if not src or not tgt:
            warnings.append("Relation incomplète (source ou cible manquante) ignorée.")
            continue
        key = (src, tgt, fold(r.label or ""))
        if key in seen:
            warnings.append(f"Relation « {src} » → « {tgt} » en double : une seule conservée.")
            continue
        seen.add(key)
        relations.append(r.model_copy(update={"source": src, "target": tgt}))

    entities = []
    for key, name in names.items():
        columns = list(attrs[key].values())
        if columns and not any(c.primary_key for c in columns):
            warnings.append(f"Table « {name} » sans clé primaire.")
        entities.append(EREntity(name=name, attributes=columns))
    return ERModel(title=model.title, assumptions=_dedupe(model.assumptions),
                   entities=entities, relations=relations), warnings


# --------------------------------------------------------------------------- #
# Cas d'utilisation
# --------------------------------------------------------------------------- #
def _validate_usecase(model: UseCaseModel) -> Tuple[UseCaseModel, List[str]]:
    warnings: List[str] = []
    actors: Dict[str, Actor] = {}
    use_cases: Dict[str, UseCase] = {}
    for a in model.actors:
        name = clean_text(a.name)
        if fold(name) and fold(name) not in actors:
            actors[fold(name)] = Actor(name=name, kind=a.kind)
    for u in model.use_cases:
        name = clean_text(u.name)
        key = fold(name)
        if not key or key in use_cases:
            continue
        if key in actors:
            warnings.append(f"« {name} » est à la fois acteur et cas d'utilisation : conservé comme acteur.")
            continue
        use_cases[key] = UseCase(name=name)
    if not use_cases:
        raise ModelError("Aucun cas d'utilisation détecté. Décrivez ce que les utilisateurs peuvent faire.")

    resolver = Resolver([a.name for a in actors.values()] + [u.name for u in use_cases.values()])

    def kind_of(name: str) -> str:
        return "actor" if fold(name) in actors else "usecase"

    relations = []
    seen: Set[Tuple[str, str, str]] = set()
    linked: Set[str] = set()
    for r in model.relations:
        src, tgt = resolver.find(r.source), resolver.find(r.target)
        if not src or not tgt:
            warnings.append(f"Relation « {r.source} » → « {r.target} » ignorée : élément non déclaré.")
            continue
        ks, kt = kind_of(src), kind_of(tgt)
        if r.type == "association":
            if ks == "usecase" and kt == "actor":
                src, tgt = tgt, src  # on range toujours acteur → cas d'utilisation
            elif ks == kt:
                warnings.append(f"Association « {src} » — « {tgt} » ignorée : elle doit relier un acteur à un cas d'utilisation.")
                continue
        elif r.type in ("include", "extend"):
            if ks != "usecase" or kt != "usecase":
                warnings.append(f"« {r.type} » entre « {src} » et « {tgt} » ignoré : il relie deux cas d'utilisation.")
                continue
        elif ks != kt:
            warnings.append(f"Généralisation « {src} » → « {tgt} » ignorée : les deux éléments doivent être de même nature.")
            continue
        if src == tgt:
            warnings.append(f"Relation de « {src} » sur lui-même ignorée.")
            continue
        key = (src, tgt, r.type)
        if key in seen:
            continue
        seen.add(key)
        linked.update((src, tgt))
        relations.append(r.model_copy(update={"source": src, "target": tgt}))

    for a in actors.values():
        if a.name not in linked:
            warnings.append(f"Acteur « {a.name} » relié à aucun cas d'utilisation.")
    for u in use_cases.values():
        if u.name not in linked:
            warnings.append(f"Cas d'utilisation « {u.name} » relié à aucun acteur.")
    cleaned = UseCaseModel(title=model.title, assumptions=_dedupe(model.assumptions), system_name=model.system_name,
                           actors=list(actors.values()), use_cases=list(use_cases.values()), relations=relations)
    return cleaned, warnings


# --------------------------------------------------------------------------- #
# Séquence
# --------------------------------------------------------------------------- #
def _validate_sequence(model: SequenceModel) -> Tuple[SequenceModel, List[str]]:
    warnings: List[str] = []
    participants: Dict[str, Participant] = {}
    for p in model.participants:
        name = clean_text(p.name)
        if fold(name) and fold(name) not in participants:
            participants[fold(name)] = Participant(name=name, kind=p.kind)
    resolver = Resolver(p.name for p in participants.values())

    def ensure(ref: str) -> Optional[str]:
        found = resolver.find(ref)
        if found:
            return found
        name = clean_text(ref)
        if not fold(name):
            return None
        participants[fold(name)] = Participant(name=name)
        resolver.add(name)
        warnings.append(f"Participant « {name} » utilisé sans être déclaré : ajouté automatiquement.")
        return name

    steps: List[SequenceStep] = []
    stack: List[str] = []
    messages = 0
    for s in model.steps:
        if s.kind == "message":
            src, tgt = ensure(s.source), ensure(s.target)
            if not src or not tgt:
                warnings.append(f"Message « {s.label or '…'} » ignoré : émetteur ou destinataire manquant.")
                continue
            messages += 1
            steps.append(s.model_copy(update={"source": src, "target": tgt}))
        elif s.kind == "group_start":
            stack.append(s.group_type)
            steps.append(s)
        elif s.kind == "group_else":
            if not stack or stack[-1] not in ("alt", "par"):
                warnings.append("Branche « sinon » hors d'un fragment alt/par : ignorée.")
                continue
            steps.append(s)
        elif s.kind == "group_end":
            if not stack:
                warnings.append("Fin de fragment sans début : ignorée.")
                continue
            stack.pop()
            steps.append(s)
        elif s.kind == "note":
            src = ensure(s.source) if s.source else None
            if not src or not s.label:
                warnings.append("Note sans participant ou sans texte : ignorée.")
                continue
            steps.append(s.model_copy(update={"source": src}))
    for _ in stack:
        steps.append(SequenceStep(kind="group_end"))
        warnings.append("Fragment non fermé : fermé automatiquement.")
    if messages == 0:
        raise ModelError("Aucun message détecté. Décrivez les échanges entre les participants.")
    return SequenceModel(title=model.title, assumptions=_dedupe(model.assumptions),
                         participants=list(participants.values()), steps=steps), warnings


# --------------------------------------------------------------------------- #
# Activité
# --------------------------------------------------------------------------- #
_CLOSERS = {"if": "endif", "while": "endwhile", "fork": "end_fork"}


def _validate_activity(model: ActivityModel) -> Tuple[ActivityModel, List[str]]:
    warnings: List[str] = []
    steps: List[ActivityStep] = []
    stack: List[Dict[str, object]] = []
    started = False
    for s in model.steps:
        k = s.kind
        if k == "start":
            if started:
                warnings.append("Second nœud de début ignoré.")
                continue
            started = True
        elif k in ("action", "if", "while") and not s.label:
            warnings.append(f"Étape « {k} » sans libellé ignorée.")
            continue
        elif k == "swimlane" and not s.label:
            continue
        if k in ("if", "while", "fork"):
            stack.append({"type": k, "else": False})
        elif k == "else":
            if not stack or stack[-1]["type"] != "if" or stack[-1]["else"]:
                warnings.append("« sinon » mal placé : ignoré.")
                continue
            stack[-1]["else"] = True
        elif k == "fork_again":
            if not stack or stack[-1]["type"] != "fork":
                warnings.append("Branche parallèle hors d'un fork : ignorée.")
                continue
        elif k in ("endif", "endwhile", "end_fork"):
            expected = [t for t, c in _CLOSERS.items() if c == k][0]
            if not stack or stack[-1]["type"] != expected:
                warnings.append(f"« {k} » sans bloc ouvert correspondant : ignoré.")
                continue
            stack.pop()
        steps.append(s)

    while stack:
        steps.append(ActivityStep(kind=_CLOSERS[str(stack.pop()["type"])]))
        warnings.append("Bloc (décision, boucle ou parallélisme) non fermé : fermé automatiquement.")
    if not any(s.kind == "action" for s in steps):
        raise ModelError("Aucune activité détectée. Décrivez les étapes du processus.")
    first = next(i for i, s in enumerate(steps) if s.kind != "swimlane")
    if steps[first].kind != "start":
        steps.insert(first, ActivityStep(kind="start"))
    if steps[-1].kind != "stop":
        steps.append(ActivityStep(kind="stop"))
    return ActivityModel(title=model.title, assumptions=_dedupe(model.assumptions), steps=steps), warnings


# --------------------------------------------------------------------------- #
# États
# --------------------------------------------------------------------------- #
def _is_pseudo(text: str, resolver: Resolver) -> bool:
    raw = clean_text(text).lower()
    if raw in ("[*]", "*"):
        return True
    if resolver.find(text):
        return False
    return fold(raw) in {
        "initial", "initialstate", "etatinitial", "start", "debut", "begin",
        "final", "finalstate", "etatfinal", "end", "fin", "stop",
    }


def _validate_state(model: StateModel) -> Tuple[StateModel, List[str]]:
    warnings: List[str] = []
    states: Dict[str, State] = {}
    for s in model.states:
        name = clean_text(s.name)
        if fold(name) and fold(name) not in states:
            states[fold(name)] = State(name=name, description=s.description)
    resolver = Resolver(s.name for s in states.values())
    if not states and not model.transitions:
        raise ModelError("Aucun état détecté. Décrivez les états de l'objet et ses transitions.")

    def ensure(ref: str) -> Optional[str]:
        found = resolver.find(ref)
        if found:
            return found
        name = clean_text(ref)
        if not fold(name):
            return None
        states[fold(name)] = State(name=name)
        resolver.add(name)
        warnings.append(f"État « {name} » utilisé sans être déclaré : ajouté automatiquement.")
        return name

    transitions = []
    seen: Set[Tuple[str, str, str, str, str]] = set()
    for t in model.transitions:
        src = "[*]" if _is_pseudo(t.source, resolver) else ensure(t.source)
        tgt = "[*]" if _is_pseudo(t.target, resolver) else ensure(t.target)
        if not src or not tgt:
            warnings.append("Transition incomplète ignorée.")
            continue
        if src == "[*]" and tgt == "[*]":
            warnings.append("Transition de l'état initial vers l'état final ignorée.")
            continue
        key = (src, tgt, fold(t.event), fold(t.guard), fold(t.action))
        if key in seen:
            continue
        seen.add(key)
        transitions.append(t.model_copy(update={"source": src, "target": tgt}))
    if not transitions:
        raise ModelError("Aucune transition détectée. Décrivez comment l'objet change d'état.")

    if not any(t.source == "[*]" for t in transitions):
        warnings.append("Aucun état initial défini (transition depuis [*]).")
    else:
        reachable: Set[str] = set()
        frontier = [t.target for t in transitions if t.source == "[*]"]
        while frontier:
            node = frontier.pop()
            if node not in reachable:
                reachable.add(node)
                frontier.extend(t.target for t in transitions if t.source == node)
        for s in states.values():
            if s.name not in reachable:
                warnings.append(f"État « {s.name} » inaccessible depuis l'état initial.")
    return StateModel(title=model.title, assumptions=_dedupe(model.assumptions),
                      states=list(states.values()), transitions=transitions), warnings


# --------------------------------------------------------------------------- #
# Composants
# --------------------------------------------------------------------------- #
def _validate_component(model: ComponentModel) -> Tuple[ComponentModel, List[str]]:
    warnings: List[str] = []
    components: Dict[str, Component] = {}
    for c in model.components:
        name = clean_text(c.name)
        if fold(name) and fold(name) not in components:
            components[fold(name)] = Component(name=name, kind=c.kind, group=c.group)
    if not components:
        raise ModelError("Aucun composant détecté. Décrivez les éléments de l'architecture.")
    resolver = Resolver(c.name for c in components.values())

    def ensure(ref: str) -> Optional[str]:
        found = resolver.find(ref)
        if found:
            return found
        name = clean_text(ref)
        if not fold(name):
            return None
        components[fold(name)] = Component(name=name)
        resolver.add(name)
        warnings.append(f"Élément « {name} » utilisé dans un lien sans être déclaré : ajouté automatiquement.")
        return name

    links = []
    seen: Set[Tuple[str, str, str]] = set()
    linked: Set[str] = set()
    for l in model.links:
        src, tgt = ensure(l.source), ensure(l.target)
        if not src or not tgt:
            warnings.append("Lien incomplet ignoré.")
            continue
        key = (src, tgt, fold(l.label))
        if key in seen:
            continue
        seen.add(key)
        linked.update((src, tgt))
        links.append(l.model_copy(update={"source": src, "target": tgt}))
    if len(components) > 1:
        for c in components.values():
            if c.name not in linked:
                warnings.append(f"Élément « {c.name} » relié à aucun autre.")
    return ComponentModel(title=model.title, assumptions=_dedupe(model.assumptions),
                          components=list(components.values()), links=links), warnings


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
_DISPATCH: List[Tuple[type, Callable]] = [
    (UMLModel, _validate_class),
    (ERModel, _validate_er),
    (UseCaseModel, _validate_usecase),
    (SequenceModel, _validate_sequence),
    (ActivityModel, _validate_activity),
    (StateModel, _validate_state),
    (ComponentModel, _validate_component),
]


def validate_model(model: BaseDiagram) -> Tuple[BaseDiagram, List[str]]:
    """Nettoie le modèle et renvoie (modèle corrigé, alertes). Lève ModelError s'il est vide."""
    for cls, fn in _DISPATCH:
        if isinstance(model, cls):
            return fn(model)
    raise TypeError(f"Type de modèle non pris en charge : {type(model).__name__}")
