import json

import pytest

from models.uml_model import ActivityModel, ERModel, SequenceModel, StateModel, UMLModel, UseCaseModel
from services.diagram_types import DIAGRAM_TYPES
from services.validator import ModelError, validate_model


@pytest.mark.parametrize("key", list(DIAGRAM_TYPES))
def test_schema_examples_are_valid_and_clean(key):
    """Les exemples montrés au LLM doivent eux-mêmes passer le validateur sans alerte."""
    dt = DIAGRAM_TYPES[key]
    model, warnings = validate_model(dt.model.model_validate(json.loads(dt.schema_example)))
    assert warnings == []
    assert all(value > 0 for _, value in dt.stats(model))


def test_class_tolerates_llm_variants():
    model = UMLModel.model_validate({
        "entities": ["Client", {"name": "Commande", "attributes": [{"name": "total", "type": "float"}]}],
        "relationships": [{"from": "Client", "to": "Commande", "type": "Composition",
                           "source_cardinality": "un", "target_cardinality": "n"}],
    })
    clean, warnings = validate_model(model)
    rel = clean.relations[0]
    assert (rel.type, rel.source_cardinality, rel.target_cardinality) == ("composition", "1", "*")
    assert clean.classes[1].attributes == ["total: float"]
    assert warnings == []


def test_class_merges_duplicates_and_adds_missing_class():
    model = UMLModel.model_validate({
        "classes": [{"name": "Client", "attributes": ["id: int"]}, {"name": "client", "attributes": ["nom: string"]}],
        "relations": [{"source": "Client", "target": "Commande", "type": "association"},
                      {"source": "Client", "target": "Commande", "type": "association"}],
    })
    clean, warnings = validate_model(model)
    assert [c.name for c in clean.classes] == ["Client", "Commande"]
    assert clean.classes[0].attributes == ["id: int", "nom: string"]
    assert len(clean.relations) == 1
    assert any("fusionnées" in w for w in warnings) and any("ajoutée" in w for w in warnings)


def test_class_resolves_accents_and_plural():
    model = UMLModel.model_validate({
        "classes": [{"name": "Entreprise"}, {"name": "Recruteur"}],
        "relations": [{"source": "entreprise", "target": "Recruteurs", "type": "association"}],
    })
    clean, warnings = validate_model(model)
    assert len(clean.classes) == 2 and len(clean.relations) == 1
    assert clean.relations[0].target == "Recruteur"


def test_class_rejects_inheritance_cycle():
    model = UMLModel.model_validate({
        "classes": [{"name": "A"}, {"name": "B"}],
        "relations": [{"source": "A", "target": "B", "type": "inheritance"},
                      {"source": "B", "target": "A", "type": "inheritance"}],
    })
    clean, warnings = validate_model(model)
    assert len(clean.relations) == 1 and any("cycle" in w for w in warnings)


def test_empty_models_raise():
    with pytest.raises(ModelError):
        validate_model(UMLModel.model_validate({"classes": [], "relations": []}))
    with pytest.raises(ModelError):
        validate_model(SequenceModel.model_validate({"participants": ["A"], "steps": []}))


def test_er_entity_attribute_strings_and_pk_warning():
    model = ERModel.model_validate({
        "tables": [{"name": "Livre", "attributes": ["id: int (PK)", "auteur_id: int (FK)"]},
                   {"name": "Auteur", "attributes": ["nom: string"]}],
        "relations": [{"source": "Auteur", "target": "Livre"}],
    })
    clean, warnings = validate_model(model)
    livre = clean.entities[0]
    assert livre.attributes[0].primary_key and livre.attributes[1].foreign_key
    assert any("Auteur" in w and "clé primaire" in w for w in warnings)


def test_usecase_swaps_and_rejects_bad_links():
    model = UseCaseModel.model_validate({
        "actors": ["Client"],
        "use_cases": ["Commander", "Payer"],
        "relations": [
            {"source": "Commander", "target": "Client", "type": "association"},   # inversé : à remettre dans l'ordre
            {"source": "Commander", "target": "Payer", "type": "include"},
            {"source": "Client", "target": "Payer", "type": "include"},          # include avec un acteur : invalide
            {"source": "Commander", "target": "Inconnu", "type": "extend"},      # cible non déclarée
        ],
    })
    clean, warnings = validate_model(model)
    assert (clean.relations[0].source, clean.relations[0].target) == ("Client", "Commander")
    assert len(clean.relations) == 2 and len(warnings) >= 2


def test_sequence_autodeclares_participants_and_closes_groups():
    model = SequenceModel.model_validate({
        "participants": [{"name": "Client", "kind": "utilisateur"}],
        "steps": [
            {"source": "Client", "target": "Serveur", "label": "demande"},
            {"kind": "alt", "label": "ok"},
            {"kind": "message", "source": "Serveur", "target": "Client", "label": "réponse", "arrow": "return"},
        ],
    })
    clean, warnings = validate_model(model)
    assert {p.name for p in clean.participants} == {"Client", "Serveur"}
    assert clean.participants[0].kind == "actor"
    assert clean.steps[-1].kind == "group_end"
    assert any("non fermé" in w for w in warnings)


def test_activity_closes_blocks_and_adds_start_stop():
    model = ActivityModel.model_validate({"steps": [
        {"kind": "action", "label": "Saisir"},
        {"kind": "if", "label": "Valide ?"},
        {"kind": "action", "label": "Enregistrer"},
    ]})
    clean, warnings = validate_model(model)
    kinds = [s.kind for s in clean.steps]
    assert kinds[0] == "start" and kinds[-1] == "stop" and "endif" in kinds
    assert any("non fermé" in w for w in warnings)


def test_state_normalizes_pseudo_states_and_reachability():
    model = StateModel.model_validate({
        "states": ["Brouillon", "Payée", "Orpheline"],
        "transitions": [
            {"source": "initial", "target": "Brouillon"},
            {"source": "Brouillon", "target": "Payée", "event": "payer"},
            {"source": "Payée", "target": "final"},
        ],
    })
    clean, warnings = validate_model(model)
    assert clean.transitions[0].source == "[*]" and clean.transitions[-1].target == "[*]"
    assert any("Orpheline" in w and "inaccessible" in w for w in warnings)
