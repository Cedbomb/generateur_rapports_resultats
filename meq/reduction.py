"""Reduit le payload complet a ce qu'un destinataire a le droit de voir.

Masquer un menu ne protege rien : tout ce qui est dans le payload se lit dans
la source de la page. Les autres ecoles et le reste de l'ecole sont donc
FUSIONNES avant le rendu, ce que permettent des statistiques additives.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from .rapport import CHAMPS, CHAMPS_PERM, CHAMPS_QUESTIONS



PART_MIN_COENSEIGNANT = 0.25


I = {c: i for i, c in enumerate(CHAMPS)}


IQ = {c: i for i, c in enumerate(CHAMPS_QUESTIONS)}


IP = {c: i for i, c in enumerate(CHAMPS_PERM)}


ECO_AUTRES = 0


_COPIES = {"ECO", "ANNEE", "CD_COURS", "COURS_PARENT", "DESCR_ABREG"}


_VIDES = {"GROUPE": "", "ENSEIGNANT": "", "ENSEIGNANT_ID": "", "NB_ENSEIGNANTS": 0,
          "ELEVES_JOINT": None, "ELEVES_MODERATION_JOINT": None}


_COPIES_Q = {"ECO", "ANNEE", "CD_COURS", "COURS_PARENT", "TYPE_QUEST", "NO_QUEST", "SCORE_MAX"}


_VIDES_Q = {"GROUPE": "", "ENSEIGNANT": "", "ENSEIGNANT_ID": "", "NB_ENSEIGNANTS": 0}


def enseignants_par_cellule(lignes: list[dict], annee: int) -> tuple[dict, dict]:
    """({cellule: enseignants}, {(ecole, id): nom}) pour l'annee exportee."""
    porteurs: dict[tuple, set] = defaultdict(set)
    noms: dict[tuple, str] = {}
    for r in lignes:
        if int(r["ANNEE"]) != annee:
            continue
        eco = int(r["ECO"])
        cle = (eco, int(r["ANNEE"]), str(r["CD_COURS"]).strip(), r["GROUPE"])
        majoritaire = r.get("ENSEIGNANT_ID") or ""
        if majoritaire:
            porteurs[cle].add(majoritaire)
            noms[(eco, majoritaire)] = r.get("ENSEIGNANT") or ""
        tous = json.loads(r["ENSEIGNANTS"]) if r.get("ENSEIGNANTS") else []
        total = sum(c for _, _, c in tous)
        for ens_id, nom, c in tous:
            if total and c / total >= PART_MIN_COENSEIGNANT:
                porteurs[cle].add(ens_id)
                noms[(eco, ens_id)] = nom
    return dict(porteurs), noms


def fusionner(cellules: list, eco) -> list:
    """Une cellule anonyme par (annee, cours), sous l'ECO donne."""
    lots: dict[tuple, list] = defaultdict(list)
    for c in cellules:
        lots[(c[I["ANNEE"]], c[I["CD_COURS"]])].append(c)
    sortie = []
    for lot in lots.values():
        s = [None] * len(CHAMPS)
        for champ, i in I.items():
            if champ in _COPIES:
                s[i] = lot[0][i]
            elif champ in _VIDES:
                s[i] = _VIDES[champ]
            elif champ.startswith("HIST_"):
                h: dict = defaultdict(int)
                for c in lot:
                    for v, n in c[i] or []:
                        h[v] += n
                s[i] = [[v, n] for v, n in sorted(h.items())] or None
            else:
                vals = [c[i] for c in lot if c[i] is not None]
                s[i] = sum(vals) if vals else None
        s[I["ECO"]] = eco
        sortie.append(s)
    return sortie


def fusionner_questions(cellules: list, eco) -> list:
    """Une cellule anonyme par (annee, cours, type, question, bareme)."""
    lots: dict[tuple, list] = defaultdict(list)
    for c in cellules:
        lots[tuple(c[IQ[k]] for k in ("ANNEE", "CD_COURS", "TYPE_QUEST",
                                       "NO_QUEST", "SCORE_MAX"))].append(c)
    sortie = []
    for lot in lots.values():
        s = [None] * len(CHAMPS_QUESTIONS)
        for champ, i in IQ.items():
            if champ in _COPIES_Q:
                s[i] = lot[0][i]
            elif champ in _VIDES_Q:
                s[i] = _VIDES_Q[champ]
            else:
                vals = [c[i] for c in lot if c[i] is not None]
                s[i] = sum(vals) if vals else None
        s[IQ["ECO"]] = eco
        sortie.append(s)
    return sortie


def codes_matiere(m: dict) -> set:
    """Codes du cours et de ses competences."""
    return {m["parent"]} | {c for c, _ in m["competences"]}


class Contexte:
    """Le payload complet d'une variante, et ce qu'il faut pour le reduire."""

    def __init__(self, payload: dict, porteurs: dict, noms_ens: dict, annee: int):
        self.payload = payload
        self.porteurs = porteurs
        self.noms_ens = noms_ens
        self.annee = annee

    def _porteurs(self, eco, cours, groupe) -> set:
        return self.porteurs.get((eco, self.annee, str(cours).strip(), groupe), set())

    def _du_cours(self, m):
        codes = codes_matiere(m)
        cel = [c for c in self.payload["cellules"]
               if c[I["ANNEE"]] == self.annee and c[I["CD_COURS"]] in codes]
        celq = [c for c in self.payload["cellules_questions"]
                if c[IQ["ANNEE"]] == self.annee and c[IQ["CD_COURS"]] in codes]
        return cel, celq

    def _cadre(self, m, eco, cellules, cellules_q, perms) -> dict:
        nom = next((e["nom"] for e in self.payload["ecoles"] if e["id"] == eco), f"École {eco}")
        return {"cellules": cellules, "cellules_questions": cellules_q,
                "cellules_perm": perms, "ecoles": [{"id": eco, "nom": nom}],
                "annees": [self.annee], "matieres": [m]}

    def enseignant(self, m: dict, eco: int, ens_id: str) -> dict:
        cel, celq = self._du_cours(m)
        nom = self.noms_ens.get((eco, ens_id), "")
        siens, reste, autres = [], [], []
        for c in cel:
            if c[I["ECO"]] != eco:
                autres.append(c)
            elif ens_id in self._porteurs(eco, c[I["CD_COURS"]], c[I["GROUPE"]]):
                c = list(c)
                c[I["ENSEIGNANT_ID"]], c[I["ENSEIGNANT"]] = ens_id, nom
                siens.append(c)
            else:
                reste.append(c)
        siensq, resteq, autresq = [], [], []
        for c in celq:
            if c[IQ["ECO"]] != eco:
                autresq.append(c)
            elif ens_id in (self._porteurs(eco, c[IQ["CD_COURS"]], c[IQ["GROUPE"]])
                            or {c[IQ["ENSEIGNANT_ID"]]}):
                c = list(c)
                c[IQ["ENSEIGNANT_ID"]], c[IQ["ENSEIGNANT"]] = ens_id, nom
                siensq.append(c)
            else:
                resteq.append(c)
        perms = [p for p in self.payload["cellules_perm"]
                 if p[IP["ECO"]] == eco and p[IP["ENSEIGNANT_ID"]] == ens_id
                 and p[IP["ANNEE"]] == self.annee and p[IP["CD_COURS"]] in codes_matiere(m)]
        return self._cadre(
            m, eco,
            siens + fusionner(reste, eco) + fusionner(autres, ECO_AUTRES),
            siensq + fusionner_questions(resteq, eco) + fusionner_questions(autresq, ECO_AUTRES),
            perms)

    def ecole(self, m: dict, eco: int) -> dict:
        cel, celq = self._du_cours(m)
        siens, autres = [], []
        for c in cel:
            if c[I["ECO"]] != eco:
                autres.append(c)
                continue
            c = list(c)
            for champ in ("GROUPE", "ENSEIGNANT", "ENSEIGNANT_ID",
                          "NB_ENSEIGNANTS", "ELEVES_MODERATION_JOINT"):
                c[I[champ]] = _VIDES[champ]
            siens.append(c)
        return self._cadre(
            m, eco,
            siens + fusionner(autres, ECO_AUTRES),
            fusionner_questions([c for c in celq if c[IQ["ECO"]] == eco], eco)
            + fusionner_questions([c for c in celq if c[IQ["ECO"]] != eco], ECO_AUTRES),
            [])

    def enseignants_de(self, m: dict, eco: int) -> list[str]:
        cel, _ = self._du_cours(m)
        ids = set()
        for c in cel:
            if c[I["ECO"]] == eco:
                ids |= self._porteurs(eco, c[I["CD_COURS"]], c[I["GROUPE"]])
        return sorted((i for i in ids if self.noms_ens.get((eco, i))),
                      key=lambda i: self.noms_ens[(eco, i)])

    def sans_enseignant(self, m: dict, eco: int) -> list[tuple[str, str, int]]:
        cel, _ = self._du_cours(m)
        return sorted(
            (c[I["CD_COURS"]], c[I["GROUPE"]], c[I["N_FINAL"]] or 0)
            for c in cel
            if c[I["ECO"]] == eco and c[I["CD_COURS"]] != m["parent"]
            and not any(self.noms_ens.get((eco, i))
                        for i in self._porteurs(eco, c[I["CD_COURS"]], c[I["GROUPE"]])))


def differe_g85(red: dict, red_g85: dict) -> bool:
    """La bascule des groupes exclus change-t-elle ce fichier ?"""
    return (red["cellules"] != red_g85["cellules"]
            or red["cellules_questions"] != red_g85["cellules_questions"])


def a_absents(red: dict) -> bool:
    """Ce fichier compte-t-il un absent a l'epreuve ?"""
    return any(c[I[f"N_{p}_ABS"]] for c in red["cellules"] for p in ("BRUT", "MODR", "FINAL"))


def noms_eleves(cellules: list) -> set:
    """Noms d'eleves presents dans des cellules."""
    noms = set()
    for c in cellules:
        for champ in ("ELEVES_JOINT", "ELEVES_MODERATION_JOINT"):
            for pt in c[I[champ]] or []:
                noms.add(pt[0])
    return noms


def verifier_fichier(html: str, permis_eleves: set, tous_eleves: set,
                     permis_ens: set, tous_ens: set) -> list[str]:
    """Noms presents dans le fichier sans y avoir droit."""
    fuites = []
    for nom in sorted(tous_eleves - permis_eleves):
        if json.dumps(nom, ensure_ascii=False) in html:
            fuites.append(f"élève {nom}")
    for nom in sorted(tous_ens - permis_ens):
        if nom and json.dumps(nom, ensure_ascii=False) in html:
            fuites.append(f"enseignant {nom}")
    return fuites


def nom_fichier(texte: str) -> str:
    """Texte utilisable comme nom de fichier."""
    return re.sub(r'[<>:"/\\|?*]+', "-", texte).strip(" .")
