"""Lecture des classeurs Charlemagne vers une base SQLite EN MEMOIRE.

Rien n'est ecrit sur le disque : un classeur protege est dechiffre en memoire,
et la base disparait a la fermeture de l'application.

Le type d'un onglet se reconnait a ses colonnes, pas au nom du fichier :
  - RESLT_FINAL -> resultats aux epreuves (table MEQ) ;
  - NO_QUEST et RESLT_QUEST -> reponses par question (table MEQ_QUESTIONS).
"""
from __future__ import annotations

import io
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import msoffcrypto
import openpyxl
from msoffcrypto.exceptions import InvalidKeyError

from .calculs import CODES_RETENUS, _code_cours_question

COLONNES_MEQ = (
    "CD_PERMN", "NOM", "PRENM", "CD_ORGNS", "CD_COURS", "AN_OBTEN_RESLT", "DT_OBTEN_RESLT",
    "NO_GROUP_ELEVE", "NOTE_ECOLE_BRUT", "NOTE_ECOLE_MODR", "NOTE_MINST_CONVR", "RESLT_FINAL",
)
COLONNES_QUESTIONS = (
    "CD_PERMN", "CD_ORGNS", "CD_COURS", "NO_GROUP_ELEVE", "AN_EPREU", "SESN_EPREU",
    "DT_OBTEN_RESLT", "TYPE_QUEST", "NO_QUEST", "RESLT_QUEST",
)
REQUISES_MEQ = {"CD_PERMN", "CD_ORGNS", "CD_COURS", "DT_OBTEN_RESLT", "RESLT_FINAL"}
REQUISES_QUESTIONS = {"CD_PERMN", "CD_ORGNS", "CD_COURS", "TYPE_QUEST", "NO_QUEST", "RESLT_QUEST"}
ALIAS = {"SCORE": "RESLT_QUEST"}
LIGNES_ENTETE_MAX = 20
TAILLE_LOT = 5000


class ErreurLecture(Exception):
    """Message destine a l'utilisateur."""


@dataclass
class Analyse:
    conn: sqlite3.Connection
    lignes_resultats: int = 0
    lignes_questions: int = 0
    prefixes: Counter = field(default_factory=Counter)
    onglets_ignores: list = field(default_factory=list)


def _source(chemin: Path, mot_de_passe: str):
    """Le chemin d'un classeur en clair, ou sa copie dechiffree en memoire."""
    with open(chemin, "rb") as fh:
        try:
            office = msoffcrypto.OfficeFile(fh)
            chiffre = office.is_encrypted()
        except Exception:  # pas un conteneur OLE : classeur ordinaire
            chiffre = False
        if not chiffre:
            return chemin
        if not mot_de_passe:
            raise ErreurLecture(f"{chemin.name} est protégé : indiquez son mot de passe.")
        memoire = io.BytesIO()
        try:
            office.load_key(password=mot_de_passe, verify_password=True)
            office.decrypt(memoire)
        except InvalidKeyError:
            raise ErreurLecture(f"Mot de passe incorrect pour {chemin.name}.") from None
    memoire.seek(0)
    return memoire


def _texte(valeur):
    if valeur is None:
        return None
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat(sep=" ") if isinstance(valeur, datetime) else valeur.isoformat()
    texte = str(valeur).strip()
    return texte or None


def _entete(rangees) -> dict | None:
    """{colonne: indice} de la ligne d'en-tete, cherchee dans les premieres lignes."""
    for _ in range(LIGNES_ENTETE_MAX):
        rangee = next(rangees, None)
        if rangee is None:
            return None
        noms = [str(c).strip().upper() if c is not None else "" for c in rangee]
        if "CD_PERMN" in noms and "CD_COURS" in noms:
            return {ALIAS.get(n, n): i for i, n in enumerate(noms) if n}
    return None


def _inserer(conn, table, colonnes, lignes):
    marques = ", ".join("?" * len(colonnes))
    conn.executemany(f'INSERT INTO "{table}" VALUES ({marques})', lignes)


def _prefixe(cd_orgns) -> str:
    try:
        return str(int(float(cd_orgns)))[:3]
    except (TypeError, ValueError):
        return ""


def _lire_onglet(ws, analyse: Analyse, nom_fichier: str) -> None:
    rangees = ws.iter_rows(values_only=True)
    entete = _entete(rangees)
    colonnes_presentes = set(entete or ())
    if REQUISES_MEQ <= colonnes_presentes:
        table, colonnes = "MEQ", COLONNES_MEQ
    elif REQUISES_QUESTIONS <= colonnes_presentes:
        table, colonnes = "MEQ_QUESTIONS", COLONNES_QUESTIONS
    else:
        analyse.onglets_ignores.append(f"{nom_fichier} / {ws.title}")
        return

    i_cours = colonnes.index("CD_COURS")
    i_orgns = colonnes.index("CD_ORGNS")
    i_score = colonnes.index("RESLT_QUEST") if table == "MEQ_QUESTIONS" else None
    positions = [entete.get(c) for c in colonnes]
    lot, total = [], 0
    for rangee in rangees:
        ligne = [_texte(rangee[p]) if p is not None and p < len(rangee) else None
                 for p in positions]
        code = _code_cours_question(ligne[i_cours])
        if code not in CODES_RETENUS:
            continue  # le releve porte aussi tous les cours sans epreuve
        ligne[i_cours] = code
        if i_score is not None and ligne[i_score]:
            ligne[i_score] = ligne[i_score].replace(",", ".")
        lot.append(ligne)
        total += 1
        if table == "MEQ":
            analyse.prefixes[_prefixe(ligne[i_orgns])] += 1
        if len(lot) >= TAILLE_LOT:
            _inserer(analyse.conn, table, colonnes, lot)
            lot = []
    if lot:
        _inserer(analyse.conn, table, colonnes, lot)
    if table == "MEQ":
        analyse.lignes_resultats += total
    else:
        analyse.lignes_questions += total
    print(f"  {nom_fichier} / {ws.title} : {total} ligne(s) retenue(s) ({table})")


def charger_fichiers(chemins, mot_de_passe: str = "") -> Analyse:
    """Charge des classeurs Charlemagne. Leve ErreurLecture si rien n'est exploitable."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    for table, colonnes in (("MEQ", COLONNES_MEQ), ("MEQ_QUESTIONS", COLONNES_QUESTIONS)):
        definitions = ", ".join(f'"{c}" TEXT' for c in colonnes)
        conn.execute(f'CREATE TABLE "{table}" ({definitions})')

    analyse = Analyse(conn=conn)
    try:
        for chemin in map(Path, chemins):
            try:
                wb = openpyxl.load_workbook(_source(chemin, mot_de_passe), read_only=True, data_only=True)
            except ErreurLecture:
                raise
            except Exception as e:
                raise ErreurLecture(f"{chemin.name} est illisible ({type(e).__name__}).") from None
            try:
                for ws in wb.worksheets:
                    _lire_onglet(ws, analyse, chemin.name)
            finally:
                wb.close()
        conn.commit()
        if not analyse.lignes_resultats:
            raise ErreurLecture("Aucun résultat d'épreuve trouvé. Un onglet doit contenir les colonnes "
                                + ", ".join(sorted(REQUISES_MEQ)) + ".")
    except BaseException:
        conn.close()
        raise
    return analyse
