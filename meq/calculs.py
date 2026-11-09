"""Agregation des epreuves ministerielles a partir des tables Charlemagne.

Les fonctions lisent une base SQLite EN MEMOIRE creee par lecture.py (tables
MEQ et MEQ_QUESTIONS) et produisent, par ecole x annee x cours x groupe, des
statistiques suffisantes : effectif, somme, somme des carres, histogramme.
Moyennes, ecarts-types et seuils se recalculent ensuite dans le rapport.

Regles de population :
  - seuls les cours a epreuve unique et leurs competences sont retenus ;
  - seule la passation de mai-juin compte (ni reprises, ni cours d'ete) ;
  - un resultat obtenu hors du centre de services est ecarte (CD_ORGNS) ;
  - un eleve dedouble garde la note finale la plus elevee.

Rien de ce module ne doit ecrire sur le disque.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple


@dataclass
class Reglages:
    """Ce qui varie d'un centre de services a l'autre."""
    prefixe_organisme: str = ""
    groupes_exclus: frozenset = frozenset()
    noms_ecoles: dict = field(default_factory=dict)      # {eco: nom}
    # {(eco, annee, cours parent, groupe): [(id enseignant, nom), ...]}
    enseignants_groupes: dict = field(default_factory=dict)
    inclure_noms: bool = False


CTX = Reglages()

ANNEE_DEBUT_DEFAUT = 2000
ANNEE_FIN_DEFAUT = 2100
ANNEE_MEQ_MIN = ANNEE_DEBUT_DEFAUT



MOIS_RETENUS = (5, 6)


COURS_A_EPREUVE = {
    "055444": "Science et technologie, 4e secondaire",
    "063414": "Mathématique — Culture, société et technique (CST), 4e secondaire",
    "065426": "Mathématique — Sciences naturelles (SN), 4e secondaire",
    "085404": "Histoire du Québec et du Canada, 4e secondaire",
    "132506": "Français, langue d'enseignement, 5e secondaire",
    "134504": "Anglais, langue seconde, 5e secondaire",
    "064426": "Mathématique — Technico-sciences (TS), 4e secondaire",
    "057416": "Applications technologiques et scientifiques, 4e secondaire",

}


COMPETENCES = {
    "055": {"10": "Théorie",
            "20": "Pratique"},
    "057": {"10": "Théorie",
            "20": "Pratique"},
    "063": {"10": "Résoudre",
            "20": "Utiliser"},
    "064": {"10": "Résoudre",
            "20": "Utiliser"},
    "065": {"10": "Résoudre",
            "20": "Utiliser"},
    "132": {"10": "Lire",
            "20": "Écrire",
            "30": "Communiquer"},
    "134": {"10": "Communiquer",
            "20": "Comprendre",
            "30": "Écrire"},
}


def codes_competence(parent: str) -> list[str]:
    """Codes de competence d'un cours a epreuve."""
    return [parent[:4] + suffixe for suffixe in COMPETENCES.get(parent[:3], {})]


CODES_RETENUS = frozenset(
    set(COURS_A_EPREUVE)
    | {code for parent in COURS_A_EPREUVE for code in codes_competence(parent)}
)


PARENT_DE_COMPETENCE = {
    code: parent
    for parent in COURS_A_EPREUVE
    for code in codes_competence(parent)
}


SUFFIXES_COMPETENCE = ("10", "20", "30")


MOTIFS_DATE = (
    (re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$"), 2, 3),
    (re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})"
                r"(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)?\s*$"), 2, 1),
)


def eco_de_organisme(cd_orgns) -> int | None:
    """Code d'ecole tire de CD_ORGNS, ou None si hors du centre de services."""
    texte = str(cd_orgns or "").strip()
    if not texte.startswith(CTX.prefixe_organisme):
        return None
    try:
        entier = int(float(texte))
    except ValueError:
        return None
    reste = str(entier)[len(CTX.prefixe_organisme):]
    return int(reste) if reste.isdigit() else None


def parties_date(date_texte) -> tuple[int, int] | None:
    """(mois, annee civile) d'une date, ou None si son format est inconnu."""
    if date_texte is None:
        return None
    texte = str(date_texte)
    for motif, groupe_mois, groupe_annee in MOTIFS_DATE:
        m = motif.match(texte)
        if not m:
            continue
        mois = int(m.group(groupe_mois))
        if not 1 <= mois <= 12:
            return None
        return mois, int(m.group(groupe_annee))
    return None


def annee_scolaire(annee_civile: int) -> int:
    """Annee scolaire designee par son millesime de septembre (juin 2025 -> 2024)."""
    return annee_civile - 1


def est_competence(code: str) -> bool:
    """Le code est-il celui d'une competence plutot que d'un cours ?"""
    return len(code) == 6 and code[-2:] in SUFFIXES_COMPETENCE


def nom_competence(code: str) -> str:
    """Libelle affiche pour un code de competence."""
    return COMPETENCES.get(code[:3], {}).get(code[-2:], f"Compétence {code}")


def resoudre_parents(codes: set[str]) -> dict[str, str]:
    """{code: cours parent} pour chaque code fourni."""
    return {
        code: (code if code in COURS_A_EPREUVE else PARENT_DE_COMPETENCE[code])
        for code in codes
    }


def parse_note(valeur_brute) -> float | None:
    """Note en nombre (virgule ou point), None si elle n'est pas numerique."""
    if valeur_brute is None:
        return None
    s = str(valeur_brute).strip()
    if s == "":
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def tables_epreuves(conn) -> list[str]:
    """Table des resultats, creee par lecture.py."""
    return ["MEQ"]


def table_questions_brute(conn) -> str | None:
    """Table des reponses par question, si des fichiers par question ont ete fournis."""
    return "MEQ_QUESTIONS" if conn.execute("SELECT 1 FROM MEQ_QUESTIONS LIMIT 1").fetchone() else None


class _NomsEcoles:
    def get(self, cle, defaut=""):
        return CTX.noms_ecoles.get(cle[0], defaut)


def charger_noms_ecoles(conn, annee_debut: int, annee_fin: int) -> _NomsEcoles:
    """Noms saisis dans l'interface ; Charlemagne ne fournit que des codes."""
    return _NomsEcoles()


class LigneDetail(NamedTuple):
    """Une ligne eleve x code de cours."""
    eco: int
    annee: int
    cd_permn: str
    nom: str
    cd_cours: str
    groupe: str
    groupe_src: str
    note_finale: float | None
    note_brut: float | None
    note_modr: float | None
    note_meq: float | None


def _normaliser_groupe(valeur) -> str:
    """NO_GROUP_ELEVE en chaine stable ; 0 signifie sans groupe."""
    texte = str(valeur or "").strip()
    if not texte:
        return ""
    try:
        numero = int(float(texte))
    except ValueError:
        return texte
    return "" if numero == 0 else str(numero)


def _nom_eleve(nom, prenom) -> str:
    """Prenom Nom de l'eleve, pour le survol du nuage de points."""
    prenom = str(prenom or "").strip()
    famille = str(nom or "").strip()
    if prenom and famille:
        return f"{prenom} {famille}"
    return prenom or famille or ""


CODES_ABSENCE = frozenset({"ABS"})


def charger_enseignants(conn, annee_debut: int, annee_fin: int) -> dict:
    """{(eleve, annee, cours parent): [("", "", groupe)]}, pour les lignes sans groupe.

    Charlemagne laisse NO_GROUP_ELEVE vide sur le code du cours (le Sommaire) ;
    on reprend le groupe porte par les competences du meme eleve, sans quoi le
    Sommaire d'un enseignant serait toujours vide.
    """
    votes: dict[tuple, Counter] = defaultdict(Counter)
    for cd_permn, cd_cours, dt_obten, no_groupe in conn.execute(
        "SELECT CD_PERMN, CD_COURS, DT_OBTEN_RESLT, NO_GROUP_ELEVE FROM MEQ"
    ):
        parent = PARENT_DE_COMPETENCE.get(str(cd_cours or "").strip())
        groupe = _normaliser_groupe(no_groupe)
        parts = parties_date(dt_obten)
        if parent and groupe and parts and parts[0] in MOIS_RETENUS:
            votes[(str(cd_permn or "").strip(), annee_scolaire(parts[1]), parent)][groupe] += 1
    return {cle: [("", "", sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0])]
            for cle, c in votes.items()}


def charger_enseignants_groupes(conn, annee_debut: int, annee_fin: int) -> dict:
    """Correspondance groupe -> enseignant saisie dans l'interface."""
    return CTX.enseignants_groupes


def _enseignants_directs(directs: dict, eco: int, annee: int, parent: str,
                         groupe: str) -> list[tuple]:
    """Enseignants attribues a un groupe."""
    return (directs.get((eco, annee, parent, groupe))
            or directs.get((eco, annee, parent[:4] + "00", groupe))
            or [])


def charger_lignes_detail(conn, annee_debut: int, annee_fin: int,
                          absences: list | None = None) -> list[LigneDetail]:
    """Une ligne par (eleve, code de cours), avec groupe et les quatre notes."""
    lignes: list[LigneDetail] = []
    hors_perimetre = hors_organisme = date_illisible = hors_mois = 0
    hors_plage = note_illisible = sans_groupe = 0

    for table in tables_epreuves(conn):
        quoted = '"' + table.replace('"', '""') + '"'
        colonnes = {l[1] for l in conn.execute(f"PRAGMA table_info({quoted})")}
        sel_nom = ("NOM, PRENM" if CTX.inclure_noms and {"NOM", "PRENM"} <= colonnes
                   else "'' AS NOM, '' AS PRENM")
        cur = conn.execute(
            f"SELECT CD_PERMN, {sel_nom}, CD_COURS, AN_OBTEN_RESLT, DT_OBTEN_RESLT, "
            f"CD_ORGNS, NO_GROUP_ELEVE, RESLT_FINAL, NOTE_ECOLE_BRUT, NOTE_ECOLE_MODR, "
            f"NOTE_MINST_CONVR FROM {quoted} "
            f"WHERE AN_OBTEN_RESLT IS NULL OR TRIM(CAST(AN_OBTEN_RESLT AS TEXT)) = '' "
            f"   OR CAST(AN_OBTEN_RESLT AS REAL) BETWEEN ? AND ?",
            (annee_debut, annee_fin + 1),
        )
        for (cd_permn, nom_famille, prenom, cd_cours, _an_obten, dt_obten, cd_orgns,
             no_groupe, reslt_final, note_ecole_brut, note_ecole_modr,
             note_minst_convr) in cur.fetchall():
            code = str(cd_cours or "").strip()
            if code not in CODES_RETENUS:
                hors_perimetre += 1
                continue

            eco = eco_de_organisme(cd_orgns)
            if eco is None:
                hors_organisme += 1
                continue

            parts = parties_date(dt_obten)
            if parts is None:
                date_illisible += 1
                continue
            mois, annee_civile = parts
            if mois not in MOIS_RETENUS:
                hors_mois += 1
                continue

            annee = annee_scolaire(annee_civile)
            if not annee_debut <= annee <= annee_fin:
                hors_plage += 1
                continue

            note = parse_note(reslt_final)
            absent = (note is None and absences is not None
                      and str(reslt_final or "").strip().upper() in CODES_ABSENCE)
            if note is None and not absent:
                note_illisible += 1
                continue

            groupe = _normaliser_groupe(no_groupe)
            if not groupe and not absent:
                sans_groupe += 1

            (absences if absent else lignes).append(LigneDetail(
                eco=eco,
                annee=annee,
                cd_permn=str(cd_permn or "").strip(),
                nom=_nom_eleve(nom_famille, prenom),
                cd_cours=code,
                groupe=groupe,
                groupe_src="eleve" if groupe else "",
                note_finale=note,
                note_brut=parse_note(note_ecole_brut),
                note_modr=parse_note(note_ecole_modr),
                note_meq=parse_note(note_minst_convr),
            ))

    if hors_perimetre:
        print(f"  ({hors_perimetre} ligne(s) hors des cours à épreuve unique, écartées)")
    if hors_organisme:
        print(f"  ({hors_organisme} ligne(s) obtenues hors du centre de services, écartées)")
    if hors_mois:
        print(f"  ({hors_mois} ligne(s) hors mai-juin — reprises —, écartées)")
    if hors_plage:
        print(f"  ({hors_plage} ligne(s) hors de la plage {annee_debut}-{annee_fin}, écartées)")
    if date_illisible:
        print(f"  *** {date_illisible} ligne(s) DT_OBTEN_RESLT illisible, écartées ***")
    if note_illisible:
        print(f"  ({note_illisible} ligne(s) RESLT_FINAL non numérique, écartées)")
    if absences:
        print(f"  ({len(absences)} ligne(s) RESLT_FINAL = absence à l'épreuve, "
              f"gardées à part — voir integrer_absences())")
    if sans_groupe:
        print(f"  ({sans_groupe} ligne(s) sans NO_GROUP_ELEVE — repli sur les autres lignes de l'élève)")
    return lignes


def integrer_absences(lignes: list[LigneDetail], absences: list[LigneDetail],
                      parents: dict[str, str]) -> tuple[list[LigneDetail], set]:
    """Reintegre les absents a l'epreuve et rend leurs cles."""
    if not absences:
        return lignes, set()

    a_passe = {(l.eco, l.annee, l.cd_permn, parents[l.cd_cours])
               for l in lignes if l.note_meq is not None}
    deja = {(l.eco, l.annee, l.cd_permn, l.cd_cours) for l in lignes}

    cles_absents: set = set()
    ajoutees: list[LigneDetail] = []
    for a in absences:
        cle_parent = (a.eco, a.annee, a.cd_permn, parents[a.cd_cours])
        if cle_parent in a_passe:
            continue
        cles_absents.add(cle_parent)
        cle_code = (a.eco, a.annee, a.cd_permn, a.cd_cours)
        if cle_code in deja:
            continue
        deja.add(cle_code)
        ajoutees.append(a)

    print(f"  Absents à l'épreuve : {len(cles_absents)} élève(s)-cours, "
          f"{len(ajoutees)} ligne(s) réintégrée(s) pour leurs notes d'école")
    return lignes + ajoutees, cles_absents


def dedoublonner_detail(lignes: list[LigneDetail]) -> list[LigneDetail]:
    """Une ligne par (ecole, annee, eleve, cours) ; la note finale la plus elevee gagne."""
    meilleure: dict[tuple, LigneDetail] = {}
    collisions = 0
    for l in lignes:
        cle = (l.eco, l.annee, l.cd_permn, l.cd_cours)
        existante = meilleure.get(cle)
        if existante is None:
            meilleure[cle] = l
        else:
            collisions += 1
            if l.note_finale > existante.note_finale:
                meilleure[cle] = l
    if collisions:
        print(f"  ({collisions} doublon(s) élève-cours-année, note finale la plus élevée retenue)")
    return list(meilleure.values())


def _serie(valeurs: list[float]) -> tuple[int, float | None, float | None, str | None]:
    """(n, somme, somme des carres, histogramme JSON) d'une mesure."""
    if not valeurs:
        return 0, None, None, None
    somme = sum(valeurs)
    somme_carres = sum(v * v for v in valeurs)
    compte: dict[float, int] = defaultdict(int)
    for v in valeurs:
        compte[v] += 1
    hist = json.dumps(sorted(compte.items()), separators=(",", ":"))
    return len(valeurs), somme, somme_carres, hist


def _eleves(points: list[tuple[str, float, float]]) -> str | None:
    """Points d'un nuage par eleve, en JSON."""
    if not points:
        return None
    return json.dumps(
        sorted([[nom, x, y] for nom, x, y in points]),
        separators=(",", ":"), ensure_ascii=False,
    )


def aggreger_detail(conn, annee_debut: int = ANNEE_DEBUT_DEFAUT,
                    annee_fin: int = ANNEE_FIN_DEFAUT,
                    inclure_groupe_85: bool = False) -> list[dict]:
    """Une ligne par (ecole, annee, cours, groupe)."""
    tables = tables_epreuves(conn)
    if not tables:
        print("*** ATTENTION : aucune table d'épreuves (MEQ* ni XXX_SEC4) dans la "
              "base — le rapport détaillé des épreuves sera VIDE ***")
        return []

    if annee_debut < ANNEE_MEQ_MIN:
        annee_debut = ANNEE_MEQ_MIN
    if annee_debut > annee_fin:
        print("  aucune ligne retenue (plancher épreuves MEQ au-delà de la plage demandée).")
        return []

    print(f"Épreuves ministérielles — détail par groupe ({annee_debut}-{annee_fin}) : "
          f"source {', '.join(tables)}")

    absences: list[LigneDetail] = []
    lignes = dedoublonner_detail(charger_lignes_detail(conn, annee_debut, annee_fin,
                                                       absences=absences))
    if not lignes:
        return []

    try:
        noms_ecoles = charger_noms_ecoles(conn, annee_debut, annee_fin)
    except Exception as e:
        print(f"  (noms d'écoles illisibles : {e} — les écoles resteront sans nom)")
        noms_ecoles = {}
    enseignants = charger_enseignants(conn, annee_debut, annee_fin)
    directs = charger_enseignants_groupes(conn, annee_debut, annee_fin)
    parents = resoudre_parents({l.cd_cours for l in lignes} | {a.cd_cours for a in absences})
    lignes, cles_absents = integrer_absences(lignes, absences, parents)

    cellules: dict[tuple, dict] = defaultdict(lambda: {
        "brut": [], "modr": [], "meq": [], "final": [], "moderation": [],
        "triple": [], "eleves": [], "eleves_moderation": [], "ens": defaultdict(int),
        "brut_abs": [], "modr_abs": [], "final_abs": [],
    })
    sans_groupe_final = 0

    for l in lignes:
        parent = parents[l.cd_cours]
        infos_ens = (enseignants.get((l.cd_permn, l.annee, parent))
                     or enseignants.get((l.cd_permn, l.annee, parent[:4] + "00"))
                     or [])

        groupe, groupe_src = l.groupe, l.groupe_src
        if not groupe and infos_ens:
            groupe = infos_ens[0][2]
            groupe_src = "groupe-cours" if groupe else ""
        if not groupe:
            sans_groupe_final += 1
            groupe = "(sans groupe)"
            groupe_src = "absent"
        if not inclure_groupe_85 and groupe in CTX.groupes_exclus:
            continue

        cle = (l.eco, l.annee, l.cd_cours, groupe)
        cel = cellules[cle]
        cel["src"] = groupe_src
        cel["parent"] = parent

        for interv, nom, _grp in infos_ens:
            if nom:
                cel["ens"][(interv, nom)] += 1

        absent = (l.eco, l.annee, l.cd_permn, parent) in cles_absents

        def noter(serie: str, valeur) -> None:
            if valeur is None:
                return
            cel[serie].append(valeur)
            if absent:
                cel[serie + "_abs"].append(valeur)

        noter("final", l.note_finale)
        noter("brut", l.note_brut)
        noter("modr", l.note_modr)
        if l.note_meq is not None:
            cel["meq"].append(l.note_meq)
        a_epreuve = l.note_meq is not None
        if a_epreuve and l.note_modr is not None and l.note_brut is not None:
            cel["moderation"].append(l.note_modr - l.note_brut)
            cel["eleves_moderation"].append((l.nom or "Élève", l.note_brut, l.note_modr))
        if l.note_brut is not None and a_epreuve:
            cel["eleves"].append((l.nom or "Élève", l.note_brut, l.note_meq))
        if l.note_brut is not None and l.note_modr is not None and l.note_meq is not None:
            cel["triple"].append((l.note_brut, l.note_modr, l.note_meq))

    if sans_groupe_final:
        print(f"  ({sans_groupe_final} ligne(s) sans groupe même après repli, "
              f"regroupées sous « (sans groupe) »)")

    sortie: list[dict] = []
    repli = 0
    for (eco, annee, cd_cours, groupe), cel in cellules.items():
        parent = cel["parent"]
        du_groupe = _enseignants_directs(directs, eco, annee, parent, groupe)
        if du_groupe:
            cel["ens"] = {e: 1 for e in du_groupe}
        elif cel["ens"]:
            repli += 1
        ens = sorted(cel["ens"].items(), key=lambda kv: (-kv[1], kv[0][1]))
        enseignant_id, enseignant = (ens[0][0] if ens else ("", ""))

        n_b, som_b, somcar_b, hist_b = _serie(cel["brut"])
        n_m, som_m, somcar_m, hist_m = _serie(cel["modr"])
        n_q, som_q, somcar_q, hist_q = _serie(cel["meq"])
        n_f, som_f, somcar_f, hist_f = _serie(cel["final"])
        n_o, som_o, somcar_o, hist_o = _serie(cel["moderation"])

        triple = cel["triple"]
        ligne = {
            "ECO": eco,
            "NOM_ECO": noms_ecoles.get((eco, annee), ""),
            "ANNEE": annee,
            "CD_COURS": cd_cours,
            "COURS_PARENT": parent,
            "DESCR_ABREG": nom_competence(cd_cours) if est_competence(cd_cours) else "",
            "GROUPE": groupe,
            "GROUPE_SRC": cel["src"],
            "ENSEIGNANT": enseignant,
            "ENSEIGNANT_ID": enseignant_id,
            "NB_ENSEIGNANTS": len(cel["ens"]),
            "N_BRUT": n_b, "SOM_BRUT": som_b, "SOMCAR_BRUT": somcar_b, "HIST_BRUT": hist_b,
            "N_MODR": n_m, "SOM_MODR": som_m, "SOMCAR_MODR": somcar_m, "HIST_MODR": hist_m,
            "N_MEQ": n_q, "SOM_MEQ": som_q, "SOMCAR_MEQ": somcar_q, "HIST_MEQ": hist_q,
            "N_FINAL": n_f, "SOM_FINAL": som_f, "SOMCAR_FINAL": somcar_f, "HIST_FINAL": hist_f,
            "N_MODERATION": n_o, "SOM_MODERATION": som_o,
            "SOMCAR_MODERATION": somcar_o, "HIST_MODERATION": hist_o,
            "N_TRIPLE": len(triple),
            "SOM_B": sum(b for b, _, _ in triple) or None,
            "SOM_M": sum(m for _, m, _ in triple) or None,
            "SOM_Q": sum(q for _, _, q in triple) or None,
            "SOM_BB": sum(b * b for b, _, _ in triple) or None,
            "SOM_MM": sum(m * m for _, m, _ in triple) or None,
            "SOM_QQ": sum(q * q for _, _, q in triple) or None,
            "SOM_BM": sum(b * m for b, m, _ in triple) or None,
            "SOM_BQ": sum(b * q for b, _, q in triple) or None,
            "SOM_MQ": sum(m * q for _, m, q in triple) or None,
            "ELEVES_JOINT": _eleves(cel["eleves"]),
            "ELEVES_MODERATION_JOINT": _eleves(cel["eleves_moderation"]),
        }
        for serie, prefixe in (("brut", "BRUT"), ("modr", "MODR"), ("final", "FINAL")):
            n, som, somcar, hist = _serie(cel[serie + "_abs"])
            ligne.update({f"N_{prefixe}_ABS": n, f"SOM_{prefixe}_ABS": som,
                          f"SOMCAR_{prefixe}_ABS": somcar, f"HIST_{prefixe}_ABS": hist})
        ligne["ENSEIGNANTS"] = (json.dumps([[i, nom, c] for (i, nom), c in ens],
                                           separators=(",", ":"), ensure_ascii=False)
                                if ens else None)
        sortie.append(ligne)

    sortie.sort(key=lambda l: (l["ANNEE"], l["ECO"], l["CD_COURS"], l["GROUPE"]))
    print(f"  {len(sortie):,} cellule(s) (école × année × cours × groupe)".replace(",", " "))
    if repli:
        print(f"  ({repli} cellule(s) sans groupe-cours homonyme : enseignant déduit "
              f"des inscriptions)")
    return sortie


class LigneQuestion(NamedTuple):
    """Une reponse d'un eleve a une question."""
    eco: int
    annee: int
    cd_permn: str
    cd_cours: str
    groupe: str
    groupe_src: str
    type_quest: str
    no_quest: int
    score: float


def _code_cours_question(valeur) -> str:
    """CD_COURS sur 6 caracteres."""
    texte = str(valeur or "").strip()
    if not texte:
        return ""
    try:
        return f"{int(float(texte)):06d}"
    except ValueError:
        return texte


def _annee_question(an_epreu, sesn_epreu, dt_obten) -> tuple[int, int, str] | None:
    """(mois, annee civile, chemin utilise) d'une reponse."""
    try:
        mois = int(float(sesn_epreu))
        annee_civile = int(float(an_epreu))
        if 1 <= mois <= 12:
            return mois, annee_civile, "session"
    except (TypeError, ValueError):
        pass
    parts = parties_date(dt_obten)
    if parts is not None:
        return parts[0], parts[1], "date"
    return None


def charger_lignes_questions(conn, annee_debut: int, annee_fin: int) -> list[LigneQuestion]:
    """Une ligne par (eleve, code de cours, question)."""
    table = table_questions_brute(conn)
    if table is None:
        return []

    quoted = '"' + table.replace('"', '""') + '"'
    colonnes = {l[1].upper() for l in conn.execute(f"PRAGMA table_info({quoted})")}
    def opt(nom, defaut="NULL"):
        return nom if nom.upper() in colonnes else f"{defaut} AS {nom}"

    sel_groupe = opt("NO_GROUP_ELEVE")
    sel_an = opt("AN_EPREU")
    sel_sesn = opt("SESN_EPREU")
    sel_date = opt("DT_OBTEN_RESLT", "''")
    col_score = next(c for c in COLONNES_SCORE if c.upper() in colonnes)
    sel_score = f'"{col_score}" AS Score'

    lignes: list[LigneQuestion] = []
    hors_perimetre = hors_organisme = hors_mois = hors_plage = 0
    annee_illisible = score_illisible = sans_groupe = 0
    par_chemin: dict[str, int] = defaultdict(int)

    cur = conn.execute(
        f"SELECT CD_PERMN, CD_COURS, CD_ORGNS, {sel_groupe}, "
        f"{sel_an}, {sel_sesn}, {sel_date}, "
        f'TYPE_QUEST, NO_QUEST, {sel_score} FROM {quoted}'
    )
    for (cd_permn, cd_cours, cd_orgns, no_groupe, an_epreu, sesn_epreu,
         dt_obten, type_quest, no_quest, score) in cur.fetchall():
        code = _code_cours_question(cd_cours)
        if code not in CODES_RETENUS:
            hors_perimetre += 1
            continue

        eco = eco_de_organisme(cd_orgns)
        if eco is None:
            hors_organisme += 1
            continue

        parts = _annee_question(an_epreu, sesn_epreu, dt_obten)
        if parts is None:
            annee_illisible += 1
            continue
        mois, annee_civile, chemin = parts
        par_chemin[chemin] += 1
        if mois not in MOIS_RETENUS:
            hors_mois += 1
            continue

        annee = annee_scolaire(annee_civile)
        if not annee_debut <= annee <= annee_fin:
            hors_plage += 1
            continue

        type_norm = str(type_quest or "").strip().upper()
        lettre = str(score or "").strip().upper()
        try:
            numero = int(float(no_quest))
            if type_norm in TYPES_CHOIX_MULTIPLE and lettre in LETTRES_CHOIX:
                valeur = lettre
            else:
                valeur = float(score)
        except (TypeError, ValueError):
            score_illisible += 1
            continue

        groupe = _normaliser_groupe(no_groupe)
        if not groupe:
            sans_groupe += 1

        lignes.append(LigneQuestion(
            eco=eco,
            annee=annee,
            cd_permn=str(cd_permn or "").strip(),
            cd_cours=code,
            groupe=groupe,
            groupe_src="eleve" if groupe else "",
            type_quest=type_norm,
            no_quest=numero,
            score=valeur,
        ))

    print(f"  Source par question : {table}")
    if par_chemin:
        print(f"  (année datée par : "
              f"{', '.join(f'{k} {v}' for k, v in sorted(par_chemin.items()))})")
    if hors_perimetre:
        print(f"  ({hors_perimetre} ligne(s) hors des cours à épreuve unique, écartées)")
    if hors_organisme:
        print(f"  ({hors_organisme} ligne(s) obtenues hors du centre de services, écartées)")
    if hors_mois:
        print(f"  ({hors_mois} ligne(s) hors mai-juin — reprises —, écartées)")
    if hors_plage:
        print(f"  ({hors_plage} ligne(s) hors de la plage {annee_debut}-{annee_fin}, écartées)")
    if annee_illisible:
        print(f"  *** {annee_illisible} ligne(s) sans AN_EPREU/SESN_EPREU ni date "
              f"lisible, écartées ***")
    if score_illisible:
        print(f"  ({score_illisible} ligne(s) Score ou NO_QUEST non numérique, écartées)")
    if sans_groupe:
        print(f"  ({sans_groupe} ligne(s) sans NO_GROUP_ELEVE — repli sur les autres lignes de l'élève)")
    return noter_choix_multiples(lignes)


COLONNES_SCORE = ("Score", "RESLT_QUEST")


TYPES_CHOIX_MULTIPLE = {"OB"}


LETTRES_CHOIX = {"A", "B", "C", "D"}


BAREME_CHOIX_MULTIPLE = 4.0


ACCORD_MIN = 0.8


REFERENCE_MIN = 5


PERM_TIRAGES = 10000


PERM_GRAINE = 20260101


def noter_choix_multiples(lignes: list[LigneQuestion]) -> list[LigneQuestion]:
    """Note les lettres contre un corrige deduit des meilleurs eleves."""
    lettres = [l for l in lignes if isinstance(l.score, str)]
    if not lettres:
        return lignes
    notees = [l for l in lignes if not isinstance(l.score, str)]

    bareme: dict[tuple, float] = defaultdict(float)
    for l in notees:
        cle = (l.annee, l.cd_cours, l.type_quest, l.no_quest)
        bareme[cle] = max(bareme[cle], l.score)
    total: dict[tuple, list] = defaultdict(lambda: [0.0, 0.0])
    for l in notees:
        t = total[(l.annee, l.cd_cours, l.cd_permn)]
        t[0] += l.score
        t[1] += bareme[(l.annee, l.cd_cours, l.type_quest, l.no_quest)]

    par_epreuve: dict[tuple, list] = defaultdict(list)
    for (annee, cours, eleve), (som, possible) in total.items():
        if possible:
            par_epreuve[(annee, cours)].append((som / possible, eleve))
    reference: dict[tuple, set] = {}
    for epreuve, eleves in par_epreuve.items():
        parfaits = {e for taux, e in eleves if taux >= 1.0}
        if len(parfaits) < REFERENCE_MIN:
            parfaits = {e for _, e in sorted(eleves, reverse=True)[:REFERENCE_MIN]}
        reference[epreuve] = parfaits

    votes: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    for l in lettres:
        if l.cd_permn in reference.get((l.annee, l.cd_cours), ()):
            votes[(l.annee, l.cd_cours, l.no_quest)][l.score] += 1
    corrige: dict[tuple, str] = {}
    print("  Choix multiples — corrigé déduit des élèves à 100 % sur les autres questions :")
    for cle in sorted(votes):
        lettre, n = max(votes[cle].items(), key=lambda kv: kv[1])
        total_votes = sum(votes[cle].values())
        corrige[cle] = lettre
        accord = n / total_votes
        alerte = "   *** accord faible, à vérifier ***" if accord < ACCORD_MIN else ""
        print(f"    {cle[0]}-{cle[0] + 1} {cle[1]} Q{cle[2]} : {lettre}  "
              f"({n}/{total_votes} élèves de référence, {accord:.0%}){alerte}")

    sans_corrige = 0
    for l in lettres:
        bonne = corrige.get((l.annee, l.cd_cours, l.no_quest))
        if bonne is None:
            sans_corrige += 1
            continue
        notees.append(l._replace(score=BAREME_CHOIX_MULTIPLE if l.score == bonne else 0.0))
    if sans_corrige:
        print(f"  ({sans_corrige} réponse(s) à choix multiples sans corrigé déductible, écartées)")
    return notees


def dedoublonner_questions(lignes: list[LigneQuestion]) -> list[LigneQuestion]:
    """Une ligne par reponse ; le meilleur score gagne."""
    meilleure: dict[tuple, LigneQuestion] = {}
    collisions = 0
    for l in lignes:
        cle = (l.eco, l.annee, l.cd_permn, l.cd_cours, l.type_quest, l.no_quest)
        existante = meilleure.get(cle)
        if existante is None:
            meilleure[cle] = l
        else:
            collisions += 1
            if l.score > existante.score:
                meilleure[cle] = l
    if collisions:
        print(f"  ({collisions} doublon(s) élève-question, meilleur score retenu)")
    return list(meilleure.values())


class PreparationQuestions(NamedTuple):
    """Population par question, commune a la carte de chaleur et au test."""
    lignes: list[tuple[LigneQuestion, tuple]]
    cellules: dict[tuple, dict]
    baremes: dict[tuple, float]
    noms_ecoles: dict[tuple, str]


def preparer_questions(conn, annee_debut: int = ANNEE_DEBUT_DEFAUT,
                       annee_fin: int = ANNEE_FIN_DEFAUT,
                       inclure_groupe_85: bool = False) -> PreparationQuestions | None:
    """Charge, dedoublonne et rattache les reponses par question."""
    if table_questions_brute(conn) is None:
        print("  Aucune table d'export par question dans cette base.")
        return None

    if annee_debut < ANNEE_MEQ_MIN:
        annee_debut = ANNEE_MEQ_MIN
    if annee_debut > annee_fin:
        print("  aucune ligne retenue (plancher épreuves MEQ au-delà de la plage demandée).")
        return None

    print(f"Épreuves ministérielles — détail par question ({annee_debut}-{annee_fin})")

    lignes = dedoublonner_questions(
        charger_lignes_questions(conn, annee_debut, annee_fin))
    if not lignes:
        return None

    try:
        noms_ecoles = charger_noms_ecoles(conn, annee_debut, annee_fin)
    except Exception as e:
        print(f"  (noms d'écoles illisibles : {e} — les écoles resteront sans nom)")
        noms_ecoles = {}
    enseignants = charger_enseignants(conn, annee_debut, annee_fin)
    directs = charger_enseignants_groupes(conn, annee_debut, annee_fin)
    parents = resoudre_parents({l.cd_cours for l in lignes})

    baremes: dict[tuple, float] = defaultdict(float)
    for l in lignes:
        cle = (l.cd_cours, l.type_quest, l.no_quest)
        if l.score > baremes[cle]:
            baremes[cle] = l.score

    cellules: dict[tuple, dict] = defaultdict(lambda: {
        "n": 0, "som": 0.0, "somcar": 0.0, "ens": defaultdict(int),
    })
    retenues: list[tuple[LigneQuestion, tuple]] = []
    sans_groupe_final = 0

    for l in lignes:
        parent = parents[l.cd_cours]
        infos_ens = (enseignants.get((l.cd_permn, l.annee, parent))
                     or enseignants.get((l.cd_permn, l.annee, parent[:4] + "00"))
                     or [])

        groupe, groupe_src = l.groupe, l.groupe_src
        if not groupe and infos_ens:
            groupe = infos_ens[0][2]
            groupe_src = "groupe-cours" if groupe else ""
        if not groupe:
            sans_groupe_final += 1
            groupe = "(sans groupe)"
            groupe_src = "absent"
        if not inclure_groupe_85 and groupe in CTX.groupes_exclus:
            continue

        cle = (l.eco, l.annee, l.cd_cours, groupe, l.type_quest, l.no_quest)
        cel = cellules[cle]
        cel["src"] = groupe_src
        cel["parent"] = parent
        for interv, nom, _grp in infos_ens:
            if nom:
                cel["ens"][(interv, nom)] += 1
        cel["n"] += 1
        cel["som"] += l.score
        cel["somcar"] += l.score * l.score
        retenues.append((l, cle))

    if sans_groupe_final:
        print(f"  ({sans_groupe_final} ligne(s) sans groupe même après repli, "
              f"regroupées sous « (sans groupe) »)")

    for (eco, annee, _cours, groupe, _t, _q), cel in cellules.items():
        du_groupe = _enseignants_directs(directs, eco, annee, cel["parent"], groupe)
        if du_groupe:
            cel["ens"] = {e: 1 for e in du_groupe}
        ens = sorted(cel["ens"].items(), key=lambda kv: (-kv[1], kv[0][1]))
        cel["ens_id"], cel["ens_nom"] = (ens[0][0] if ens else ("", ""))

    return PreparationQuestions(lignes=retenues, cellules=dict(cellules),
                                baremes=dict(baremes), noms_ecoles=noms_ecoles)


def aggreger_questions(conn, annee_debut: int = ANNEE_DEBUT_DEFAUT,
                       annee_fin: int = ANNEE_FIN_DEFAUT,
                       prep: PreparationQuestions | None = None,
                       inclure_groupe_85: bool = False) -> list[dict]:
    """Une ligne par (ecole, annee, cours, groupe, question)."""
    if prep is None:
        prep = preparer_questions(conn, annee_debut, annee_fin, inclure_groupe_85)
    if prep is None:
        return []

    sortie: list[dict] = []
    for (eco, annee, cd_cours, groupe, type_quest, no_quest), cel in prep.cellules.items():
        sortie.append({
            "ECO": eco,
            "NOM_ECO": prep.noms_ecoles.get((eco, annee), ""),
            "ANNEE": annee,
            "CD_COURS": cd_cours,
            "COURS_PARENT": cel["parent"],
            "GROUPE": groupe,
            "GROUPE_SRC": cel["src"],
            "ENSEIGNANT": cel["ens_nom"],
            "ENSEIGNANT_ID": cel["ens_id"],
            "NB_ENSEIGNANTS": len(cel["ens"]),
            "TYPE_QUEST": type_quest,
            "NO_QUEST": no_quest,
            "SCORE_MAX": prep.baremes.get((cd_cours, type_quest, no_quest)) or None,
            "N": cel["n"],
            "SOM": cel["som"],
            "SOMCAR": cel["somcar"],
        })

    sortie.sort(key=lambda l: (l["ANNEE"], l["ECO"], l["CD_COURS"],
                               l["TYPE_QUEST"], l["NO_QUEST"], l["GROUPE"]))
    print(f"  {len(sortie):,} cellule(s) (école × année × cours × groupe × question)"
          .replace(",", " "))
    return sortie


def _benjamini_hochberg(p_par_cle: dict) -> dict:
    """q-valeurs (FDR) d'une famille de p."""
    if not p_par_cle:
        return {}
    ordre = sorted(p_par_cle.items(), key=lambda kv: kv[1])
    m = len(ordre)
    q_par_cle = {}
    plafond = 1.0
    for rang in range(m, 0, -1):
        cle, p = ordre[rang - 1]
        plafond = min(plafond, p * m / rang)
        q_par_cle[cle] = plafond
    return q_par_cle


def _taux_reussite(som, possible):
    """Taux de reussite en %."""
    import numpy as np
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(possible > 0, som / np.where(possible > 0, possible, 1) * 100.0,
                        np.nan)


def permuter_examen(S, W, debuts, tirages: int, graine):
    """p bilateraux du test de permutation d'une epreuve."""
    import numpy as np
    n_eleves = S.shape[0]
    taux_obs = _taux_reussite(np.add.reduceat(S, debuts, axis=0), np.add.reduceat(W, debuts, axis=0))
    taux_ref = _taux_reussite(S.sum(axis=0), W.sum(axis=0))
    ecart_obs = np.abs(taux_obs - taux_ref)
    rng = np.random.default_rng(graine)
    extremes = np.zeros_like(taux_obs)
    for _ in range(tirages):
        melange = rng.permutation(n_eleves)
        tp = _taux_reussite(np.add.reduceat(S[melange], debuts, axis=0),
                            np.add.reduceat(W[melange], debuts, axis=0))
        extremes += np.abs(tp - taux_ref) >= ecart_obs - 1e-9
    return (extremes + 1.0) / (tirages + 1.0)


def aggreger_permutations(conn, annee_debut: int = ANNEE_DEBUT_DEFAUT,
                          annee_fin: int = ANNEE_FIN_DEFAUT,
                          prep: PreparationQuestions | None = None,
                          tirages: int = PERM_TIRAGES, cache=None) -> list[dict]:
    """Test de permutation par enseignant et par question."""
    try:
        import numpy as np
    except ImportError:
        print("  NumPy absent : test de permutation sauté.")
        return []

    if prep is None:
        prep = preparer_questions(conn, annee_debut, annee_fin)
    if prep is None:
        return []

    par_examen: dict[tuple, list] = defaultdict(list)
    sans_bareme = 0
    for ligne, cle in prep.lignes:
        bareme = prep.baremes.get((ligne.cd_cours, ligne.type_quest, ligne.no_quest)) or 0.0
        if bareme <= 0:
            sans_bareme += 1
            continue
        par_examen[(ligne.annee, ligne.cd_cours)].append((ligne, cle, bareme))

    if sans_bareme:
        print(f"  ({sans_bareme} réponse(s) sans barème, hors du test)")

    sortie: list[dict] = []
    eleves_mixtes = 0

    for (annee, cd_cours), reponses in sorted(par_examen.items()):
        votes: dict[str, dict] = defaultdict(lambda: defaultdict(int))
        for ligne, cle, _bareme in reponses:
            votes[ligne.cd_permn][(cle[0], prep.cellules[cle]["ens_id"])] += 1

        unite_par_eleve = {}
        for eleve, compte in votes.items():
            if len(compte) > 1:
                eleves_mixtes += 1
            unite_par_eleve[eleve] = max(compte.items(),
                                         key=lambda kv: (kv[1], kv[0]))[0]

        unites = sorted({u for u in unite_par_eleve.values()})
        if len(unites) < 2:
            continue

        eleves = sorted(unite_par_eleve)
        rang_unite = {u: k for k, u in enumerate(unites)}
        eleves.sort(key=lambda e: (rang_unite[unite_par_eleve[e]], e))
        rang_eleve = {e: i for i, e in enumerate(eleves)}

        questions = sorted({(l.type_quest, l.no_quest) for l, _c, _b in reponses})
        rang_question = {q: j for j, q in enumerate(questions)}
        types = sorted({t for t, _no in questions})
        rang_type = {t: k for k, t in enumerate(types)}

        n_eleves, n_questions = len(eleves), len(questions)
        S = np.zeros((n_eleves, n_questions))
        W = np.zeros((n_eleves, n_questions))
        C = np.zeros((n_eleves, n_questions))
        for ligne, _cle, bareme in reponses:
            i = rang_eleve[ligne.cd_permn]
            j = rang_question[(ligne.type_quest, ligne.no_quest)]
            S[i, j] += ligne.score
            W[i, j] += bareme
            C[i, j] += 1.0

        agregation = np.zeros((n_questions, len(types)))
        for (t, _no), j in rang_question.items():
            agregation[j, rang_type[t]] = 1.0
        S = np.hstack([S, S @ agregation])
        W = np.hstack([W, W @ agregation])
        C = np.hstack([C, C @ agregation])
        colonnes = questions + [(t, None) for t in types]

        tailles = np.array([sum(1 for e in eleves if unite_par_eleve[e] == u)
                            for u in unites])
        debuts = np.concatenate([[0], np.cumsum(tailles)[:-1]])

        som_obs = np.add.reduceat(S, debuts, axis=0)
        pos_obs = np.add.reduceat(W, debuts, axis=0)
        n_obs = np.add.reduceat(C, debuts, axis=0)
        taux_obs = _taux_reussite(som_obs, pos_obs)

        taux_ref = _taux_reussite(S.sum(axis=0), W.sum(axis=0))

        try:
            graine_cours = int(cd_cours)
        except ValueError:
            graine_cours = sum(ord(c) for c in cd_cours)
        p_val = (cache.questions_meq if cache is not None else permuter_examen)(
            S, W, debuts, tirages, [PERM_GRAINE, int(annee), graine_cours])

        for k, (eco, ens_id) in enumerate(unites):
            ps = {j: float(p_val[k, j]) for j, (_t, no) in enumerate(colonnes)
                  if no is not None and n_obs[k, j] > 0}
            qs = _benjamini_hochberg(ps)

            for j, (type_quest, no_quest) in enumerate(colonnes):
                if not n_obs[k, j]:
                    continue
                sortie.append({
                    "ECO": eco,
                    "ANNEE": annee,
                    "CD_COURS": cd_cours,
                    "ENSEIGNANT_ID": ens_id,
                    "TYPE_QUEST": type_quest,
                    "NO_QUEST": no_quest,
                    "N": int(n_obs[k, j]),
                    "TAUX": round(float(taux_obs[k, j]), 4),
                    "TAUX_REF": round(float(taux_ref[j]), 4),
                    "ECART": round(float(taux_obs[k, j] - taux_ref[j]), 4),
                    "P": round(float(p_val[k, j]), 6),
                    "Q": None if no_quest is None else round(qs[j], 6),
                    "NB_TIRAGES": tirages,
                })

    if eleves_mixtes:
        print(f"  *** {eleves_mixtes} élève(s) rattaché(s) à deux enseignants "
              f"pour une même épreuve, majorité retenue ***")

    sortie.sort(key=lambda l: (l["ANNEE"], l["ECO"], l["CD_COURS"], l["ENSEIGNANT_ID"],
                               l["TYPE_QUEST"], l["NO_QUEST"] is None, l["NO_QUEST"] or 0))
    print(f"  {len(sortie):,} test(s) de permutation "
          f"(école × année × cours × enseignant × question, {tirages} tirages)"
          .replace(",", " "))
    return sortie
