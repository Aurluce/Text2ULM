"""Fonctions utilitaires partagées : normalisation de noms, identifiants PlantUML, cardinalités."""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Set

# Mots que PlantUML interprète comme de la syntaxe : on évite de les utiliser comme identifiants.
_RESERVED = {
    "start", "stop", "end", "if", "else", "elseif", "endif", "while", "endwhile", "fork", "again",
    "repeat", "state", "actor", "class", "abstract", "interface", "enum", "note", "title",
    "participant", "component", "database", "usecase", "package", "node", "cloud", "entity",
    "rectangle", "queue", "as", "of", "over", "legend", "skinparam", "hide", "show", "left",
    "right", "top", "bottom", "autonumber", "alt", "opt", "loop", "par", "break", "group", "box",
    "return", "activate", "deactivate", "create", "destroy", "namespace", "object", "artifact",
    "folder", "frame", "storage", "boundary", "control", "collections", "partition", "detach",
    "kill", "label", "map", "json", "together", "set", "url", "is", "then",
}


def strip_accents(text) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c))


def fold(text) -> str:
    """Forme comparable d'un nom : sans accents, en minuscules, lettres et chiffres seulement."""
    return re.sub(r"[^a-z0-9]+", "", strip_accents(text).lower())


def clean_text(text) -> str:
    """Remplace les retours à la ligne et espaces multiples par un seul espace."""
    return re.sub(r"\s+", " ", "" if text is None else str(text)).strip()


def slug(text) -> str:
    """Identifiant ASCII sûr pour PlantUML."""
    value = re.sub(r"[^A-Za-z0-9]+", "_", strip_accents(text)).strip("_") or "X"
    return "_" + value if value[0].isdigit() else value


class Namer:
    """Associe chaque nom affiché à un identifiant PlantUML ASCII, unique et stable."""

    def __init__(self) -> None:
        self._ids: Dict[str, str] = {}
        self._used: Set[str] = set()

    def __call__(self, name) -> str:
        key = fold(name) or str(name)
        if key in self._ids:
            return self._ids[key]
        base = slug(name)
        if base.lower() in _RESERVED:
            base += "_"
        candidate, n = base, 2
        while candidate.lower() in self._used:
            candidate = f"{base}_{n}"
            n += 1
        self._used.add(candidate.lower())
        self._ids[key] = candidate
        return candidate


_CARD_WORDS = {
    "un": "1", "une": "1", "one": "1", "unique": "1",
    "plusieurs": "*", "many": "*", "multiple": "*", "n": "*", "m": "*",
}


def normalize_cardinality(value, default: str = "") -> str:
    """Ramène « n », « 0..n », « plusieurs », « 1-3 »… vers une cardinalité UML standard."""
    v = clean_text(value).lower().replace(" ", "").replace("…", "..").replace("–", "-")
    if not v:
        return default
    if v in _CARD_WORDS:
        return _CARD_WORDS[v]
    v = re.sub(r"^(\d+)-(\d+|\*|n|m)$", r"\1..\2", v)
    v = re.sub(r"\.\.[nm]$", "..*", v)
    if v == "1..1":
        return "1"
    if re.fullmatch(r"\d+|\*|\d+\.\.(\d+|\*)", v):
        return v
    return default
