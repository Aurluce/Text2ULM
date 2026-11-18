import json
from types import SimpleNamespace

import pytest

from services import ai_service
from services.ai_service import GenerationError, extract_json, generate_diagram_model

GOOD = {
    "title": "Test",
    "classes": [{"name": "Client", "attributes": ["id: int"]}, {"name": "Commande"}],
    "relations": [{"source": "Client", "target": "Commande", "type": "association",
                   "source_cardinality": "1", "target_cardinality": "*"}],
}


def reply(content, finish="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
    )


class ApiError(Exception):
    def __init__(self, status_code, body=None):
        super().__init__(f"Error code: {status_code}")
        self.status_code, self.body = status_code, body


@pytest.fixture
def fake_llm(monkeypatch):
    """Remplace l'appel Groq par une file de réponses (ou d'exceptions)."""
    calls = []

    def install(*outputs):
        queue = list(outputs)

        def fake(system, messages, json_mode):
            calls.append({"system": system, "messages": messages, "json_mode": json_mode})
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(ai_service, "_call_llm", fake)
        return calls

    return install


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Voici :\n```json\n{"a": {"b": "}"}}\n```\nFin') == {"a": {"b": "}"}}
    assert extract_json('texte {"a": "x{y"} texte') == {"a": "x{y"}
    with pytest.raises(ValueError, match="tronqué"):
        extract_json('{"a": [1, 2')
    with pytest.raises(ValueError):
        extract_json("   ")


def test_success_first_try(fake_llm):
    calls = fake_llm(reply(json.dumps(GOOD)))
    result = generate_diagram_model("Un client passe des commandes.", "class")
    assert result.attempts == 1 and len(result.model.classes) == 2
    assert result.usage == {"prompt": 10, "completion": 20}
    assert calls[0]["json_mode"] is True
    assert "diagramme de classes" in calls[0]["system"]


def test_prompt_is_specific_to_diagram_type(fake_llm):
    calls = fake_llm(reply(json.dumps({"states": ["A", "B"], "transitions": [{"source": "[*]", "target": "A"}]})))
    generate_diagram_model("Un objet a deux états.", "state", detail="detailed")
    assert "diagramme d'états" in calls[0]["system"] and "[*]" in calls[0]["system"]
    assert "Ajoute les transitions d'erreur" in calls[0]["system"]


def test_truncated_response_is_retried(fake_llm):
    calls = fake_llm(reply('{"classes": [{"name": "Cli', finish="length"), reply(json.dumps(GOOD)))
    result = generate_diagram_model("x", "class")
    assert result.attempts == 2
    assert "coupée" in calls[1]["messages"][-1]["content"]


def test_invalid_json_is_retried_with_feedback(fake_llm):
    calls = fake_llm(reply("Je ne peux pas."), reply(json.dumps(GOOD)))
    assert generate_diagram_model("x", "class").attempts == 2
    assert calls[1]["messages"][-1]["role"] == "user"


def test_json_validate_failed_recovers_partial_output(fake_llm):
    """Erreur 400 de Groq : on récupère le JSON dans failed_generation quand il est exploitable."""
    body = {"error": {"code": "json_validate_failed", "failed_generation": json.dumps(GOOD)}}
    fake_llm(ApiError(400, body))
    result = generate_diagram_model("x", "class")
    assert result.attempts == 1 and len(result.model.classes) == 2


def test_json_validate_failed_empty_falls_back_without_json_mode(fake_llm):
    """Cas réel signalé : failed_generation vide. On retente sans le mode JSON strict."""
    body = {"error": {"code": "json_validate_failed", "failed_generation": ""}}
    calls = fake_llm(ApiError(400, body), reply(json.dumps(GOOD)))
    result = generate_diagram_model("x", "class")
    assert result.attempts == 2
    assert calls[0]["json_mode"] is True and calls[1]["json_mode"] is False


def test_all_attempts_fail(fake_llm):
    fake_llm(reply("non"), reply("non"), reply("non"))
    with pytest.raises(GenerationError, match="3 tentatives"):
        generate_diagram_model("x", "class")


@pytest.mark.parametrize("code,expected", [(401, "Clé API"), (404, "introuvable"), (429, "Limite"), (413, "trop longue")])
def test_http_errors_are_explained_and_not_retried(fake_llm, code, expected):
    calls = fake_llm(ApiError(code))
    with pytest.raises(GenerationError, match=expected):
        generate_diagram_model("x", "class")
    assert len(calls) == 1


def test_empty_model_gives_clear_error(fake_llm):
    fake_llm(reply(json.dumps({"classes": [], "relations": []})))
    with pytest.raises(GenerationError, match="Aucune classe"):
        generate_diagram_model("x", "class")


def test_input_checks():
    with pytest.raises(GenerationError, match="saisir"):
        generate_diagram_model("   ", "class")
    with pytest.raises(GenerationError, match="trop longue"):
        generate_diagram_model("x" * 20000, "class")
    with pytest.raises(GenerationError, match="inconnu"):
        generate_diagram_model("x", "nope")
