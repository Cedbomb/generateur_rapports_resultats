"""Rendu du rapport HTML : un seul fichier autonome, sans bibliotheque externe."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

APP_VERSION = "1.0.0"
ASSETS = Path(__file__).parent / "assets"



def safe_json_for_script(data) -> str:
    """JSON sur a inserer dans une balise script."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (
        payload
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


MATIERES = [
    {
        "cle": "cst", "nom": "Mathématique — CST (4e sec.)",
        "parent": "063414",
        "competences": [("063410", "Résoudre"), ("063420", "Utiliser")],
        "exam": ["063420"],
    },
    {
        "cle": "sn", "nom": "Mathématique — SN (4e sec.)",
        "parent": "065426",
        "competences": [("065410", "Résoudre"), ("065420", "Utiliser")],
        "exam": ["065420"],
    },
    {
        "cle": "ts", "nom": "Mathématique — TS (4e sec.)",
        "parent": "064426",
        "competences": [("064410", "Résoudre"), ("064420", "Utiliser")],
        "exam": ["064420"],
    },
    {
        "cle": "st", "nom": "Science et technologie (4e sec.)",
        "parent": "055444",
        "competences": [("055410", "Théorie"), ("055420", "Pratique")],
        "exam": ["055410"],
    },
    {
        "cle": "ats", "nom": "Applications technologiques et scientifiques (4e sec.)",
        "parent": "057416",
        "competences": [("057410", "Théorie"), ("057420", "Pratique")],
        "exam": ["057410"],
    },
    {
        "cle": "histoire", "nom": "Histoire du Québec et du Canada (4e sec.)",
        "parent": "085404",
        "competences": [],
        "exam": ["085404"],
    },
    {
        "cle": "francais", "nom": "Français, langue d'enseignement (5e sec.)",
        "parent": "132506",
        "competences": [("132510", "Lire"), ("132520", "Écrire"),
                        ("132530", "Communiquer")],
        "exam": ["132520"],
    },
    {
        "cle": "anglais", "nom": "Anglais, langue seconde (5e sec.)",
        "parent": "134504",
        "competences": [("134510", "Communiquer"), ("134520", "Comprendre"),
                        ("134530", "Écrire")],
        "exam": ["134510", "134530"],
    },
]


SEUIL_PASSAGE = 60


SEUIL_SANS_RISQUE = 70


N_MIN_AFFICHAGE = 5


CHAMPS = [
    "ECO", "ANNEE", "CD_COURS", "COURS_PARENT", "DESCR_ABREG",
    "GROUPE", "ENSEIGNANT", "ENSEIGNANT_ID", "NB_ENSEIGNANTS",
    "N_BRUT", "SOM_BRUT", "SOMCAR_BRUT", "HIST_BRUT",
    "N_MODR", "SOM_MODR", "SOMCAR_MODR", "HIST_MODR",
    "N_MEQ", "SOM_MEQ", "SOMCAR_MEQ", "HIST_MEQ",
    "N_FINAL", "SOM_FINAL", "SOMCAR_FINAL", "HIST_FINAL",
    "N_MODERATION", "SOM_MODERATION", "SOMCAR_MODERATION", "HIST_MODERATION",
    "N_TRIPLE", "SOM_B", "SOM_M", "SOM_Q",
    "SOM_BB", "SOM_MM", "SOM_QQ", "SOM_BM", "SOM_BQ", "SOM_MQ",
    "ELEVES_JOINT", "ELEVES_MODERATION_JOINT",
    "N_BRUT_ABS", "SOM_BRUT_ABS", "SOMCAR_BRUT_ABS", "HIST_BRUT_ABS",
    "N_MODR_ABS", "SOM_MODR_ABS", "SOMCAR_MODR_ABS", "HIST_MODR_ABS",
    "N_FINAL_ABS", "SOM_FINAL_ABS", "SOMCAR_FINAL_ABS", "HIST_FINAL_ABS",
]


_CHAMPS_JSON = {"HIST_BRUT", "HIST_MODR", "HIST_MEQ", "HIST_FINAL",
                "HIST_MODERATION", "ELEVES_JOINT", "ELEVES_MODERATION_JOINT",
                "HIST_BRUT_ABS", "HIST_MODR_ABS", "HIST_FINAL_ABS"}


CHAMPS_QUESTIONS = [
    "ECO", "ANNEE", "CD_COURS", "COURS_PARENT",
    "GROUPE", "ENSEIGNANT", "ENSEIGNANT_ID", "NB_ENSEIGNANTS",
    "TYPE_QUEST", "NO_QUEST", "SCORE_MAX", "N", "SOM", "SOMCAR",
]


CHAMPS_PERM = [
    "ECO", "ANNEE", "CD_COURS", "ENSEIGNANT_ID", "TYPE_QUEST", "NO_QUEST",
    "N", "ECART", "P", "Q",
]


SEUIL_SIGNIF = 0.05


TITRE_DEFAUT = "Épreuves ministérielles — rapport détaillé"


def _decoder(valeur, champ):
    """Decode les champs stockes en JSON."""
    if champ not in _CHAMPS_JSON:
        return valeur
    if not valeur:
        return None
    if isinstance(valeur, (list, dict)):
        return valeur
    try:
        return json.loads(valeur)
    except (TypeError, ValueError):
        return None


def build_payloads(rows: list[dict], rows_questions: list[dict] | None = None,
                   rows_perm: list[dict] | None = None) -> dict:
    """Charge utile du rapport, a partir des lignes de calculs.py."""
    codes_connus = set()
    for m in MATIERES:
        codes_connus.add(m["parent"])
        codes_connus |= {c for c, _ in m["competences"]}

    cellules = []
    ecoles: dict = {}
    annees = set()
    ignorees = 0

    for r in rows:
        code = str(r.get("CD_COURS") or "").strip()
        if code not in codes_connus:
            ignorees += 1
            continue
        try:
            eco = int(r["ECO"])
            annee = int(r["ANNEE"])
        except (TypeError, ValueError, KeyError):
            ignorees += 1
            continue

        annees.add(annee)
        if eco not in ecoles:
            ecoles[eco] = str(r.get("NOM_ECO") or "").strip() or f"École {eco}"

        cellules.append([_decoder(r.get(c), c) for c in CHAMPS])

    cellules_questions = []
    ignorees_questions = 0
    for r in rows_questions or []:
        code = str(r.get("CD_COURS") or "").strip()
        if code not in codes_connus:
            ignorees_questions += 1
            continue
        try:
            eco = int(r["ECO"])
            annee = int(r["ANNEE"])
        except (TypeError, ValueError, KeyError):
            ignorees_questions += 1
            continue
        if not r.get("SCORE_MAX"):
            ignorees_questions += 1
            continue
        ligne = [r.get(c) for c in CHAMPS_QUESTIONS]
        ligne[CHAMPS_QUESTIONS.index("ECO")] = eco
        ligne[CHAMPS_QUESTIONS.index("ANNEE")] = annee
        cellules_questions.append(ligne)

    cellules_perm = []
    for r in rows_perm or []:
        code = str(r.get("CD_COURS") or "").strip()
        if code not in codes_connus:
            continue
        try:
            eco = int(r["ECO"])
            annee = int(r["ANNEE"])
        except (TypeError, ValueError, KeyError):
            continue
        ligne = [r.get(c) for c in CHAMPS_PERM]
        ligne[CHAMPS_PERM.index("ECO")] = eco
        ligne[CHAMPS_PERM.index("ANNEE")] = annee
        cellules_perm.append(ligne)

    return {
        "cellules": cellules,
        "cellules_questions": cellules_questions,
        "cellules_perm": cellules_perm,
        "ecoles": [{"id": e, "nom": n} for e, n in sorted(ecoles.items())],
        "annees": sorted(annees),
        "matieres": MATIERES,
        "ignorees": ignorees,
        "ignorees_questions": ignorees_questions,
    }


def _esc_html(texte: str) -> str:
    """Echappe un texte pour le HTML."""
    return (texte.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))


def build_html(payloads: dict, questions_disponibles: bool = False,
               payloads_g85: dict | None = None, export: dict | None = None,
               nom_css: str = "Centre de services", groupes_exclus=(),
               noms_courts: dict | None = None) -> str:
    """Rend le rapport.

    payloads_g85 : variante incluant les groupes exclus.
    export : None pour le rapport du centre de services (menus complets), sinon
    {"type": "enseignant"|"ecole", "ecole", "enseignant", "titre", "g85", "absents"}.
    Il fige les menus ; la confidentialite vient des payloads, deja reduits.
    """
    payloads_g85 = payloads_g85 or payloads
    lire = lambda nom: (ASSETS / nom).read_text(encoding="utf-8")
    groupes = ", ".join(sorted(groupes_exclus))

    html = lire("gabarit.html")
    for cle, valeur in (
        ("__NOM_CSS__", _esc_html(nom_css)),
        ("__GROUPES_EXCLUS__", _esc_html(groupes)),
        ("__STYLE_GROUPES_EXCLUS__", "" if groupes else ' style="display:none"'),
        ("__NOMS_COURTS_JSON__", safe_json_for_script(noms_courts or {})),
        ("__TITRE__", _esc_html((export or {}).get("titre") or TITRE_DEFAUT)),
        ("__EXPORT_MODE_JSON__", safe_json_for_script(export)),
        ("__CSS_TEXT__", lire("styles.css")),
        ("__CSS_PARTAGE__", lire("partage.css")),
        ("__EXPORT_CSS__", lire("export.css")),
        ("__EXPORT_JS__", lire("export.js")),
        ("__CELLULES_JSON__", safe_json_for_script(payloads["cellules"])),
        ("__CELLULES_G85_JSON__", safe_json_for_script(payloads_g85["cellules"])),
        ("__CELLULES_QUESTIONS_JSON__", safe_json_for_script(payloads.get("cellules_questions") or [])),
        ("__CELLULES_QUESTIONS_G85_JSON__", safe_json_for_script(payloads_g85.get("cellules_questions") or [])),
        ("__CHAMPS_QUESTIONS_JSON__", safe_json_for_script(CHAMPS_QUESTIONS)),
        ("__CELLULES_PERM_JSON__", safe_json_for_script(payloads.get("cellules_perm") or [])),
        ("__CHAMPS_PERM_JSON__", safe_json_for_script(CHAMPS_PERM)),
        ("__SEUIL_SIGNIF_JSON__", safe_json_for_script(SEUIL_SIGNIF)),
        ("__ECOLES_JSON__", safe_json_for_script(payloads["ecoles"])),
        ("__ANNEES_JSON__", safe_json_for_script(payloads["annees"])),
        ("__MATIERES_JSON__", safe_json_for_script(payloads["matieres"])),
        ("__CHAMPS_JSON__", safe_json_for_script(CHAMPS)),
        ("__SEUIL_PASSAGE_JSON__", safe_json_for_script(SEUIL_PASSAGE)),
        ("__SEUIL_SANS_RISQUE_JSON__", safe_json_for_script(SEUIL_SANS_RISQUE)),
        ("__SEUIL_SANS_RISQUE__", str(SEUIL_SANS_RISQUE)),
        ("__OBJECTIFS_PASSAGE_JSON__", "{}"),
        ("__N_MIN_JSON__", safe_json_for_script(N_MIN_AFFICHAGE)),
        ("__QUESTIONS_JSON__", safe_json_for_script(bool(questions_disponibles))),
        ("__GENERATED_AT__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("__APP_VERSION__", APP_VERSION),
    ):
        html = html.replace(cle, valeur)
    return html
