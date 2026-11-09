"""Modele Excel de la correspondance groupe -> enseignant : creation et lecture."""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .calculs import _code_cours_question, _normaliser_groupe
from .generation import NOMS_COURTS
from .lecture import ErreurLecture, _source
from .rapport import MATIERES

ONGLET = "Enseignants"
ENTETES = ("Code école", "École", "Code cours", "Groupe", "Enseignant(s)")
LARGEURS = (12, 34, 16, 10, 36)
LIGNES_VALIDEES = 2000
LIGNES_ENTETE_MAX = 20
ALIAS_COLONNES = {"code ecole": "code", "ecole": "ecole", "code cours": "matiere",
                  "code de cours": "matiere", "matiere": "matiere", "groupe": "groupe",
                  "enseignant(s)": "enseignant", "enseignant": "enseignant"}
CONSIGNES = (
    "Une ligne par groupe : le code de l'école (ou son nom), le code de cours, le groupe et l'enseignant.",
    "Plusieurs enseignants pour un groupe : séparez les noms par « ; » ou ajoutez une ligne par enseignant.",
    "Forme conseillée pour les noms : Prénom N.",
    "Une ligne sans enseignant est ignorée. Le groupe reste compté dans les rapports, sans rapport individuel.",
    "Le code et le nom des écoles sont ceux de l'onglet Paramètres de l'application.",
    "",
    "Exemple (fictif) : 12 | École Exemple | 063414 | 41 | Prénom N.",
    "",
    "Ce fichier contient des noms d'enseignants : conservez-le dans un emplacement sécurisé.",
    "",
    "Codes de cours :",
    *(f"{m['parent']} : {m['nom']}" for m in MATIERES),
)


def _cle(texte) -> str:
    """Texte comparable : sans accents, sans casse, espaces normalises."""
    decompose = unicodedata.normalize("NFKD", str(texte or ""))
    return " ".join("".join(c for c in decompose if not unicodedata.combining(c)).casefold().split())


def _matieres_connues() -> dict:
    """Valeurs acceptees : code du cours ou d'une competence, nom complet, nom court, cle."""
    connues = {}
    for m in MATIERES:
        codes = [m["parent"], *(c for c, _ in m["competences"])]
        for valeur in (*codes, m["cle"], m["nom"], NOMS_COURTS[m["cle"]]):
            connues[_cle(valeur)] = m["cle"]
    return connues


def _matiere_saisie(valeur) -> str:
    """Valeur comparable ; Excel retire le zero initial d'un code saisi en nombre."""
    return _cle(_code_cours_question(valeur))


def creer_modele(chemin, groupes=(), noms_ecoles=None, existants=None) -> None:
    """Ecrit le modele. groupes : [(eco, cle de matiere, groupe)], vide pour un modele vierge."""
    noms_ecoles, existants = noms_ecoles or {}, existants or {}
    code_cours = {m["cle"]: m["parent"] for m in MATIERES}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = ONGLET
    ws.append(ENTETES)
    for i, (cellule, largeur) in enumerate(zip(ws[1], LARGEURS), start=1):
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="4A5568")
        cellule.alignment = Alignment(vertical="center")
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = largeur
    ws.freeze_panes = "A2"
    # Format texte : sinon Excel transforme 063414 en 63414.
    ws.column_dimensions["C"].number_format = "@"
    for eco, cle, groupe in groupes:
        ws.append([eco, noms_ecoles.get(eco, f"École {eco}"), code_cours[cle],
                   int(groupe) if str(groupe).isdigit() else groupe,
                   existants.get((eco, cle, groupe), "")])
        ws.cell(row=ws.max_row, column=3).number_format = "@"

    listes = wb.create_sheet("Listes")
    for code in code_cours.values():
        listes.append([code])
        listes.cell(row=listes.max_row, column=1).number_format = "@"
    listes.sheet_state = "hidden"
    liste_matieres = DataValidation(
        type="list", formula1=f"Listes!$A$1:$A${len(code_cours)}", allow_blank=True, showErrorMessage=True,
        errorTitle="Code cours", error="Choisissez un code de cours dans la liste.")
    liste_matieres.add(f"C2:C{LIGNES_VALIDEES}")
    ws.add_data_validation(liste_matieres)

    consignes = wb.create_sheet("Consignes")
    consignes.column_dimensions["A"].width = 110
    for ligne in CONSIGNES:
        consignes.append([ligne])
    wb.active = 0
    wb.save(chemin)


def _colonnes(rangees) -> tuple[dict, int] | None:
    """({champ: indice}, numero de la ligne d'en-tete), cherchee dans les premieres lignes."""
    for no in range(1, LIGNES_ENTETE_MAX + 1):
        rangee = next(rangees, None)
        if rangee is None:
            return None
        trouve = {ALIAS_COLONNES[_cle(c)]: i for i, c in enumerate(rangee) if _cle(c) in ALIAS_COLONNES}
        if {"matiere", "groupe", "enseignant"} <= set(trouve) and {"code", "ecole"} & set(trouve):
            return trouve, no
    return None


def _code_ecole(valeur) -> int | None:
    try:
        return int(float(str(valeur).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None


def lire_modele(chemin, groupes_connus, noms_ecoles=None) -> tuple[dict, list]:
    """({(eco, cle de matiere, groupe): "A; B"}, [motifs des lignes ignorees]).

    Un motif cite le numero de ligne et jamais le nom de l'enseignant.
    """
    chemin = Path(chemin)
    ecoles_par_nom = {_cle(n): e for e, n in (noms_ecoles or {}).items()}
    matieres = _matieres_connues()
    try:
        wb = openpyxl.load_workbook(_source(chemin, ""), read_only=True, data_only=True)
    except ErreurLecture:
        raise
    except Exception as e:
        raise ErreurLecture(f"{chemin.name} est illisible ({type(e).__name__}).") from None
    try:
        ws = wb[ONGLET] if ONGLET in wb.sheetnames else wb.worksheets[0]
        rangees = ws.iter_rows(values_only=True)
        entete = _colonnes(rangees)
        if entete is None:
            raise ErreurLecture(f"Colonnes introuvables dans {chemin.name}. Attendu : {', '.join(ENTETES)}.")
        pos, no_entete = entete

        noms: dict[tuple, list] = defaultdict(list)
        ignorees: list[str] = []
        for no, rangee in enumerate(rangees, start=no_entete + 1):
            val = lambda champ: rangee[pos[champ]] if champ in pos and pos[champ] < len(rangee) else None
            enseignant = str(val("enseignant") or "").strip()
            if not enseignant:
                continue
            eco = _code_ecole(val("code"))
            if eco is None:
                eco = ecoles_par_nom.get(_cle(val("ecole")))
            cle = matieres.get(_matiere_saisie(val("matiere")))
            groupe = _normaliser_groupe(val("groupe"))
            if eco is None:
                ignorees.append(f"Ligne {no} : école non reconnue.")
            elif cle is None:
                ignorees.append(f"Ligne {no} : code de cours non reconnu.")
            elif (eco, cle, groupe) not in groupes_connus:
                ignorees.append(f"Ligne {no} : école {eco}, {NOMS_COURTS[cle]}, groupe {groupe or '(vide)'} "
                                "absent des résultats de la dernière année.")
            else:
                liste = noms[(eco, cle, groupe)]
                for nom in (n.strip() for n in enseignant.split(";")):
                    if nom and nom.casefold() not in {x.casefold() for x in liste}:
                        liste.append(nom)
    finally:
        wb.close()
    return {k: "; ".join(v) for k, v in noms.items()}, ignorees
