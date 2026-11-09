#!/usr/bin/env python3
"""Cree des classeurs au format Charlemagne. TOUTES LES DONNEES SONT INVENTEES.

Usage : python exemple/generer_exemple.py [dossier]
Organismes : prefixe fictif 999 (ecoles 1 et 2) ; 888 simule un autre organisme.
"""
import random
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

COLONNES = ["CD_PERMN", "NOM", "PRENM", "CATGR_EPREU", "CD_ORGNS", "CD_COURS", "NO_SEQNC_DECLR",
            "TYPE_FORMT", "SECTR_ENSEI", "AN_OBTEN_RESLT", "SESN_OBTEN_RESLT", "DT_OBTEN_RESLT",
            "REGM_PEDGQ_ORIGN", "NO_GROUP_ELEVE", "NOTE_ECOLE_BRUT", "NOTE_ECOLE_MODR",
            "NOTE_MINST_BRUT", "NOTE_MINST_CONVR", "RESLT_FINAL", "REUST_COURS"]
COLONNES_Q = ["NO_SEQNC_RESLT_EPREU", "CD_PERMN", "NOM", "PRENM", "CD_ORGNS", "CD_COURS",
              "NO_GROUP_ELEVE", "AN_EPREU", "SESN_EPREU", "DT_OBTEN_RESLT", "TYPE_QUEST",
              "NO_QUEST", "RESLT_QUEST"]

# onglet : (cours, competences, code porteur de l'epreuve)
COURS = {
    "CST": ("063414", ["063410", "063420"], "063420"),
    "SN": ("065426", ["065410", "065420"], "065420"),
    "Sc": ("055444", ["055410", "055420"], "055410"),
    "His": ("085404", [], "085404"),
    "Fra": ("132506", ["132510", "132520", "132530"], "132520"),
    "Ang": ("134504", ["134510", "134520", "134530"], "134530"),
}
ANNEES = (2024, 2025)                  # annees civiles des passations de juin
ECOLES = (999001, 999002)
GROUPES = (41, 42, 43)
ELEVES_PAR_GROUPE = 18


def borne(x):
    return max(0, min(100, round(x)))


def creer(dossier: Path) -> list[Path]:
    dossier.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260101)
    resultats = openpyxl.Workbook()
    resultats.remove(resultats.active)
    questions = openpyxl.Workbook()
    feuille_q = questions.active
    feuille_q.title = "Feuil1"
    feuille_q.append(COLONNES_Q)
    corrige = {q: rng.choice("ABCD") for q in range(1, 7)}
    seq = 0

    for onglet, (parent, competences, porteur) in COURS.items():
        ws = resultats.create_sheet(onglet)
        ws.append(COLONNES)
        for an in ANNEES:
            date = datetime(an, 6, 15)
            for ecole in ECOLES:
                for groupe in GROUPES:
                    for k in range(ELEVES_PAR_GROUPE):
                        seq += 1
                        code = f"TEST{seq:08d}"
                        nom, prenom = f"Fictif{seq}", f"Eleve{seq}"
                        base = rng.gauss(72 + (groupe - 42) * 3, 11)
                        absent = k == 0 and groupe == 41
                        brut = borne(base + rng.gauss(0, 4))
                        modr = borne(brut - rng.gauss(2, 2))
                        meq = borne(base + rng.gauss(-3, 6))
                        tete = [code, nom, prenom, None, str(ecole)]
                        finale = borne((modr + meq) / 2)
                        if competences:  # Sommaire : sans groupe, comme dans Charlemagne
                            ws.append(tete + [parent, "1", "J", "S", an, 6, date, "R"]
                                      + [None, None, None, None, None, finale,
                                         "R" if finale >= 60 else "E"])
                        for c in competences:
                            if c != porteur:
                                ws.append(tete + [c, "1", "J", "S", an, 6, date, "R", str(groupe),
                                                  None, None, None, None, borne(base), None])
                        ws.append(tete + [porteur, "1", "J", "S", an, 6, date, "R", str(groupe), brut,
                                          modr, "ABS" if absent else meq, None if absent else meq,
                                          "ABS" if absent else finale, None])
                        if k == 1:  # reprise d'aout : doit etre ecartee
                            ws.append(tete + [porteur, "1", "J", "S", an, 8, datetime(an, 8, 10), "R",
                                              str(groupe), brut, modr, 99.5, 99.5, 99.5, None])
                        if k == 2:  # autre organisme : doit etre ecarte
                            ws.append([code, nom, prenom, None, "888123", porteur, "1", "J", "S", an, 6, date,
                                       "R", str(groupe), brut, modr, 98.5, 98.5, 98.5, None])
                        if onglet == "Sc" and an == ANNEES[-1] and not absent:
                            niveau = (base - 40) / 60
                            ident = [seq, code, nom, prenom, ecole, int(porteur), groupe, an, 6, date]
                            for q in range(1, 7):
                                ok = rng.random() < niveau
                                lettre = corrige[q] if ok else rng.choice("ABCD")
                                feuille_q.append(ident + ["OB", q, lettre])
                            for q in range(7, 16):
                                feuille_q.append(ident + ["DC", q, min(4, max(0, round(rng.gauss(niveau * 4, 1))))])

    chemins = [dossier / "exemple_resultats.xlsx", dossier / "exemple_par_question.xlsx"]
    resultats.save(chemins[0])
    questions.save(chemins[1])
    return chemins


if __name__ == "__main__":
    cible = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    for c in creer(cible):
        print(c)
