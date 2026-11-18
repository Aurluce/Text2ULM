import json
import shutil
import subprocess

import pytest

import config
from services.diagram_types import DIAGRAM_TYPES
from services.uml_generator import (
    DIRECTIONS,
    THEMES,
    RenderOptions,
    _local_command,
    encode_for_server,
    generate_plantuml_code,
    render,
)
from services.validator import validate_model

needs_plantuml = pytest.mark.skipif(_local_command() is None, reason="PlantUML (ou Java + plantuml.jar) absent")


def build(key):
    dt = DIAGRAM_TYPES[key]
    model, _ = validate_model(dt.model.model_validate(json.loads(dt.schema_example)))
    return model


@pytest.mark.parametrize("key", list(DIAGRAM_TYPES))
def test_code_structure(key):
    code = generate_plantuml_code(build(key))
    assert code.startswith("@startuml\n") and code.endswith("@enduml\n")
    assert "title " in code


def test_class_code_details():
    code = generate_plantuml_code(build("class"))
    assert "abstract class Utilisateur {" in code
    assert "enum StatutCandidature {" in code
    assert "Candidat --|> Utilisateur" in code
    assert 'Candidat "1" -- "*" Candidature : soumet' in code
    assert "Candidature ..> StatutCandidature" in code
    assert "seConnecter()" not in generate_plantuml_code(build("class"), RenderOptions(show_methods=False))


def test_er_crowfoot_and_keys():
    code = generate_plantuml_code(build("er"))
    assert "Auteur ||--o{ Livre : écrit" in code
    assert "* id : int <<PK>>" in code and "auteur_id : int <<FK>>" in code


def test_accents_and_reserved_words_get_safe_identifiers():
    from models.uml_model import StateModel
    m, _ = validate_model(StateModel.model_validate({
        "states": ["Prêt", "start", "Fin de vie"],
        "transitions": [{"source": "[*]", "target": "Prêt"}, {"source": "Prêt", "target": "start", "event": "go"},
                        {"source": "start", "target": "Fin de vie", "guard": "ok", "action": "log"}],
    }))
    code = generate_plantuml_code(m)
    assert 'state "Prêt" as Pret' in code
    assert 'state "start" as start_' in code
    assert "start_ --> Fin_de_vie : [ok] / log" in code


def test_labels_are_sanitized():
    from models.uml_model import ActivityModel
    m, _ = validate_model(ActivityModel.model_validate({"steps": [
        {"kind": "action", "label": "Lire; écrire"},
        {"kind": "if", "label": "Valide (oui) ?"}, {"kind": "action", "label": "A"}, {"kind": "endif"},
    ]}))
    code = generate_plantuml_code(m)
    assert ":Lire, écrire;" in code and "if (Valide [oui] ?) then (oui)" in code


def test_theme_direction_scale():
    code = generate_plantuml_code(build("class"), RenderOptions(theme="Bleu", direction=list(DIRECTIONS)[1], scale=1.5))
    assert "!theme cerulean" in code and "left to right direction" in code and "scale 1.5" in code
    seq = generate_plantuml_code(build("sequence"), RenderOptions(direction=list(DIRECTIONS)[1]))
    assert "direction" not in seq


@needs_plantuml
@pytest.mark.parametrize("key", list(DIAGRAM_TYPES))
def test_render_every_diagram_type(key):
    result = render(generate_plantuml_code(build(key)))
    assert result.ok, result.error
    assert result.png.startswith(b"\x89PNG") and result.svg and b"<svg" in result.svg


@needs_plantuml
@pytest.mark.parametrize("theme", list(THEMES))
def test_render_every_theme(theme):
    assert render(generate_plantuml_code(build("class"), RenderOptions(theme=theme))).ok


@needs_plantuml
def test_render_reports_syntax_errors_without_raising():
    result = render("@startuml\nclass A {\n@enduml\n")
    assert not result.ok and "Erreur PlantUML" in result.error


@needs_plantuml
def test_server_encoding_roundtrip():
    cmd = _local_command()
    if len(cmd) == 1:
        pytest.skip("décodage vérifié uniquement avec plantuml.jar")
    code = generate_plantuml_code(build("sequence"))
    out = subprocess.run(cmd + ["-decodeurl", encode_for_server(code)], capture_output=True, text=True).stdout
    assert "Utilisateur" in out and "Base de données" in out


def test_no_engine_gives_actionable_message(monkeypatch):
    monkeypatch.setattr("services.uml_generator._local_command", lambda: None)
    monkeypatch.setattr(config, "ALLOW_ONLINE_RENDER", False)
    result = render("@startuml\nclass A\n@enduml\n")
    assert not result.ok and "Java" in result.error
