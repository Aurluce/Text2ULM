"""Configuration chargée depuis .env (ou depuis les secrets Streamlit)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "").strip() or "llama-3.3-70b-versatile"

# Un JSON structuré est verbeux : une limite trop basse produit des réponses tronquées,
# donc un JSON invalide (erreur « json_validate_failed »).
GROQ_MAX_TOKENS = _int("GROQ_MAX_TOKENS", 8192)
GROQ_TIMEOUT = _int("GROQ_TIMEOUT", 60)
MAX_DESCRIPTION_CHARS = _int("MAX_DESCRIPTION_CHARS", 8000)

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "outputs"))

# Chemin ou commande PlantUML ; laissé vide, l'application cherche « plantuml » puis
# un fichier plantuml.jar (nécessite Java). Sinon, elle bascule sur le serveur public.
PLANTUML_CMD = os.getenv("PLANTUML_CMD", "").strip()
PLANTUML_JAR = os.getenv("PLANTUML_JAR", "").strip()
PLANTUML_SERVER = os.getenv("PLANTUML_SERVER", "https://www.plantuml.com/plantuml").rstrip("/")
ALLOW_ONLINE_RENDER = os.getenv("ALLOW_ONLINE_RENDER", "true").strip().lower() in ("1", "true", "yes", "oui")
