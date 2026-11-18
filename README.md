# 📐 Text2UML

Décrivez un système en langage naturel, choisissez un type de diagramme, obtenez le schéma.

## Types de diagrammes
| Type | Contenu |
|---|---|
| 🧱 Classes | classes, attributs, méthodes, héritage, composition, énumérations, cardinalités |
| 🗄️ Entité-association | tables, clés primaires/étrangères, notation pattes de corbeau |
| 🎯 Cas d'utilisation | acteurs, cas, `include`, `extend`, généralisation |
| 🔁 Séquence | messages, retours, `alt` / `opt` / `loop` / `par`, notes |
| 🔀 Activité | décisions, boucles, parallélisme, couloirs |
| 🚦 États | états, événements, gardes, actions |
| 🏗️ Composants | architecture : services, bases, équipements, liens synchrones/asynchrones |

## Installation
```bash
pip install -r requirements.txt
cp .env.example .env        # puis renseigner GROQ_API_KEY
streamlit run app.py
```

**Rendu des images** (au choix) :
1. `plantuml` dans le PATH, ou
2. Java + `plantuml.jar` placé à côté de `app.py` (ou `PLANTUML_JAR=chemin` dans `.env`), ou
3. rien à installer : l'application utilise le serveur public PlantUML (le texte du diagramme y est envoyé ;
   `ALLOW_ONLINE_RENDER=false` pour l'interdire).

## Organisation
```
app.py                    interface Streamlit
config.py                 variables d'environnement
utils.py                  noms, identifiants PlantUML, cardinalités
models/uml_model.py       un modèle Pydantic par type de diagramme (tolérant aux variantes du LLM)
services/diagram_types.py catalogue : prompts, règles, exemples, statistiques
services/ai_service.py    appel Groq, extraction JSON, reprises automatiques
services/validator.py     nettoyage et contrôle de cohérence
services/uml_generator.py code PlantUML + rendu PNG/SVG
tests/                    pytest (64 tests)
```

## Tests
```bash
pip install pytest
pytest -q
```

## Ajouter un type de diagramme
1. Modèle Pydantic dans `models/uml_model.py`.
2. Entrée dans `services/diagram_types.py` (prompt, exemple, statistiques).
3. Fonction de validation dans `services/validator.py`.
4. Constructeur PlantUML dans `services/uml_generator.py`.
