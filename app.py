"""Text2UML : génération de diagrammes UML à partir d'une description en langage naturel."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import streamlit as st

import config
from services.ai_service import GenerationError, generate_diagram_model
from services.diagram_types import DEFAULT_TYPE, DIAGRAM_TYPES, TYPE_ORDER
from services.uml_generator import (
    DIRECTIONS,
    THEMES,
    RenderOptions,
    _local_command,
    generate_plantuml_code,
    render,
    save_outputs,
)

st.set_page_config(page_title="Text2UML", page_icon="", layout="wide", initial_sidebar_state="expanded")

DETAIL_LABELS = {"minimal": "Minimal", "standard": "Standard", "detailed": "Détaillé"}
LANGUAGES = {"Français": "français", "English": "English"}
HISTORY_LIMIT = 12

st.markdown(
    """
<style>
.block-container {padding-top: 4rem; max-width: 1280px;}
.t2u-hero {padding: 1.1rem 1.4rem; border-radius: 14px; margin-bottom: 1.1rem;
  background: linear-gradient(120deg, #1f3a8a 0%, #3b82f6 100%); color: #fff;}
.t2u-hero h1 {margin: 0; font-size: 1.9rem; color: #fff; padding: 0;}
.t2u-hero p {margin: .25rem 0 0; opacity: .92; font-size: 1.02rem;}
.t2u-type {padding: .6rem .9rem; border-left: 4px solid #3b82f6; border-radius: 6px;
  background: rgba(59,130,246,.08); margin: .2rem 0 .9rem;}
div[data-testid="stMetric"] {background: rgba(128,128,128,.08); padding: .6rem .9rem; border-radius: 10px;}
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    defaults = {
        "description": "",
        "result": None,        # dernier résultat : type, modèle, alertes, hypothèses…
        "override": None,      # code PlantUML modifié à la main
        "options_sig": None,
        "rendered": None,      # (code, RenderResult)
        "history": [],
        "last_upload": None,
        "dtype": DEFAULT_TYPE,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


_init_state()


def _load_example() -> None:
    dt = DIAGRAM_TYPES[st.session_state.dtype]
    st.session_state.description = dt.examples[st.session_state.example_choice]


def _clear_description() -> None:
    st.session_state.description = ""


def _restore(entry_id: str) -> None:
    for entry in st.session_state.history:
        if entry["id"] == entry_id:
            st.session_state.result = entry
            st.session_state.override = None
            st.session_state.dtype = entry["type"]
            st.session_state.description = entry["description"]
            return


# --------------------------------------------------------------------------- #
# Barre latérale : paramètres
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Paramètres")

    st.subheader("Génération")
    detail = st.select_slider(
        "Niveau de détail", options=list(DETAIL_LABELS), value="standard",
        format_func=DETAIL_LABELS.get,
        help="Minimal : seulement ce qui est écrit. Détaillé : le modèle complète avec des hypothèses raisonnables.",
    )
    language_label = st.radio("Langue du diagramme", list(LANGUAGES), horizontal=True)

    st.subheader("Style du diagramme")
    theme = st.selectbox("Thème", list(THEMES))
    direction = st.selectbox("Orientation", list(DIRECTIONS), help="Sans effet sur les diagrammes de séquence et d'activité.")
    scale = st.slider("Taille de l'image", 0.7, 2.0, 1.0, 0.1)
    show_methods = st.toggle("Afficher les méthodes (classes)", value=True)

    options = RenderOptions(theme=theme, direction=direction, scale=scale, show_methods=show_methods)

    st.divider()
    st.subheader("Environnement")
    api_ok = bool(config.GROQ_API_KEY) and not config.GROQ_API_KEY.startswith("VOTRE_")
    st.write(("" if api_ok else "❌") + " Clé API Groq")
    st.caption(f"Modèle : `{config.GROQ_MODEL}`")
    local_engine = _local_command()
    if local_engine:
        st.write(" PlantUML local")
    elif config.ALLOW_ONLINE_RENDER:
        st.write(" PlantUML en ligne")
        st.caption("Aucun PlantUML local : le texte du diagramme est envoyé au serveur public. "
                   "Installez Java et `plantuml.jar` pour un rendu privé.")
    else:
        st.write(" Aucun moteur de rendu")

    st.divider()
    st.subheader(" Historique")
    if not st.session_state.history:
        st.caption("Vos diagrammes générés apparaîtront ici.")
    for entry in st.session_state.history:
        icon = DIAGRAM_TYPES[entry["type"]].icon
        st.button(f"{icon} {entry['title']} · {entry['time']}", key=f"hist_{entry['id']}",
                  on_click=_restore, args=(entry["id"],), width="stretch")
    if st.session_state.history and st.button("Vider l'historique", type="tertiary"):
        st.session_state.history = []
        st.rerun()


# --------------------------------------------------------------------------- #
# En-tête et saisie
# --------------------------------------------------------------------------- #
st.markdown(
    '<div class="t2u-hero"><h1> Text2UML</h1>'
    "<p>Décrivez votre système en langage naturel, choisissez un type de diagramme, obtenez le schéma.</p></div>",
    unsafe_allow_html=True,
)

dtype_key = st.pills(
    "Type de diagramme", TYPE_ORDER, selection_mode="single", default=DEFAULT_TYPE, required=True,
    format_func=lambda k: f"{DIAGRAM_TYPES[k].icon} {DIAGRAM_TYPES[k].label}", key="dtype",
)
dt = DIAGRAM_TYPES[dtype_key or DEFAULT_TYPE]
st.markdown(f'<div class="t2u-type"><b>{dt.label}</b> — {dt.description}</div>', unsafe_allow_html=True)

col_text, col_help = st.columns([3, 1.25], gap="large")

with col_text:
    st.text_area(
        "Décrivez votre système :", key="description", height=260,
        placeholder="Exemple : " + next(iter(dt.examples.values()))[:140] + "…",
        max_chars=config.MAX_DESCRIPTION_CHARS,
    )
    n_chars = len(st.session_state.description)
    st.caption(f"{n_chars} / {config.MAX_DESCRIPTION_CHARS} caractères")

    b1, b2, _ = st.columns([2, 1, 3])
    generate = b1.button(" Générer le diagramme", type="primary", width="stretch", disabled=not api_ok)
    b2.button("Effacer", on_click=_clear_description, width="stretch")
    if not api_ok:
        st.warning("Renseignez `GROQ_API_KEY` dans le fichier `.env`, puis relancez l'application.")

with col_help:
    st.markdown("**Exemples**")
    st.selectbox("Choisir un exemple", list(dt.examples), key="example_choice", label_visibility="collapsed")
    st.button("Charger cet exemple", on_click=_load_example, width="stretch")
    with st.expander(" Importer un fichier texte"):
        upload = st.file_uploader("Fichier .txt ou .md", type=["txt", "md"], label_visibility="collapsed")
        if upload is not None and st.session_state.last_upload != upload.file_id:
            st.session_state.last_upload = upload.file_id
            st.session_state.description = upload.getvalue().decode("utf-8", errors="replace")[: config.MAX_DESCRIPTION_CHARS]
            st.rerun()
    with st.expander(" Conseils"):
        st.markdown(
            "- Une phrase par règle : « Un client passe plusieurs commandes ».\n"
            "- Citez les **attributs** et les **cardinalités** (un, plusieurs, au plus 5…).\n"
            "- Pour un système très grand, générez-le **en plusieurs parties**.\n"
            "- Changez le thème ou l'orientation à tout moment : l'image se met à jour sans rappeler l'IA."
        )

# --------------------------------------------------------------------------- #
# Génération
# --------------------------------------------------------------------------- #
if generate:
    description = st.session_state.description
    if not description.strip():
        st.warning("Veuillez saisir une description.")
    else:
        try:
            with st.status("Analyse de la description…", expanded=True) as status:
                generated = generate_diagram_model(
                    description, dt.key, detail=detail, language=LANGUAGES[language_label],
                )
                status.update(label="Modèle validé. Génération de l'image…", state="running")
                entry = {
                    "id": hashlib.md5(f"{datetime.now().isoformat()}{description}".encode()).hexdigest()[:10],
                    "time": datetime.now().strftime("%H:%M"),
                    "type": dt.key,
                    "title": generated.model.title or dt.label,
                    "model": generated.model,
                    "warnings": generated.warnings,
                    "attempts": generated.attempts,
                    "usage": generated.usage,
                    "description": description,
                }
                st.session_state.result = entry
                st.session_state.override = None
                st.session_state.history = ([entry] + st.session_state.history)[:HISTORY_LIMIT]
                status.update(label="Diagramme prêt", state="complete", expanded=False)
        except GenerationError as error:
            st.error(str(error))
        except Exception as error:  # imprévu : on garde l'application utilisable
            st.error("Une erreur inattendue est survenue.")
            with st.expander("Détails techniques"):
                st.exception(error)

# --------------------------------------------------------------------------- #
# Résultat
# --------------------------------------------------------------------------- #
result = st.session_state.result
if result:
    r_dt = DIAGRAM_TYPES[result["type"]]
    model = result["model"]

    sig = (options.theme, options.direction, options.scale, options.show_methods, result["id"])
    if st.session_state.options_sig != sig:
        st.session_state.options_sig = sig
        st.session_state.override = None
    generated_code = generate_plantuml_code(model, options)
    code = st.session_state.override or generated_code

    cached = st.session_state.rendered
    if not cached or cached[0] != code:
        with st.spinner("Rendu du diagramme…"):
            rendered = render(code)
        if rendered.ok:
            save_outputs(rendered, model.title or r_dt.label)
        st.session_state.rendered = (code, rendered)
    rendered = st.session_state.rendered[1]

    st.divider()
    st.subheader(f"{r_dt.icon} {model.title or r_dt.label}")
    stats = r_dt.stats(model)
    for col, (label, value) in zip(st.columns(len(stats) + 1), stats + [("Alertes", len(result["warnings"]))]):
        col.metric(label, value)

    tab_diagram, tab_model, tab_code, tab_checks = st.tabs(
        [" Diagramme", " Modèle structuré", " Code PlantUML",
         f" Vérifications ({len(result['warnings']) + len(model.assumptions)})"]
    )

    with tab_diagram:
        if rendered.ok:
            st.image(rendered.png, width="content")
            st.caption(f"Rendu : PlantUML {rendered.engine}" + (
                f" · {result['usage'].get('prompt', 0) + result['usage'].get('completion', 0)} tokens"
                if result["usage"] else "") + (f" · {result['attempts']} tentatives" if result["attempts"] > 1 else ""))
            stem = f"{r_dt.key}-{result['id']}"
            d1, d2, d3, d4 = st.columns(4)
            d1.download_button(" PNG", rendered.png, f"{stem}.png", "image/png", on_click="ignore", width="stretch")
            d2.download_button(" SVG", rendered.svg or b"", f"{stem}.svg", "image/svg+xml", on_click="ignore",
                               disabled=not rendered.svg, width="stretch")
            d3.download_button(" Code .puml", code, f"{stem}.puml", "text/plain", on_click="ignore", width="stretch")
            d4.download_button(" Modèle .json", json.dumps(model.model_dump(), ensure_ascii=False, indent=2),
                               f"{stem}.json", "application/json", on_click="ignore", width="stretch")
        else:
            st.error("Le diagramme n'a pas pu être dessiné.")
            st.code(rendered.error or "Erreur inconnue", language=None)
            st.info("Le modèle et le code PlantUML restent disponibles dans les autres onglets. "
                    "Vous pouvez corriger le code puis le redessiner depuis l'onglet « Code PlantUML ».")

    with tab_model:
        st.json(model.model_dump(), expanded=2)

    with tab_code:
        key = "code_" + hashlib.md5(code.encode()).hexdigest()[:8]
        edited = st.text_area("Code source PlantUML (modifiable)", value=code, height=380, key=key)
        c1, c2 = st.columns([1, 1])
        if c1.button(" Redessiner depuis ce code", disabled=edited == code):
            st.session_state.override = edited
            st.rerun()
        if st.session_state.override and c2.button(" Revenir au code généré"):
            st.session_state.override = None
            st.rerun()
        st.caption("Le code modifié est abandonné si vous changez de thème, d'orientation ou régénérez le diagramme.")

    with tab_checks:
        if model.assumptions:
            st.markdown("**Hypothèses faites par l'IA**")
            for item in model.assumptions:
                st.info(item, icon="")
        if result["warnings"]:
            st.markdown("**Corrections et points d'attention**")
            for item in result["warnings"]:
                st.warning(item)
        if not model.assumptions and not result["warnings"]:
            st.success("Aucune alerte : le modèle est cohérent.")
