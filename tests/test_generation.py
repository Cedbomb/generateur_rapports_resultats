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
from msoffcrypto.format.ooxml import OOXMLFile  # noqa: E402

from meq import calculs  # noqa: E402
from meq.generation import Parametres, generer, groupes_a_attribuer  # noqa: E402
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
