"""Enchaine calculs, reduction et ecriture des rapports HTML."""
from __future__ import annotations

import contextlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import calculs, rapport
from .lecture import Analyse
from .rapport import MATIERES
from .reduction import (
    I,
    IP,
    IQ,
    Contexte,
    a_absents,
    codes_matiere,
    differe_g85,
    enseignants_par_cellule,
    nom_fichier,
    noms_eleves,
    verifier_fichier,
)

ELEVE_ANONYME = "Élève"
CODE_PERMANENT = re.compile(r"\b[A-Z]{4}\d{8}\b")
NOMS_COURTS = {"cst": "Math CST", "sn": "Math SN", "ts": "Math TS", "st": "Science", "ats": "ATS",
               "histoire": "Histoire", "francais": "Français", "anglais": "Anglais"}
MOTIF_NOM_CSS = re.compile(r"^[\w '’.\-]+$")


@dataclass
class Parametres:
    nom_css: str
    prefixe: str
    dossier: Path
    noms_ecoles: dict = field(default_factory=dict)   # {eco: nom}
    groupes_exclus: set = field(default_factory=set)
    cibles: dict = field(default_factory=dict)        # {cle de matiere: cible PEVR}
    enseignants: dict = field(default_factory=dict)   # {(eco, cle de matiere, groupe): "A; B"}
    inclure_noms: bool = False
    niveaux: set = field(default_factory=lambda: {"css", "ecole", "prof"})
    cours: set | None = None                          # codes de cours retenus ; None = tous


@dataclass
class Resultat:
    racine: Path
    ecrits: int = 0
    sans_enseignant: list = field(default_factory=list)
    fuites: list = field(default_factory=list)


def _matiere_du_parent(parent: str):
    return next((m for m in MATIERES if m["parent"] == parent), None)


def groupes_a_attribuer(analyse: Analyse, prefixe: str, noms_ecoles: dict | None = None):
    """(annee, [{eco, cle, matiere, groupe, effectif}]) de la derniere annee."""
    calculs.CTX.__init__(prefixe_organisme=prefixe, noms_ecoles=noms_ecoles or {})
    with contextlib.redirect_stdout(io.StringIO()):
        lignes = calculs.aggreger_detail(analyse.conn, inclure_groupe_85=True)
    if not lignes:
        return None, []
    annee = max(l["ANNEE"] for l in lignes)
    groupes: dict[tuple, int] = defaultdict(int)
    for l in lignes:
        m = _matiere_du_parent(l["COURS_PARENT"])
        # Un cours sans competences (histoire) porte ses groupes sur son propre code.
        if (m and l["ANNEE"] == annee and (l["CD_COURS"] != m["parent"] or not m["competences"])
                and l["GROUPE"] != "(sans groupe)"):
            cle = (l["ECO"], m["cle"], l["GROUPE"])
            groupes[cle] = max(groupes[cle], l["N_FINAL"] or 0)
    noms = {m["cle"]: m["nom"] for m in MATIERES}
    ordre = {m["cle"]: i for i, m in enumerate(MATIERES)}
    return annee, [
        {"eco": e, "cle": c, "matiere": noms[c], "groupe": g, "effectif": n}
        for (e, c, g), n in sorted(groupes.items(), key=lambda kv: (kv[0][0], ordre[kv[0][1]],
                                                                     kv[0][2].zfill(6)))
    ]


def ecoles_presentes(analyse: Analyse, prefixe: str) -> list[int]:
    calculs.CTX.__init__(prefixe_organisme=prefixe)
    ecoles = set()
    for (orgns,) in analyse.conn.execute("SELECT DISTINCT CD_ORGNS FROM MEQ"):
        eco = calculs.eco_de_organisme(orgns)
        if eco is not None:
            ecoles.add(eco)
    return sorted(ecoles)


def cours_presents(analyse: Analyse, prefixe: str) -> list[str]:
    """Codes de cours ayant des resultats pour ce prefixe, dans l'ordre des matieres."""
    calculs.CTX.__init__(prefixe_organisme=prefixe)
    presents = set()
    for code, orgns in analyse.conn.execute("SELECT DISTINCT CD_COURS, CD_ORGNS FROM MEQ"):
        if calculs.eco_de_organisme(orgns) is not None:
            presents.add(calculs.PARENT_DE_COMPETENCE.get(code, code))
    return [m["parent"] for m in MATIERES if m["parent"] in presents]


def _restreindre(payload: dict, matieres: list) -> dict:
    """Le payload limite aux matieres choisies."""
    codes = set().union(*(codes_matiere(m) for m in matieres))
    cellules = [c for c in payload["cellules"] if c[I["CD_COURS"]] in codes]
    ecoles_gardees = {c[I["ECO"]] for c in cellules}
    return dict(
        payload,
        cellules=cellules,
        cellules_questions=[c for c in payload["cellules_questions"] if c[IQ["CD_COURS"]] in codes],
        cellules_perm=[c for c in payload["cellules_perm"] if c[IP["CD_COURS"]] in codes],
        ecoles=[e for e in payload["ecoles"] if e["id"] in ecoles_gardees],
        annees=sorted({c[I["ANNEE"]] for c in cellules}),
        matieres=matieres,
    )


def _table_enseignants(p: Parametres, annee: int) -> dict:
    """Correspondance saisie -> {(eco, annee, parent, groupe): [(id, nom), ...]}."""
    parent_de = {m["cle"]: m["parent"] for m in MATIERES}
    ids: dict[tuple, str] = {}
    table: dict[tuple, list] = {}
    for (eco, cle, groupe), noms in p.enseignants.items():
        personnes = []
        for nom in (n.strip() for n in (noms or "").split(";")):
            if nom:
                ident = ids.setdefault((eco, nom.casefold()), f"E{len(ids) + 1}")
                personnes.append((ident, nom))
        if personnes:
            table[(eco, annee, parent_de[cle], str(groupe))] = personnes
    return table


def _anonymiser(cellules: list) -> list:
    sortie = []
    for c in cellules:
        c = list(c)
        for champ in ("ELEVES_JOINT", "ELEVES_MODERATION_JOINT"):
            if c[I[champ]]:
                c[I[champ]] = sorted([ELEVE_ANONYME, *pt[1:]] for pt in c[I[champ]])
        sortie.append(c)
    return sortie


def generer(analyse: Analyse, p: Parametres) -> Resultat:
    """Ecrit les rapports demandes. Un fichier qui echoue a la verification n'est pas ecrit."""
    annee, _groupes = groupes_a_attribuer(analyse, p.prefixe)
    if annee is None:
        raise ValueError("Aucun résultat retenu pour ce préfixe d'organisme.")

    ens = _table_enseignants(p, annee)
    calculs.CTX.__init__(prefixe_organisme=p.prefixe, groupes_exclus=frozenset(p.groupes_exclus),
                         noms_ecoles=p.noms_ecoles, enseignants_groupes=ens,
                         inclure_noms=p.inclure_noms)
    for m in MATIERES:
        m["pevr"] = p.cibles.get(m["cle"])
    choisies = [m for m in MATIERES if p.cours is None or m["parent"] in p.cours]
    if not choisies:
        raise ValueError("Aucun code de cours sélectionné.")
    codes_choisis = set().union(*(codes_matiere(m) for m in choisies))

    conn = analyse.conn
    lignes = calculs.aggreger_detail(conn)
    lignes_g85 = calculs.aggreger_detail(conn, inclure_groupe_85=True) if p.groupes_exclus else lignes
    prep = calculs.preparer_questions(conn)
    questions = calculs.aggreger_questions(conn, prep=prep)
    questions_g85 = (calculs.aggreger_questions(conn, inclure_groupe_85=True)
                     if p.groupes_exclus else questions)
    perms = []
    if ens and prep and ({"css", "prof"} & p.niveaux):
        print("Test de permutation par enseignant (peut prendre une minute)…")
        # Les eleves ne se permutent qu'a l'interieur d'une epreuve : retirer les
        # autres cours ne change aucun p.
        perms = calculs.aggreger_permutations(conn, prep=prep._replace(
            lignes=[(l, c) for l, c in prep.lignes if l.cd_cours in codes_choisis]))

    payload = rapport.build_payloads(lignes, questions, perms)
    payload_g85 = rapport.build_payloads(lignes_g85, questions_g85, perms)
    annee = max(payload["annees"])
    payload = _restreindre(payload, choisies)
    payload_g85 = _restreindre(payload_g85, choisies)
    if not payload["cellules"]:
        raise ValueError("Aucun résultat pour les codes de cours sélectionnés.")
    porteurs, noms_ens = enseignants_par_cellule(lignes + lignes_g85, annee)
    ctx = Contexte(payload, porteurs, noms_ens, annee)
    ctx_g85 = Contexte(payload_g85, porteurs, noms_ens, annee)
    tous_eleves = noms_eleves(payload["cellules"]) | noms_eleves(payload_g85["cellules"])
    tous_ens = set(noms_ens.values())

    res = Resultat(racine=p.dossier / f"Rapports_MEQ_{annee}-{annee + 1}")
    communs = {"questions_disponibles": bool(payload["cellules_questions"]), "nom_css": p.nom_css,
               "groupes_exclus": p.groupes_exclus}

    def ecrire(chemin: Path, red: dict, red_g85: dict, export: dict | None, permis_ens: set) -> None:
        if export is not None:
            export = dict(export, g85=differe_g85(red, red_g85), absents=a_absents(red))
        html = rapport.build_html(red, payloads_g85=red_g85, export=export, **communs)
        permis = noms_eleves(red["cellules"]) | noms_eleves(red_g85["cellules"])
        fuites = verifier_fichier(html, permis, tous_eleves, permis_ens, tous_ens)
        if CODE_PERMANENT.search(html):
            fuites.append("code permanent")
        if not p.inclure_noms and permis - {ELEVE_ANONYME}:
            fuites.append("nom d'élève")
        if fuites:
            res.fuites.append((chemin.name, fuites))
            return
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(html, encoding="utf-8")
        res.ecrits += 1

    if "css" in p.niveaux:
        # Le rapport le plus largement diffuse ne porte jamais de nom d'eleve.
        ecrire(res.racine / f"Rapport {nom_fichier(p.nom_css)}.html",
               dict(payload, cellules=_anonymiser(payload["cellules"])),
               dict(payload_g85, cellules=_anonymiser(payload_g85["cellules"])),
               None, tous_ens)

    if {"ecole", "prof"} & p.niveaux:
        for e in payload["ecoles"]:
            eco, nom_eco = e["id"], e["nom"]
            for m in choisies:
                cel, _ = ctx._du_cours(m)
                if not any(c[I["ECO"]] == eco for c in cel):
                    continue
                court = NOMS_COURTS[m["cle"]]
                dossier = res.racine / nom_fichier(nom_eco) / court
                periode = f"{annee}-{annee + 1}"
                if "ecole" in p.niveaux:
                    ecrire(dossier / f"{court} - École.html", ctx.ecole(m, eco), ctx_g85.ecole(m, eco),
                           {"type": "ecole", "ecole": eco, "enseignant": None,
                            "titre": f"{m['nom']} — {nom_eco} — {periode}"}, set())
                if "prof" in p.niveaux:
                    for i in ctx.enseignants_de(m, eco):
                        nom = noms_ens[(eco, i)]
                        ecrire(dossier / f"{court} - {nom_fichier(nom)}.html",
                               ctx.enseignant(m, eco, i), ctx_g85.enseignant(m, eco, i),
                               {"type": "enseignant", "ecole": eco, "enseignant": i,
                                "titre": f"{m['nom']} — {nom} ({nom_eco}) — {periode}"}, {nom})
                    res.sans_enseignant += [(nom_eco, m["nom"], *g)
                                            for g in ctx.sans_enseignant(m, eco)]
    return res
