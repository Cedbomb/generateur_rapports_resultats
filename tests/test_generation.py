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


if __name__ == "__main__":
    unittest.main()
