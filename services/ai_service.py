"""Appel du LLM (Groq) : prompt adapté au type de diagramme, JSON robuste, reprises automatiques."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

import config
from models.uml_model import BaseDiagram
from services.diagram_types import DIAGRAM_TYPES, DiagramType
from services.validator import ModelError, validate_model

log = logging.getLogger(__name__)

DETAIL_LEVELS = {
    "minimal": "Reste concis : uniquement les éléments explicitement cités dans le texte.",
    "standard": "Sois fidèle au texte. Tu peux compléter par des attributs ou éléments évidents (identifiant, date...), en les signalant dans \"assumptions\".",
    "detailed": "Sois exhaustif : complète les éléments manquants avec des hypothèses raisonnables, en les signalant toutes dans \"assumptions\".",
}


class GenerationError(RuntimeError):
    """Erreur affichable à l'utilisateur."""


@dataclass
class GenerationResult:
    model: BaseDiagram
    warnings: List[str] = field(default_factory=list)
    attempts: int = 1
    usage: Dict[str, int] = field(default_factory=dict)


_client = None


def _get_client():
    global _client
    if _client is None:
        if not config.GROQ_API_KEY or config.GROQ_API_KEY.startswith("VOTRE_"):
            raise GenerationError("Clé API manquante : renseignez GROQ_API_KEY dans le fichier .env.")
        from groq import Groq  # import tardif : l'application s'ouvre même sans le paquet

        _client = Groq(api_key=config.GROQ_API_KEY, timeout=config.GROQ_TIMEOUT, max_retries=1)
    return _client


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def build_system_prompt(dt: DiagramType, detail: str, language: str) -> str:
    return f"""Tu es un architecte logiciel expert en modélisation UML.
Tu transformes une description en un modèle structuré pour un {dt.label.lower()}.

Réponds par UN SEUL objet JSON valide, sans texte autour, sans bloc markdown, sans commentaire.
Langue des noms, libellés et hypothèses : {language}.

Structure attendue (exemple de forme à respecter) :
{dt.schema_example}

Règles propres à ce diagramme :
{dt.rules}

Règles générales :
- Fidélité : n'invente rien qui contredise le texte. {DETAIL_LEVELS.get(detail, DETAIL_LEVELS["standard"])}
- Respecte les cardinalités et les contraintes exprimées dans le texte.
- Évite les doublons et les synonymes : un concept = un seul élément.
- "title" : un titre court. "assumptions" : la liste des hypothèses que tu as faites (liste vide s'il n'y en a pas).
- Reste cohérent : tout élément cité dans un lien doit être déclaré.
{dt.detailed_extra if detail == "detailed" else ""}""".strip()


def build_user_prompt(description: str) -> str:
    return f"Description du système :\n\n\"\"\"\n{description.strip()}\n\"\"\""


# --------------------------------------------------------------------------- #
# Extraction du JSON
# --------------------------------------------------------------------------- #
def extract_json(text: str) -> Any:
    """Extrait un objet JSON même s'il est entouré de texte ou d'un bloc ```json."""
    if not text or not text.strip():
        raise ValueError("réponse vide")
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("aucun objet JSON dans la réponse")
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("JSON tronqué : la réponse a été coupée avant la fin")


# --------------------------------------------------------------------------- #
# Appel et reprises
# --------------------------------------------------------------------------- #
def _status(exc: Exception) -> Optional[int]:
    return getattr(exc, "status_code", None)


def _failed_generation(exc: Exception) -> str:
    """Récupère le JSON partiel renvoyé par Groq dans l'erreur 400 json_validate_failed."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("failed_generation") or "")
    return ""


def _call_llm(system: str, messages: List[Dict[str, str]], json_mode: bool):
    kwargs: Dict[str, Any] = dict(
        model=config.GROQ_MODEL,
        messages=[{"role": "system", "content": system}, *messages],
        temperature=0.1,
        max_tokens=config.GROQ_MAX_TOKENS,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return _get_client().chat.completions.create(**kwargs)


def _friendly(exc: Exception) -> str:
    code = _status(exc)
    if code in (401, 403):
        return "Clé API refusée par Groq : vérifiez GROQ_API_KEY."
    if code == 404:
        return f"Modèle « {config.GROQ_MODEL} » introuvable : vérifiez GROQ_MODEL."
    if code == 413:
        return "La description est trop longue pour le modèle. Raccourcissez-la ou découpez-la en plusieurs parties."
    if code == 429:
        return "Limite de requêtes Groq atteinte. Patientez quelques secondes puis réessayez."
    if code and code >= 500:
        return "Le service Groq est momentanément indisponible. Réessayez dans un instant."
    return f"Échec de l'appel au modèle : {exc}"


def generate_diagram_model(
    description: str,
    diagram_type: str = "class",
    detail: str = "standard",
    language: str = "français",
    max_attempts: int = 3,
) -> GenerationResult:
    """Génère, valide et nettoie le modèle d'un diagramme à partir d'un texte."""
    description = (description or "").strip()
    if not description:
        raise GenerationError("Veuillez saisir une description.")
    if len(description) > config.MAX_DESCRIPTION_CHARS:
        raise GenerationError(
            f"Description trop longue ({len(description)} caractères, maximum {config.MAX_DESCRIPTION_CHARS}). "
            "Découpez-la en plusieurs parties."
        )
    dt = DIAGRAM_TYPES.get(diagram_type)
    if dt is None:
        raise GenerationError(f"Type de diagramme inconnu : {diagram_type}")

    system = build_system_prompt(dt, detail, language)
    messages: List[Dict[str, str]] = [{"role": "user", "content": build_user_prompt(description)}]
    json_mode = True
    last_error = "erreur inconnue"
    usage: Dict[str, int] = {}

    for attempt in range(1, max_attempts + 1):
        try:
            response = _call_llm(system, messages, json_mode)
        except GenerationError:
            raise
        except Exception as exc:  # erreurs réseau / API du SDK Groq
            code = _status(exc)
            if code in (401, 403, 404, 413, 429) or (code and code >= 500 and attempt == max_attempts):
                raise GenerationError(_friendly(exc)) from exc
            last_error = _friendly(exc)
            log.warning("Appel Groq échoué (tentative %s) : %s", attempt, exc)
            if code == 400:
                # json_validate_failed : on tente de récupérer le JSON partiel, sinon on
                # désactive le mode JSON strict et on demande au modèle d'être plus concis.
                partial = _failed_generation(exc)
                if partial:
                    try:
                        model = dt.model.model_validate(extract_json(partial))
                        cleaned, warnings = validate_model(model)
                        return GenerationResult(cleaned, warnings, attempt, usage)
                    except Exception:
                        pass
                json_mode = False
                messages = messages[:1] + [{
                    "role": "user",
                    "content": "Ta réponse précédente n'était pas un JSON valide ou était trop longue. "
                               "Renvoie uniquement l'objet JSON, de façon plus compacte (sans méthodes ni détails superflus).",
                }]
            continue

        choice = response.choices[0]
        content = choice.message.content or ""
        if getattr(response, "usage", None):
            usage = {
                "prompt": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion": getattr(response.usage, "completion_tokens", 0) or 0,
            }
        try:
            if choice.finish_reason == "length":
                raise ValueError("réponse tronquée (limite de tokens atteinte)")
            data = extract_json(content)
            if not isinstance(data, dict):
                raise ValueError("la réponse n'est pas un objet JSON")
            model = dt.model.model_validate(data)
            cleaned, warnings = validate_model(model)
            return GenerationResult(cleaned, warnings, attempt, usage)
        except ModelError as exc:
            # Réponse bien formée mais vide : la description ne contient rien à modéliser,
            # relancer l'appel n'y changerait rien.
            raise GenerationError(str(exc)) from exc
        except (ValueError, ValidationError) as exc:
            last_error = str(exc).splitlines()[0][:200]
            log.warning("Réponse invalide (tentative %s) : %s", attempt, exc)
            if "tronquée" in last_error:
                hint = "Ta réponse a été coupée. Renvoie le JSON complet en étant plus compact."
            else:
                hint = f"Ta réponse est invalide ({last_error}). Renvoie uniquement l'objet JSON corrigé."
            messages = messages[:1] + [
                {"role": "assistant", "content": content[:2000]},
                {"role": "user", "content": hint},
            ]

    raise GenerationError(
        f"Impossible d'obtenir un modèle valide après {max_attempts} tentatives ({last_error}). "
        "Essayez une description plus courte, ou générez le diagramme en plusieurs parties."
    )
