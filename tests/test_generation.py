"""Tests sur donnees inventees. Lancer : python -m unittest discover tests"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "exemple"))

import generer_exemple  # noqa: E402
import openpyxl  # noqa: E402
from msoffcrypto.format.ooxml import OOXMLFile  # noqa: E402

from meq import calculs  # noqa: E402
from meq.enseignants import creer_modele, lire_modele  # noqa: E402
from meq.generation import Parametres, cours_presents, generer, groupes_a_attribuer  # noqa: E402
from meq.lecture import ErreurLecture, charger_fichiers  # noqa: E402


def silence():
    return contextlib.redirect_stdout(io.StringIO())


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.tmp = Path(cls._tmp.name)
        cls.fichiers = generer_exemple.creer(cls.tmp / "src")
        with silence():
            cls.analyse = charger_fichiers(cls.fichiers)

    @classmethod
    def tearDownClass(cls):
        cls.analyse.conn.close()
        cls._tmp.cleanup()

    def produire(self, nom, **kw):
        annee, groupes = groupes_a_attribuer(self.analyse, "999")
        ens = {}
        for g in groupes:
            if g["cle"] == "st" and g["eco"] == 1:
                ens[(g["eco"], g["cle"], g["groupe"])] = "Ana P." if g["groupe"] == "41" else "Bo T."
        p = Parametres(nom_css="CSS Test", prefixe="999", dossier=self.tmp / nom,
                       noms_ecoles={1: "Ecole Alpha", 2: "Ecole Beta"}, enseignants=ens, **kw)
        with silence():
            r = generer(self.analyse, p)
        self.assertEqual(r.fuites, [])
        return r


class TestLecture(Base):
    def test_prefixe_majoritaire(self):
        self.assertEqual(self.analyse.prefixes.most_common(1)[0][0], "999")

    def test_questions_lues(self):
        self.assertGreater(self.analyse.lignes_questions, 0)

    def test_reprises_et_autre_organisme_ecartes(self):
        calculs.CTX.__init__(prefixe_organisme="999")
        with silence():
            lignes = calculs.aggreger_detail(self.analyse.conn)
        for l in lignes:
            for champ in ("HIST_MEQ", "HIST_FINAL"):
                if l[champ]:
                    notes = {v for v, _ in json.loads(l[champ])}
                    self.assertFalse(notes & {99.5, 98.5})

    def test_poids_reel_examen(self):
        # Les donnees d'exemple font final = (moderee + examen) / 2, sans
        # ecrasement : le poids reel vaut 50 % + la part de la moderation, a
        # l'arrondi du resultat final pres.
        calculs.CTX.__init__(prefixe_organisme="999")
        with silence():
            lignes = calculs.aggreger_detail(self.analyse.conn)
        avec = [l for l in lignes if l["N_POIDS"]]
        self.assertTrue(avec)
        for l in lignes:
            self.assertEqual(l["N_POIDS"], l["N_TRIPLE"])
            self.assertEqual(l["N_ECART_FINAL"], l["N_POIDS"])
            self.assertLessEqual(l["N_POIDS_ELEVE"], l["N_POIDS"])
        fb = sum(l["SOM_POIDS_FB"] for l in avec)
        mb = sum(l["SOM_POIDS_MB"] for l in avec)
        eb2 = sum(l["SOM_POIDS_EB2"] for l in avec)
        self.assertAlmostEqual(fb / eb2, 0.5 + 0.5 * mb / eb2, delta=0.01)

    def test_distributions_par_question(self):
        # Chaque case porte une distribution additive qui recompose N et SOM :
        # bonne lettre x 4 pour les choix multiples, somme des scores sinon.
        calculs.CTX.__init__(prefixe_organisme="999")
        with silence():
            lignes = calculs.aggreger_questions(self.analyse.conn)
        self.assertTrue(lignes)
        types = set()
        for l in lignes:
            d = json.loads(l["DISTRIB"])
            self.assertEqual(sum(d.values()), l["N"])
            self.assertRegex(l["PASSATION"], r"^\d{4}-\d{2}$")
            if l["CORRIGE"]:
                types.add("lettres")
                self.assertLessEqual(set(d), {"A", "B", "C", "D", "?"})
                self.assertAlmostEqual(d.get(l["CORRIGE"], 0) * calculs.BAREME_CHOIX_MULTIPLE, l["SOM"])
            else:
                types.add("scores")
                self.assertLessEqual(l["SCORE_MAX"], calculs.SEUIL_TRANCHES)
                self.assertAlmostEqual(sum(float(k) * n for k, n in d.items()), l["SOM"])
        self.assertEqual(types, {"lettres", "scores"})

    def test_tranches_au_dela_du_seuil(self):
        q = calculs.LigneQuestion(1, 2024, "X", "055410", "41", "eleve", "AD", 11, 0.0)
        cle = lambda s: calculs._cle_distribution(q._replace(score=s), 100.0)
        self.assertEqual([cle(0), cle(9.9), cle(55), cle(99), cle(100)], ["0", "0", "50", "90", "90"])
        self.assertEqual(calculs._cle_distribution(q._replace(score=2.5), 4.0), "2.5")

    def test_corrige_par_passation(self):
        # Deux passations la meme annee scolaire, deux corriges : mai = B,
        # juin = C. Un corrige par annee aurait mele les deux votes.
        lignes = []
        for passation, bonne in (("2025-05", "B"), ("2025-06", "C")):
            for e in range(8):
                eleve = f"{passation}-{e}"
                base = calculs.LigneQuestion(1, 2024, eleve, "055410", "41", "eleve", "DC", 7, 4.0,
                                             passation=passation)
                lignes.append(base)
                lignes.append(base._replace(type_quest="OB", no_quest=1,
                                            score="" if e == 7 else (bonne if e < 6 else "A")))
        with silence():
            notees = calculs.noter_choix_multiples(lignes)
        ob = [l for l in notees if l.type_quest == "OB"]
        self.assertEqual(len(ob), 16)
        for l in ob:
            self.assertEqual(l.corrige, {"2025-05": "B", "2025-06": "C"}[l.passation])
            self.assertEqual(l.score, calculs.BAREME_CHOIX_MULTIPLE if l.reponse == l.corrige else 0.0)
        self.assertEqual(sum(1 for l in ob if l.reponse == ""), 2)   # vides : comptees fausses

    def test_sommaire_rattache_au_groupe(self):
        calculs.CTX.__init__(prefixe_organisme="999")
        with silence():
            lignes = calculs.aggreger_detail(self.analyse.conn)
        sommaire = [l for l in lignes if l["CD_COURS"] == "055444"]
        self.assertTrue(sommaire)
        self.assertNotIn("(sans groupe)", {l["GROUPE"] for l in sommaire})

    def test_mot_de_passe(self):
        chiffre = self.tmp / "protege.xlsx"
        with open(self.fichiers[0], "rb") as f, open(chiffre, "wb") as g:
            OOXMLFile(f).encrypt("secret", g)
        with silence():
            a = charger_fichiers([chiffre], "secret")
        self.assertEqual(a.lignes_resultats, self.analyse.lignes_resultats)
        a.conn.close()
        with self.assertRaises(ErreurLecture):
            charger_fichiers([chiffre], "mauvais")
        with self.assertRaises(ErreurLecture):
            charger_fichiers([chiffre], "")


class TestModeleEnseignants(unittest.TestCase):
    GROUPES = [(1, "st", "41"), (1, "st", "42"), (2, "cst", "43")]
    ECOLES = {1: "École Alpha", 2: "École Bêta"}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.chemin = Path(self._tmp.name) / "modele.xlsx"
        self.addCleanup(self._tmp.cleanup)

    def lire(self):
        return lire_modele(self.chemin, set(self.GROUPES), self.ECOLES)

    def remplir(self, lignes):
        wb = openpyxl.load_workbook(self.chemin)
        ws = wb["Enseignants"]
        for ligne in lignes:
            ws.append(ligne)
        wb.save(self.chemin)

    def test_modele_prerempli(self):
        creer_modele(self.chemin, self.GROUPES, self.ECOLES, {(1, "st", "42"): "Bo T."})
        ws = openpyxl.load_workbook(self.chemin)["Enseignants"]
        self.assertEqual([c.value for c in ws[2]][:4], [1, "École Alpha", "055444", 41])
        self.assertEqual(ws["C2"].number_format, "@")
        self.assertEqual(self.lire(), ({(1, "st", "42"): "Bo T."}, []))

    def test_codes_de_cours(self):
        creer_modele(self.chemin)
        self.remplir([[1, None, "055444", 41, "Ana P."],      # code du cours
                       [1, None, 55444, 42, "Bo T."],         # zero initial perdu par Excel
                       [2, None, "063420", 43, "Cy R."]])     # code de competence
        self.assertEqual(self.lire(), ({(1, "st", "41"): "Ana P.", (1, "st", "42"): "Bo T.",
                                        (2, "cst", "43"): "Cy R."}, []))

    def test_validation_matiere_et_onglet_liste(self):
        creer_modele(self.chemin)
        wb = openpyxl.load_workbook(self.chemin)
        self.assertEqual(wb["Listes"].sheet_state, "hidden")
        self.assertEqual(len(wb["Enseignants"].data_validations.dataValidation), 1)
        self.assertEqual(wb["Enseignants"].max_row, 1)

    def test_variantes_de_saisie(self):
        creer_modele(self.chemin)
        self.remplir([[1.0, None, "science", 41.0, "Ana P."],
                       [None, "ecole beta", "Mathématique — CST (4e sec.)", "43", "Bo T.; Cy R."]])
        trouves, ignorees = self.lire()
        self.assertEqual(trouves, {(1, "st", "41"): "Ana P.", (2, "cst", "43"): "Bo T.; Cy R."})
        self.assertEqual(ignorees, [])

    def test_virgule_dans_un_nom(self):
        creer_modele(self.chemin)
        self.remplir([[1, None, "Science", 41, "Tremblay, Ana"]])
        self.assertEqual(self.lire()[0], {(1, "st", "41"): "Tremblay, Ana"})

    def test_co_enseignement_sur_deux_lignes(self):
        creer_modele(self.chemin)
        self.remplir([[1, None, "Science", 41, "Ana P."], [1, None, "Science", 41, "Bo T."],
                      [1, None, "Science", 41, "ana p."]])
        self.assertEqual(self.lire()[0], {(1, "st", "41"): "Ana P.; Bo T."})

    def test_lignes_ignorees_sans_nom_dans_le_motif(self):
        creer_modele(self.chemin)
        self.remplir([[9, None, "Science", 41, "Ana P."], [1, None, "Latin", 41, "Bo T."],
                      [None, "Inconnue", "Science", 41, "Cy R."], [1, None, "Science", 99, "Di S."],
                      [1, None, "Science", 42, None]])
        trouves, ignorees = self.lire()
        self.assertEqual(trouves, {})
        self.assertEqual(len(ignorees), 4)
        self.assertTrue(ignorees[0].startswith("Ligne 2 "), ignorees[0])
        for nom in ("Ana", "Bo T", "Cy R", "Di S"):
            self.assertNotIn(nom, " ".join(ignorees))

    def test_fichier_sans_les_colonnes(self):
        wb = openpyxl.Workbook()
        wb.active.append(["Nom", "Age"])
        wb.save(self.chemin)
        with self.assertRaises(ErreurLecture):
            self.lire()


class TestRapports(Base):
    def html(self, racine):
        return {p.name: p.read_text(encoding="utf-8") for p in racine.rglob("*.html")}

    def test_sans_noms_par_defaut(self):
        r = self.produire("anon")
        fichiers = self.html(r.racine)
        self.assertIn("Rapport CSS Test.html", fichiers)
        self.assertIn("Science - Ana P.html", fichiers)
        for nom, h in fichiers.items():
            self.assertNotRegex(h, r"Fictif\d+|Eleve\d+|TEST\d{8}", nom)
            self.assertNotRegex(h, r"(?i)pevr", nom)

    def test_niveaux_demandes(self):
        r = self.produire("css", niveaux={"css"})
        self.assertEqual(list(self.html(r.racine)), ["Rapport CSS Test.html"])

    def test_histoire_a_ses_groupes_et_ses_enseignants(self):
        _annee, groupes = groupes_a_attribuer(self.analyse, "999")
        self.assertEqual({g["cle"] for g in groupes},
                         {"cst", "sn", "st", "histoire", "francais", "anglais"})
        self.assertEqual(len(groupes), 36)
        p = Parametres(nom_css="CSS Test", prefixe="999", dossier=self.tmp / "histoire",
                       enseignants={(1, "histoire", "41"): "Ana P."}, niveaux={"prof"}, cours={"085404"})
        with silence():
            r = generer(self.analyse, p)
        self.assertEqual(r.fuites, [])
        self.assertIn("Histoire - Ana P.html", self.html(r.racine))
        self.assertEqual(sorted((s[0], s[3]) for s in r.sans_enseignant),
                         [("École 1", "42"), ("École 1", "43"),
                          ("École 2", "41"), ("École 2", "42"), ("École 2", "43")])

    def test_selection_de_cours(self):
        r = self.produire("selection", cours={"055444"})
        fichiers = self.html(r.racine)
        self.assertIn("Science - Ana P.html", fichiers)
        self.assertEqual({n for n in fichiers if n != "Rapport CSS Test.html" and not n.startswith("Science")}, set())
        css = fichiers["Rapport CSS Test.html"]
        self.assertRegex(css, r'"parent":\s*"055444"')
        self.assertNotRegex(css, r'"parent":\s*"063414"')
        self.assertNotIn('"063420"', css)

    def test_selection_sans_resultat(self):
        with self.assertRaises(ValueError):
            self.produire("vide", cours={"064426"})
        with self.assertRaises(ValueError):
            self.produire("rien", cours=set())

    def test_cours_presents(self):
        self.assertEqual(cours_presents(self.analyse, "999"),
                         ["063414", "065426", "055444", "085404", "132506", "134504"])

    def test_selection_ne_change_pas_les_chiffres(self):
        extraire = lambda h: re.search(r"const CELLULES_SANS_G85 = (\[.*?\]);\n", h, re.S)
        ens = {"niveaux": {"ecole"}}
        tout = self.html(self.produire("tout", **ens).racine)["Science - École.html"]
        seul = self.html(self.produire("seul", cours={"055444"}, **ens).racine)["Science - École.html"]
        self.assertEqual(re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d", "", tout), re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d", "", seul))

    def test_confidentialite_avec_noms(self):
        r = self.produire("noms", inclure_noms=True)
        f = self.html(r.racine)
        self.assertRegex(f["Science - Ana P.html"], r"Eleve\d+ Fictif\d+")
        self.assertNotRegex(f["Rapport CSS Test.html"], r"Fictif\d+")
        self.assertNotIn('"Bo T."', f["Science - Ana P.html"])
        self.assertNotIn('"Ana P."', f["Science - Bo T.html"])
        self.assertNotIn('"Ana P."', f["Science - École.html"])
        # Les eleves d'Ana ne sont pas ceux de Bo.
        noms = lambda h: set(re.findall(r"Eleve\d+ Fictif\d+", h))
        self.assertFalse(noms(f["Science - Ana P.html"]) & noms(f["Science - Bo T.html"]))

    def test_gabarit_entierement_rempli(self):
        r = self.produire("gabarit", niveaux={"css"}, groupes_exclus={"43"})
        h = self.html(r.racine)["Rapport CSS Test.html"]
        self.assertEqual(re.findall(r"__[A-Z_]+__", h), [])
        self.assertIn("Inclure les groupes exclus (43)", h)

    def test_zone_sans_risque_a_70(self):
        r = self.produire("seuil", niveaux={"css"})
        h = self.html(r.racine)["Rapport CSS Test.html"]
        self.assertIn("const SEUIL_SANS_RISQUE = 70;", h)
        self.assertIn("% ≥ 60 et % ≥ 70", h)
        self.assertNotIn("≥ 74", h)
        self.assertIn("const CIBLES = {};", h)


class ReglagesIntegres(Base):
    """Les reglages qu'utilise un rapport integre a une autre suite (CSSL)."""

    def test_reglages_propres_a_un_centre(self):
        from meq import rapport
        with silence():
            calculs.CTX.__init__(prefixe_organisme="999")
            lignes = calculs.aggreger_detail(self.analyse.conn)
        six = [m for m in rapport.MATIERES if m["cle"] not in ("ts", "ats")]
        p = rapport.build_payloads(lignes, matieres=six)
        self.assertEqual([m["cle"] for m in p["matieres"]], [m["cle"] for m in six])
        h = rapport.build_html(
            p, nom_css="CSSX", groupes_exclus=("85",), seuil_sans_risque=74,
            cibles={"cst": 61.6}, nom_cible="PEVR", objectifs_passage={28: 85},
            notes={"source": "SOURCE-X", "sommaire": " SOMMAIRE-X", "cibles": "<li>CIBLES-X</li>",
                   "groupes_exclus": "LIBELLE-X"},
            assets={"export.js": "/*EXPORT-X*/"}, version="9.9.9")
        self.assertEqual(re.findall(r"__[A-Z_]+__", h), [])
        for attendu in ("const SEUIL_SANS_RISQUE = 74;", "% ≥ 60 et % ≥ 74", 'const CIBLES = {"cst":61.6};',
                        'const NOM_CIBLE = "PEVR";', 'const OBJECTIFS_PASSAGE = {"28":85};',
                        "Source&nbsp;: SOURCE-X", "l'introduit. SOMMAIRE-X</li>", "<li>CIBLES-X</li>",
                        "<span>LIBELLE-X</span>", "/*EXPORT-X*/", "v9.9.9", ">CSSX</option>"):
            self.assertIn(attendu, h)
        self.assertNotIn('"cle":"ts"', h)

    def test_sources_et_population_remplacables(self):
        appels = []

        def enseignants_groupes(conn, debut, fin):
            appels.append("groupes")
            return {}

        try:
            with silence():
                calculs.CTX.__init__(prefixe_organisme="999")
                defaut = calculs.aggreger_detail(self.analyse.conn)
                calculs.CTX.__init__(
                    prefixe_organisme="999", cours=frozenset({"055444"}), annee_min=2100,
                    charger_enseignants_groupes=enseignants_groupes)
                self.assertEqual(calculs.aggreger_detail(self.analyse.conn), [])  # annee_min au-dela des donnees
                calculs.CTX.annee_min = 2000
                science = calculs.aggreger_detail(self.analyse.conn)
                calculs.CTX.tables_epreuves = lambda conn: []
                self.assertEqual(calculs.aggreger_detail(self.analyse.conn), [])
        finally:
            calculs.CTX.__init__()
        self.assertTrue(science)
        self.assertEqual({r["COURS_PARENT"] for r in science}, {"055444"})
        self.assertGreater(len({r["COURS_PARENT"] for r in defaut}), 1)
        self.assertIn("groupes", appels)

    def test_verifier_fichier_detecte_code_permanent(self):
        from meq.reduction import verifier_fichier
        self.assertEqual(verifier_fichier('<p>ABCD12345678</p>', set(), set(), set(), set()),
                         ["code permanent"])
        self.assertEqual(verifier_fichier('<p>XABCD12345678Y</p>', set(), set(), set(), set()), [])


if __name__ == "__main__":
    unittest.main()
