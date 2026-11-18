import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Environnement de test : pas d'appel réseau, clé factice.
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["ALLOW_ONLINE_RENDER"] = "false"
os.environ.setdefault("OUTPUT_DIR", str(ROOT / "tests" / "_outputs"))
