"""Test de bout en bout de l'interface Streamlit, avec un LLM simulé."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services import ai_service
from services.diagram_types import DIAGRAM_TYPES
from services.uml_generator import _local_command
from test_ai_service import ApiError, reply

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def llm_returning(key):
    payload = reply(json.dumps(json.loads(DIAGRAM_TYPES[key].schema_example)))
    return lambda system, messages, json_mode: payload


def fresh():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    at.run(timeout=60)


def test_first_load():
    at = fresh()
    assert [p.label for p in at.get("pills")] == ["Type de diagramme"]
    assert at.text_area[0].value == ""
    generate = next(b for b in at.button if "Générer" in b.label)
    assert not generate.disabled


def test_load_example_then_generate_each_type(monkeypatch):
    for key, dt in DIAGRAM_TYPES.items():
        monkeypatch.setattr(ai_service, "_call_llm", llm_returning(key))
        at = fresh()
        at.session_state["dtype"] = key
        at.run()
        click(at, "Charger cet exemple")
        assert at.text_area[0].value == next(iter(dt.examples.values()))
        click(at, next(b.label for b in at.button if "Générer" in b.label))
        assert not at.exception, key
        if _local_command():
            assert not at.error, [e.value for e in at.error]
        else:  # sans PlantUML : message clair, le modèle et le code restent disponibles
            assert [e.value for e in at.error] == ["Le diagramme n'a pas pu être dessiné."]
        assert at.session_state["result"]["type"] == key
        assert len(at.tabs) == 4
        assert len(at.session_state["history"]) == 1


def test_empty_description_warns(monkeypatch):
    at = fresh()
    click(at, next(b.label for b in at.button if "Générer" in b.label))
    assert any("saisir" in w.value for w in at.warning)


def test_api_error_is_displayed_not_crashed(monkeypatch):
    def boom(system, messages, json_mode):
        raise ApiError(429)

    monkeypatch.setattr(ai_service, "_call_llm", boom)
    at = fresh()
    at.text_area[0].set_value("Un client passe des commandes.")
    at.run()
    click(at, next(b.label for b in at.button if "Générer" in b.label))
    assert not at.exception
    assert any("Limite de requêtes" in e.value for e in at.error)


def test_changing_theme_rerenders_without_calling_llm(monkeypatch):
    calls = []
    inner = llm_returning("class")
    monkeypatch.setattr(ai_service, "_call_llm", lambda *a: calls.append(1) or inner(*a))
    at = fresh()
    at.text_area[0].set_value("Un candidat soumet des candidatures.")
    at.run()
    click(at, next(b.label for b in at.button if "Générer" in b.label))
    assert len(calls) == 1
    first_code = at.session_state["rendered"][0]
    at.selectbox(next(s.key for s in at.selectbox if s.label == "Thème")).set_value("Bleu").run(timeout=60)
    assert len(calls) == 1
    assert "!theme cerulean" in at.session_state["rendered"][0] != first_code


def test_history_restore(monkeypatch):
    monkeypatch.setattr(ai_service, "_call_llm", llm_returning("er"))
    at = fresh()
    at.session_state["dtype"] = "er"
    at.run()
    at.text_area[0].set_value("Une bibliothèque.")
    at.run()
    click(at, next(b.label for b in at.button if "Générer" in b.label))
    entry_id = at.session_state["history"][0]["id"]
    at.session_state["result"] = None
    at.session_state["dtype"] = "class"
    at.run()
    next(b for b in at.button if b.key == f"hist_{entry_id}").click()
    at.run(timeout=60)
    assert at.session_state["dtype"] == "er" and at.session_state["result"]["id"] == entry_id
    assert not at.exception
