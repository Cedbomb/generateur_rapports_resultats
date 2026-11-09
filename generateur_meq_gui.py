#!/usr/bin/env python3
"""Interface graphique du generateur de rapports MEQ."""
from __future__ import annotations

import contextlib
import csv
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from meq.generation import (
    MOTIF_NOM_CSS,
    Parametres,
    ecoles_presentes,
    generer,
    groupes_a_attribuer,
)
from meq.lecture import ErreurLecture, charger_fichiers
from meq.rapport import MATIERES

# Aucune donnee nominative ici : ni eleve, ni enseignant.
FICHIER_PARAMETRES = Path.home() / ".generateur_meq.json"


class VersFile:
    """Redirige print() d'un fil de travail vers le journal."""

    def __init__(self, file):
        self.file = file

    def write(self, texte):
        if texte:
            self.file.put(("log", texte))

    def flush(self):
        pass


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Générateur de rapports MEQ")
        self.geometry("920x640")
        self.file = queue.Queue()
        self.analyse = None
        self.prefixes = {}
        self.memoire = self._lire_parametres()

        self.onglets = ttk.Notebook(self)
        self.onglets.pack(fill="both", expand=True, padx=8, pady=8)
        self._onglet_fichiers()
        self._onglet_parametres()
        self._onglet_enseignants()
        self._onglet_generer()
        for i in (1, 2, 3):
            self.onglets.tab(i, state="disabled")
        self.after(100, self._vider_file)

    # ---- Onglet 1 -------------------------------------------------------
    def _onglet_fichiers(self):
        f = ttk.Frame(self.onglets, padding=10)
        self.onglets.add(f, text="1. Fichiers")
        ttk.Label(f, text="Rapports Charlemagne (.xlsx) : résultats aux épreuves et, si disponibles, "
                          "résultats par question.").pack(anchor="w")
        self.liste = tk.Listbox(f, selectmode="extended", height=14)
        self.liste.pack(fill="both", expand=True, pady=6)
        b = ttk.Frame(f)
        b.pack(fill="x")
        ttk.Button(b, text="Ajouter…", command=self._ajouter).pack(side="left")
        ttk.Button(b, text="Retirer", command=self._retirer).pack(side="left", padx=4)
        ttk.Label(b, text="   Mot de passe des classeurs (si protégés) :").pack(side="left")
        self.mdp = tk.StringVar()
        ttk.Entry(b, textvariable=self.mdp, show="•", width=24).pack(side="left", padx=4)
        self.btn_analyser = ttk.Button(b, text="Analyser", command=self._analyser)
        self.btn_analyser.pack(side="right")
        self.etat = tk.StringVar(value="Ajoutez vos fichiers, puis cliquez sur Analyser.")
        ttk.Label(f, textvariable=self.etat, wraplength=860).pack(anchor="w", pady=(8, 0))

    def _ajouter(self):
        deja = set(self.liste.get(0, "end"))
        for c in filedialog.askopenfilenames(filetypes=[("Classeurs Excel", "*.xlsx *.xlsm")]):
            if c not in deja:
                self.liste.insert("end", c)

    def _retirer(self):
        for i in reversed(self.liste.curselection()):
            self.liste.delete(i)

    def _analyser(self):
        chemins = list(self.liste.get(0, "end"))
        if not chemins:
            messagebox.showinfo("Fichiers", "Ajoutez au moins un fichier.")
            return
        self.btn_analyser.state(["disabled"])
        self.etat.set("Lecture en cours…")
        mdp = self.mdp.get()

        def travail():
            try:
                with contextlib.redirect_stdout(VersFile(self.file)):
                    self.file.put(("analyse", charger_fichiers(chemins, mdp)))
            except ErreurLecture as e:
                self.file.put(("erreur_analyse", str(e)))
            except Exception as e:
                self.file.put(("erreur_analyse", f"Erreur inattendue : {type(e).__name__}"))

        threading.Thread(target=travail, daemon=True).start()

    def _analyse_terminee(self, analyse):
        self.analyse = analyse
        self.mdp.set("")
        self.btn_analyser.state(["!disabled"])
        msg = f"{analyse.lignes_resultats} résultats et {analyse.lignes_questions} réponses par question retenus."
        if analyse.onglets_ignores:
            msg += f" Onglets ignorés (colonnes non reconnues) : {', '.join(analyse.onglets_ignores)}."
        self.etat.set(msg)

        self.prefixes = {f"{p}  ({n} lignes)": p for p, n in analyse.prefixes.most_common() if p}
        self.combo_prefixe["values"] = list(self.prefixes)
        memo = self.memoire.get("prefixe")
        choix = next((k for k, v in self.prefixes.items() if v == memo), next(iter(self.prefixes), ""))
        self.combo_prefixe.set(choix)
        self.var_nom.set(self.memoire.get("nom_css", self.var_nom.get()))
        self.var_groupes.set(self.memoire.get("groupes_exclus", ""))
        for cle, v in self.memoire.get("cibles", {}).items():
            if cle in self.vars_cibles:
                self.vars_cibles[cle].set(v)
        self._prefixe_change()
        for i in (1, 2, 3):
            self.onglets.tab(i, state="normal")
        self.onglets.select(1)

    # ---- Onglet 2 -------------------------------------------------------
    def _onglet_parametres(self):
        f = ttk.Frame(self.onglets, padding=10)
        self.onglets.add(f, text="2. Paramètres")
        h = ttk.Frame(f)
        h.pack(fill="x")
        ttk.Label(h, text="Nom court du centre de services :").grid(row=0, column=0, sticky="w")
        self.var_nom = tk.StringVar(value="Centre de services")
        ttk.Entry(h, textvariable=self.var_nom, width=30).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(h, text="Préfixe d'organisme (CD_ORGNS) :").grid(row=1, column=0, sticky="w", pady=4)
        self.combo_prefixe = ttk.Combobox(h, state="readonly", width=28)
        self.combo_prefixe.grid(row=1, column=1, sticky="w", padx=4)
        self.combo_prefixe.bind("<<ComboboxSelected>>", lambda _e: self._prefixe_change())
        ttk.Label(h, text="Groupes à exclure (ex. 85, 90) :").grid(row=2, column=0, sticky="w")
        self.var_groupes = tk.StringVar()
        ttk.Entry(h, textvariable=self.var_groupes, width=30).grid(row=2, column=1, sticky="w", padx=4)

        b = ttk.Frame(f)
        b.pack(fill="both", expand=True, pady=8)
        g = ttk.LabelFrame(b, text="Écoles (double-clic pour nommer)", padding=6)
        g.pack(side="left", fill="both", expand=True)
        self.arbre_ecoles = ttk.Treeview(g, columns=("code", "nom"), show="headings")
        self.arbre_ecoles.heading("code", text="Code")
        self.arbre_ecoles.heading("nom", text="Nom")
        self.arbre_ecoles.column("code", width=60, stretch=False)
        self.arbre_ecoles.pack(fill="both", expand=True)
        self.arbre_ecoles.bind("<Double-1>", self._nommer_ecole)

        d = ttk.LabelFrame(b, text="Cibles PEVR, % à 74 et plus (facultatif)", padding=6)
        d.pack(side="right", fill="y", padx=(8, 0))
        self.vars_cibles = {}
        for i, m in enumerate(MATIERES):
            ttk.Label(d, text=m["nom"]).grid(row=i, column=0, sticky="w")
            self.vars_cibles[m["cle"]] = tk.StringVar()
            ttk.Entry(d, textvariable=self.vars_cibles[m["cle"]], width=7).grid(row=i, column=1, padx=4, pady=1)

    def _prefixe_actuel(self):
        return self.prefixes.get(self.combo_prefixe.get(), "")

    def _noms_ecoles(self):
        return {int(self.arbre_ecoles.set(i, "code")): self.arbre_ecoles.set(i, "nom")
                for i in self.arbre_ecoles.get_children() if self.arbre_ecoles.set(i, "nom").strip()}

    def _prefixe_change(self):
        memo = self.memoire.get("noms_ecoles", {})
        self.arbre_ecoles.delete(*self.arbre_ecoles.get_children())
        for eco in ecoles_presentes(self.analyse, self._prefixe_actuel()):
            self.arbre_ecoles.insert("", "end", values=(eco, memo.get(str(eco), f"École {eco}")))
        self._remplir_enseignants()

    def _nommer_ecole(self, _e):
        i = self.arbre_ecoles.focus()
        if i:
            nom = simpledialog.askstring("École", "Nom de l'école :", parent=self,
                                         initialvalue=self.arbre_ecoles.set(i, "nom"))
            if nom is not None:
                self.arbre_ecoles.set(i, "nom", nom.strip())
                self._remplir_enseignants()

    # ---- Onglet 3 -------------------------------------------------------
    def _onglet_enseignants(self):
        f = ttk.Frame(self.onglets, padding=10)
        self.onglets.add(f, text="3. Enseignants")
        self.lbl_ens = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.lbl_ens, wraplength=860).pack(anchor="w")
        colonnes = ("ecole", "matiere", "groupe", "effectif", "enseignant")
        self.arbre = ttk.Treeview(f, columns=colonnes, show="headings")
        for c, t, w in (("ecole", "École", 180), ("matiere", "Matière", 280), ("groupe", "Groupe", 70),
                        ("effectif", "Élèves", 60), ("enseignant", "Enseignant(s)", 240)):
            self.arbre.heading(c, text=t)
            self.arbre.column(c, width=w, stretch=c == "enseignant")
        barre = ttk.Scrollbar(f, orient="vertical", command=self.arbre.yview)
        self.arbre.configure(yscrollcommand=barre.set)
        bas = ttk.Frame(f)
        bas.pack(side="bottom", fill="x", pady=(6, 0))
        barre.pack(side="right", fill="y")
        self.arbre.pack(fill="both", expand=True, pady=6)
        self.arbre.bind("<Double-1>", self._nommer_enseignant)
        ttk.Button(bas, text="Importer un CSV…", command=self._importer).pack(side="left")
        ttk.Button(bas, text="Exporter en CSV…", command=self._exporter).pack(side="left", padx=4)
        self.lignes_ens = {}

    def _remplir_enseignants(self):
        existants = {k: self.arbre.set(i, "enseignant") for k, i in self.lignes_ens.items()}
        self.arbre.delete(*self.arbre.get_children())
        self.lignes_ens = {}
        annee, groupes = groupes_a_attribuer(self.analyse, self._prefixe_actuel())
        noms = self._noms_ecoles()
        for g in groupes:
            cle = (g["eco"], g["cle"], g["groupe"])
            self.lignes_ens[cle] = self.arbre.insert("", "end", values=(
                noms.get(g["eco"], f"École {g['eco']}"), g["matiere"], g["groupe"], g["effectif"],
                existants.get(cle, "")))
        if annee is not None:
            self.lbl_ens.set(f"Charlemagne ne fournit pas les enseignants. Indiquez-les pour {annee}-{annee + 1} "
                             "(double-clic ; forme conseillée : Prénom N. ; plusieurs noms séparés par « ; »). "
                             "Un groupe sans enseignant reste compté, sans rapport individuel.")

    def _nommer_enseignant(self, _e):
        i = self.arbre.focus()
        if i:
            nom = simpledialog.askstring("Enseignant", "Enseignant(s) du groupe :", parent=self,
                                         initialvalue=self.arbre.set(i, "enseignant"))
            if nom is not None:
                self.arbre.set(i, "enseignant", nom.strip())

    def _importer(self):
        chemin = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not chemin:
            return
        trouves = 0
        with open(chemin, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                try:
                    cle = (int(r["ecole"]), r["matiere"].strip(), r["groupe"].strip())
                    nom = r["enseignant"].strip()
                except (KeyError, ValueError, AttributeError):
                    continue
                if cle in self.lignes_ens:
                    self.arbre.set(self.lignes_ens[cle], "enseignant", nom)
                    trouves += 1
        messagebox.showinfo("Import", f"{trouves} groupe(s) mis à jour.")

    def _exporter(self):
        chemin = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not chemin:
            return
        with open(chemin, "w", encoding="utf-8-sig", newline="") as fh:
            ecr = csv.writer(fh, delimiter=";")
            ecr.writerow(["ecole", "matiere", "groupe", "enseignant"])
            for (eco, cle, groupe), i in self.lignes_ens.items():
                ecr.writerow([eco, cle, groupe, self.arbre.set(i, "enseignant")])

    # ---- Onglet 4 -------------------------------------------------------
    def _onglet_generer(self):
        f = ttk.Frame(self.onglets, padding=10)
        self.onglets.add(f, text="4. Générer")
        h = ttk.Frame(f)
        h.pack(fill="x")
        self.var_dossier = tk.StringVar()
        ttk.Label(h, text="Dossier de sortie :").pack(side="left")
        ttk.Entry(h, textvariable=self.var_dossier).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(h, text="Parcourir…", command=self._choisir_dossier).pack(side="left")

        n = ttk.LabelFrame(f, text="Rapports à produire", padding=6)
        n.pack(fill="x", pady=8)
        self.vars_niveaux = {}
        for cle, texte in (("css", "Centre de services (un fichier à menus)"),
                           ("ecole", "École (par matière)"), ("prof", "Enseignant (par matière)")):
            self.vars_niveaux[cle] = tk.BooleanVar(value=True)
            ttk.Checkbutton(n, text=texte, variable=self.vars_niveaux[cle]).pack(side="left", padx=(0, 14))
        self.var_noms = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Inclure les noms d'élèves dans les rapports école et enseignant",
                        variable=self.var_noms).pack(anchor="w")
        self.btn_generer = ttk.Button(f, text="Générer les rapports", command=self._generer)
        self.btn_generer.pack(anchor="e", pady=6)
        self.journal = tk.Text(f, height=16, state="disabled", wrap="word")
        self.journal.pack(fill="both", expand=True)

    def _choisir_dossier(self):
        d = filedialog.askdirectory()
        if d:
            self.var_dossier.set(d)

    def _parametres(self) -> Parametres | None:
        nom = self.var_nom.get().strip()
        if not MOTIF_NOM_CSS.match(nom):
            messagebox.showerror("Paramètres", "Le nom du centre ne peut contenir que des lettres, "
                                               "chiffres, espaces, apostrophes, points et traits d'union.")
            return None
        if not self.var_dossier.get().strip():
            messagebox.showerror("Sortie", "Choisissez un dossier de sortie.")
            return None
        niveaux = {k for k, v in self.vars_niveaux.items() if v.get()}
        if not niveaux:
            messagebox.showerror("Sortie", "Cochez au moins un type de rapport.")
            return None
        cibles = {}
        for cle, var in self.vars_cibles.items():
            texte = var.get().strip().replace(",", ".")
            if texte:
                try:
                    cibles[cle] = float(texte)
                except ValueError:
                    messagebox.showerror("Paramètres", f"Cible PEVR invalide : {var.get()}")
                    return None
        groupes = {g.strip() for g in self.var_groupes.get().split(",") if g.strip()}
        enseignants = {k: self.arbre.set(i, "enseignant") for k, i in self.lignes_ens.items()
                       if self.arbre.set(i, "enseignant").strip()}
        return Parametres(nom_css=nom, prefixe=self._prefixe_actuel(),
                          dossier=Path(self.var_dossier.get().strip()),
                          noms_ecoles=self._noms_ecoles(), groupes_exclus=groupes, cibles=cibles,
                          enseignants=enseignants, inclure_noms=self.var_noms.get(), niveaux=niveaux)

    def _generer(self):
        p = self._parametres()
        if p is None:
            return
        if p.inclure_noms and not messagebox.askokcancel(
            "Noms d'élèves",
            "Les rapports école et enseignant contiendront des noms d'élèves, lisibles dans le fichier "
            "HTML.\n\nGardez-les dans un emplacement sécurisé et remettez-les seulement aux personnes "
            "autorisées."):
            return
        if "prof" in p.niveaux and not p.enseignants:
            if not messagebox.askokcancel("Enseignants", "Aucun enseignant n'est indiqué : aucun rapport "
                                                         "individuel ne sera produit. Continuer ?"):
                return
        self._enregistrer_parametres(p)
        self.btn_generer.state(["disabled"])
        self._journal_vider()

        def travail():
            try:
                with contextlib.redirect_stdout(VersFile(self.file)):
                    self.file.put(("fin", generer(self.analyse, p)))
            except Exception as e:
                self.file.put(("erreur", f"{type(e).__name__} : {e}"))

        threading.Thread(target=travail, daemon=True).start()

    def _fin(self, r):
        self.btn_generer.state(["!disabled"])
        self._journal(f"\n{r.ecrits} fichier(s) écrit(s) dans {r.racine}\n")
        if r.sans_enseignant:
            self._journal(f"\n{len(r.sans_enseignant)} groupe(s) sans enseignant indiqué "
                          "(comptés dans les rapports école, sans rapport individuel).\n")
        if r.fuites:
            self._journal("\n*** FICHIERS NON ÉCRITS, vérification de confidentialité échouée ***\n")
            for nom, _detail in r.fuites:
                self._journal(f"  {nom}\n")
            messagebox.showerror("Vérification", f"{len(r.fuites)} fichier(s) n'ont pas été écrits.")
        else:
            messagebox.showinfo("Terminé", f"{r.ecrits} rapport(s) générés.")

    def _journal(self, texte):
        self.journal.configure(state="normal")
        self.journal.insert("end", texte)
        self.journal.see("end")
        self.journal.configure(state="disabled")

    def _journal_vider(self):
        self.journal.configure(state="normal")
        self.journal.delete("1.0", "end")
        self.journal.configure(state="disabled")

    # ---- Commun ---------------------------------------------------------
    def _vider_file(self):
        try:
            while True:
                genre, valeur = self.file.get_nowait()
                if genre == "log":
                    self._journal(valeur)
                elif genre == "analyse":
                    self._analyse_terminee(valeur)
                elif genre == "erreur_analyse":
                    self.btn_analyser.state(["!disabled"])
                    self.etat.set(valeur)
                    messagebox.showerror("Lecture", valeur)
                elif genre == "fin":
                    self._fin(valeur)
                elif genre == "erreur":
                    self.btn_generer.state(["!disabled"])
                    self._journal(f"\nErreur : {valeur}\n")
                    messagebox.showerror("Erreur", valeur)
        except queue.Empty:
            pass
        self.after(100, self._vider_file)

    def _lire_parametres(self) -> dict:
        try:
            return json.loads(FICHIER_PARAMETRES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _enregistrer_parametres(self, p: Parametres):
        self.memoire = {"nom_css": p.nom_css, "prefixe": p.prefixe,
                        "groupes_exclus": ", ".join(sorted(p.groupes_exclus)),
                        "noms_ecoles": {str(k): v for k, v in p.noms_ecoles.items()},
                        "cibles": {k: str(v) for k, v in p.cibles.items()}}
        with contextlib.suppress(OSError):
            FICHIER_PARAMETRES.write_text(json.dumps(self.memoire, ensure_ascii=False, indent=2),
                                          encoding="utf-8")


if __name__ == "__main__":
    Application().mainloop()
