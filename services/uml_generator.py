"""Génération du code PlantUML (7 types de diagrammes) et rendu PNG / SVG.

Rendu, par ordre de préférence :
  1. commande locale « plantuml » (ou PLANTUML_CMD) ;
  2. « java -jar plantuml.jar » (PLANTUML_JAR, ./plantuml.jar ou ./tools/plantuml.jar) ;
  3. serveur PlantUML public (désactivable avec ALLOW_ONLINE_RENDER=false) : le texte du
     diagramme est alors envoyé à ce serveur.
"""
from __future__ import annotations

import base64
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import config
from models.uml_model import (
    ActivityModel,
    BaseDiagram,
    ComponentModel,
    ERModel,
    SequenceModel,
    StateModel,
    UMLModel,
    UseCaseModel,
)
from utils import Namer, clean_text, slug

# --------------------------------------------------------------------------- #
# Options de style
# --------------------------------------------------------------------------- #
THEMES: Dict[str, str] = {
    "Classique": "",
    "Bleu": "cerulean",
    "Sobre (noir et blanc)": "plain",
    "Sombre": "cyborg",
    "Esquisse (dessiné à la main)": "sketchy-outline",
}
DIRECTIONS: Dict[str, str] = {
    "Vertical (haut → bas)": "top to bottom direction",
    "Horizontal (gauche → droite)": "left to right direction",
}
# Types pour lesquels une direction n'a pas de sens
_NO_DIRECTION = (SequenceModel, ActivityModel)


@dataclass
class RenderOptions:
    theme: str = "Classique"
    direction: str = "Vertical (haut → bas)"
    scale: float = 1.0          # facteur d'agrandissement de l'image PNG
    show_methods: bool = True   # diagramme de classes : afficher les méthodes


# --------------------------------------------------------------------------- #
# Aides de mise en forme
# --------------------------------------------------------------------------- #
def _q(text: str) -> str:
    """Texte sûr entre guillemets."""
    return clean_text(text).replace('"', "'")


def _member(text: str) -> str:
    """Ligne de membre : les accolades fermeraient le bloc de la classe."""
    return clean_text(text).replace("{", "(").replace("}", ")")


def _action_text(text: str) -> str:
    """Le point-virgule termine une action dans PlantUML."""
    return clean_text(text).replace(";", ",")


def _cond_text(text: str) -> str:
    """Les parenthèses délimitent une condition dans PlantUML."""
    return clean_text(text).replace("(", "[").replace(")", "]")


def _decl(keyword: str, name: str, ident: str, extra: str = "") -> str:
    head = f"{keyword} {ident}" if ident == name else f'{keyword} "{_q(name)}" as {ident}'
    return f"{head} {extra}".rstrip()


def _card(value: str) -> str:
    return f' "{value}"' if value else ""


def _label(text: Optional[str]) -> str:
    text = clean_text(text)
    return f" : {text}" if text else ""


# --------------------------------------------------------------------------- #
# Un constructeur par type de diagramme
# --------------------------------------------------------------------------- #
def _class_body(m: UMLModel, o: RenderOptions) -> List[str]:
    ids = Namer()
    keyword = {"class": "class", "abstract": "abstract class", "interface": "interface", "enumeration": "enum"}
    out = ["hide empty members"]
    for c in m.classes:
        head = _decl(keyword[c.kind], c.name, ids(c.name))
        members = [_member(a) for a in c.attributes]
        methods = [_member(x) for x in c.methods] if (o.show_methods and c.kind != "enumeration") else []
        if members or methods:
            out.append(head + " {")
            out += [f"  {x}" for x in members]
            if members and methods:
                out.append("  --")
            out += [f"  {x}" for x in methods]
            out.append("}")
        else:
            out.append(head)
    out.append("")
    arrows = {
        "inheritance": "--|>", "realization": "..|>", "composition": "*--",
        "aggregation": "o--", "association": "--", "dependency": "..>",
    }
    for r in m.relations:
        has_card = r.type in ("association", "composition", "aggregation")
        left = _card(r.source_cardinality) if has_card else ""
        right = _card(r.target_cardinality) if has_card else ""
        out.append(f"{ids(r.source)}{left} {arrows[r.type]}{right} {ids(r.target)}{_label(r.label)}")
    return out


_ER_LEFT = {"1": "||", "0..1": "|o", "*": "}o", "0..*": "}o", "1..*": "}|"}
_ER_RIGHT = {"1": "||", "0..1": "o|", "*": "o{", "0..*": "o{", "1..*": "|{"}


def _er_body(m: ERModel, o: RenderOptions) -> List[str]:
    ids = Namer()
    out = ["hide circle", "skinparam linetype ortho"]
    for e in m.entities:
        out.append(_decl("entity", e.name, ids(e.name), "{"))
        keys = [a for a in e.attributes if a.primary_key]
        others = [a for a in e.attributes if not a.primary_key]

        def line(a, mandatory: bool) -> str:
            flags = []
            if a.primary_key:
                flags.append("<<PK>>")
            if a.foreign_key:
                flags.append("<<FK>>")
            body = f"{_member(a.name)} : {_member(a.type)}" if a.type else _member(a.name)
            return "  " + ("* " if mandatory else "") + " ".join([body] + flags)

        out += [line(a, True) for a in keys]
        if keys and others:
            out.append("  --")
        out += [line(a, a.required) for a in others]
        out.append("}")
    out.append("")
    for r in m.relations:
        left = _ER_LEFT.get(r.source_cardinality, "||")
        right = _ER_RIGHT.get(r.target_cardinality, "o{")
        out.append(f"{ids(r.source)} {left}--{right} {ids(r.target)}{_label(r.label)}")
    return out


def _usecase_body(m: UseCaseModel, o: RenderOptions) -> List[str]:
    actors, cases = Namer(), Namer()
    out = []
    for a in m.actors:
        out.append(_decl("actor", a.name, actors(a.name), "#E8E8E8" if a.kind == "system" else ""))
    out.append(f'rectangle "{_q(m.system_name)}" {{')
    for u in m.use_cases:
        out.append("  " + _decl("usecase", u.name, cases(u.name)))
    out += ["}", ""]
    actor_names = {a.name for a in m.actors}

    def ident(name: str) -> str:
        return actors(name) if name in actor_names else cases(name)

    for r in m.relations:
        s, t = ident(r.source), ident(r.target)
        if r.type == "association":
            out.append(f"{s} --> {t}{_label(r.label)}")
        elif r.type == "include":
            out.append(f"{s} .> {t} : <<include>>")
        elif r.type == "extend":
            out.append(f"{s} .> {t} : <<extend>>")
        else:
            out.append(f"{s} --|> {t}")
    return out


def _sequence_body(m: SequenceModel, o: RenderOptions) -> List[str]:
    ids = Namer()
    out = ["autonumber", "skinparam maxMessageSize 180"]
    for p in m.participants:
        out.append(_decl(p.kind, p.name, ids(p.name)))
    out.append("")
    arrows = {"sync": "->", "async": "->>", "return": "-->"}
    indent = 0
    for s in m.steps:
        pad = "  " * indent
        if s.kind == "message":
            out.append(f"{pad}{ids(s.source)} {arrows[s.arrow]} {ids(s.target)}{_label(s.label)}")
        elif s.kind == "group_start":
            out.append(f"{pad}{s.group_type} {clean_text(s.label)}".rstrip())
            indent += 1
        elif s.kind == "group_else":
            out.append(f"{'  ' * max(indent - 1, 0)}else {clean_text(s.label)}".rstrip())
        elif s.kind == "group_end":
            indent = max(indent - 1, 0)
            out.append(f"{'  ' * indent}end")
        elif s.kind == "note":
            out.append(f"{pad}note over {ids(s.source)} : {clean_text(s.label)}")
    return out


def _activity_body(m: ActivityModel, o: RenderOptions) -> List[str]:
    out = []
    for s in m.steps:
        k = s.kind
        if k == "start":
            out.append("start")
        elif k == "stop":
            out.append("stop")
        elif k == "action":
            out.append(f":{_action_text(s.label)};")
        elif k == "swimlane":
            out.append(f"|{_action_text(s.label).replace('|', '/')}|")
        elif k == "if":
            out.append(f"if ({_cond_text(s.label)}) then ({_cond_text(s.branch) or 'oui'})")
        elif k == "else":
            out.append(f"else ({_cond_text(s.label) or 'non'})")
        elif k == "endif":
            out.append("endif")
        elif k == "while":
            out.append(f"while ({_cond_text(s.label)}) is ({_cond_text(s.branch) or 'oui'})")
        elif k == "endwhile":
            out.append(f"endwhile ({_cond_text(s.label) or 'non'})")
        elif k == "fork":
            out.append("fork")
        elif k == "fork_again":
            out.append("fork again")
        elif k == "end_fork":
            out.append("end fork")
    return out


def _state_body(m: StateModel, o: RenderOptions) -> List[str]:
    ids = Namer()
    out = []
    for s in m.states:
        out.append(_decl("state", s.name, ids(s.name)))
        if s.description:
            out.append(f"{ids(s.name)} : {clean_text(s.description)}")
    out.append("")
    for t in m.transitions:
        src = "[*]" if t.source == "[*]" else ids(t.source)
        tgt = "[*]" if t.target == "[*]" else ids(t.target)
        parts = [t.event, f"[{t.guard}]" if t.guard else "", f"/ {t.action}" if t.action else ""]
        out.append(f"{src} --> {tgt}{_label(' '.join(p for p in parts if p))}")
    return out


def _component_body(m: ComponentModel, o: RenderOptions) -> List[str]:
    ids = Namer()

    def decl(c) -> str:
        return _decl(c.kind, c.name, ids(c.name))

    out: List[str] = []
    groups: Dict[str, List] = {}
    for c in m.components:
        if c.group:
            groups.setdefault(c.group, []).append(c)
        else:
            out.append(decl(c))
    for name, members in groups.items():
        out.append(f'package "{_q(name)}" {{')
        out += [f"  {decl(c)}" for c in members]
        out.append("}")
    out.append("")
    for l in m.links:
        arrow = "..>" if l.style == "async" else "-->"
        out.append(f"{ids(l.source)} {arrow} {ids(l.target)}{_label(l.label)}")
    return out


_BUILDERS: List[tuple] = [
    (UMLModel, _class_body),
    (ERModel, _er_body),
    (UseCaseModel, _usecase_body),
    (SequenceModel, _sequence_body),
    (ActivityModel, _activity_body),
    (StateModel, _state_body),
    (ComponentModel, _component_body),
]


def generate_plantuml_code(model: BaseDiagram, options: Optional[RenderOptions] = None) -> str:
    """Construit le code source PlantUML du modèle."""
    options = options or RenderOptions()
    body: Optional[List[str]] = None
    for cls, builder in _BUILDERS:
        if isinstance(model, cls):
            body = builder(model, options)
            break
    if body is None:
        raise TypeError(f"Type de modèle non pris en charge : {type(model).__name__}")

    head = ["@startuml"]
    theme = THEMES.get(options.theme, "")
    if theme:
        head.append(f"!theme {theme}")
    if not isinstance(model, _NO_DIRECTION):
        head.append(DIRECTIONS.get(options.direction, "top to bottom direction"))
    head.append("skinparam shadowing false")
    head.append("skinparam defaultFontName SansSerif")
    head.append("skinparam roundCorner 8")
    if not isinstance(model, ERModel):
        head.append("skinparam classAttributeIconSize 0")
    if options.scale and options.scale != 1:
        head.append(f"scale {options.scale:g}")
    if model.title:
        head.append(f"title {clean_text(model.title)}")
    return "\n".join(head + [""] + body + ["", "@enduml"]) + "\n"


# --------------------------------------------------------------------------- #
# Rendu
# --------------------------------------------------------------------------- #
class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    code: str
    png: Optional[bytes] = None
    svg: Optional[bytes] = None
    engine: str = ""                      # « local », « java » ou « en ligne »
    error: Optional[str] = None
    files: Dict[str, Path] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.png is not None


def _local_command() -> Optional[List[str]]:
    """Commande locale pour lancer PlantUML, ou None."""
    if config.PLANTUML_CMD:
        return shlex.split(config.PLANTUML_CMD)
    exe = shutil.which("plantuml")
    if exe:
        return [exe]
    java = shutil.which("java")
    if not java:
        return None
    base = Path(config.BASE_DIR)
    for candidate in (config.PLANTUML_JAR, base / "plantuml.jar", base / "tools" / "plantuml.jar"):
        if candidate and Path(candidate).is_file():
            return [java, "-Djava.awt.headless=true", "-jar", str(candidate)]
    return None


def _run_local(cmd: List[str], code: str, fmt: str) -> bytes:
    try:
        proc = subprocess.run(
            cmd + ["-pipe", f"-t{fmt}", "-charset", "UTF-8", "-failfast2"],
            input=code.encode("utf-8"), capture_output=True, timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError("PlantUML a mis trop de temps à répondre.") from exc
    except OSError as exc:
        raise RenderError(f"Impossible de lancer PlantUML : {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace")
        lines = [l for l in detail.splitlines() if l.strip() and "JAVA_TOOL_OPTIONS" not in l]
        raise RenderError("Erreur PlantUML : " + " | ".join(lines[:4]) if lines else "PlantUML n'a rien produit.")
    return proc.stdout


_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_PUML = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def encode_for_server(code: str) -> str:
    """Encodage « deflate + base64 PlantUML » utilisé dans les URL du serveur."""
    packed = zlib.compress(code.encode("utf-8"), 9)[2:-4]
    return base64.b64encode(packed).decode("ascii").translate(str.maketrans(_B64, _PUML)).rstrip("=")


def _run_online(code: str, fmt: str) -> bytes:
    url = f"{config.PLANTUML_SERVER}/{fmt}/{encode_for_server(code)}"
    if len(url) > 7000:
        raise RenderError("Diagramme trop volumineux pour le serveur en ligne : installez PlantUML (Java) en local.")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Text2UML"}), timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        raise RenderError("Le serveur PlantUML a refusé le diagramme (erreur de syntaxe probable).") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RenderError(f"Serveur PlantUML injoignable : {exc}") from exc


def render(code: str) -> RenderResult:
    """Rend le code PlantUML en PNG et SVG. N'élève jamais : l'erreur est dans le résultat."""
    result = RenderResult(code=code)
    cmd = _local_command()
    runners: List[tuple] = []
    if cmd:
        runners.append(("local" if len(cmd) == 1 else "java", lambda fmt, c=cmd: _run_local(c, code, fmt)))
    if config.ALLOW_ONLINE_RENDER:
        runners.append(("en ligne", lambda fmt: _run_online(code, fmt)))
    if not runners:
        result.error = ("Aucun moteur de rendu disponible : installez Java et PlantUML, "
                        "ou autorisez le rendu en ligne (ALLOW_ONLINE_RENDER=true).")
        return result

    errors: List[str] = []
    for engine, run in runners:
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                png_future, svg_future = pool.submit(run, "png"), pool.submit(run, "svg")
                result.png = png_future.result()
                try:
                    result.svg = svg_future.result()
                except RenderError:
                    result.svg = None
            result.engine = engine
            result.error = None
            return result
        except RenderError as exc:
            errors.append(f"{engine} : {exc}")
    result.error = " — ".join(errors)
    return result


# --------------------------------------------------------------------------- #
# Enregistrement
# --------------------------------------------------------------------------- #
def save_outputs(result: RenderResult, name: str = "diagramme", output_dir: Optional[Path] = None) -> Dict[str, Path]:
    """Enregistre .puml / .png / .svg dans outputs/ et renvoie les chemins."""
    folder = Path(output_dir or config.OUTPUT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{slug(name).lower()[:40]}-{datetime.now():%Y%m%d-%H%M%S}"
    paths: Dict[str, Path] = {}
    for ext, data in (("puml", result.code.encode("utf-8")), ("png", result.png), ("svg", result.svg)):
        if data:
            path = folder / f"{stem}.{ext}"
            path.write_bytes(data)
            paths[ext] = path
    result.files = paths
    return paths


def generate_plantuml(model: BaseDiagram, options: Optional[RenderOptions] = None,
                      output_dir: Optional[Path] = None) -> RenderResult:
    """Raccourci : code + rendu + enregistrement."""
    result = render(generate_plantuml_code(model, options))
    if result.ok:
        save_outputs(result, model.title or "diagramme", output_dir)
    return result
