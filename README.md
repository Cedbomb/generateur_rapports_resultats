# Générateur de rapports MEQ

Outil de bureau qui transforme les rapports **Charlemagne** des épreuves ministérielles en
rapports HTML interactifs, pour un centre de services, ses écoles et ses enseignants.

Les rapports sont des fichiers autonomes : ils s'ouvrent dans un navigateur, sans serveur ni
connexion Internet.

## Ce qu'il vous faut

1. **Un ordinateur avec Python récent** : Python 3.10 ou plus récent (idéalement la dernière
   version offerte), avec Tkinter. L'installateur Windows de python.org inclut Tkinter.
2. **Les rapports Charlemagne 106 et 109** des épreuves ministérielles, exportés en Excel (`.xlsx`) :

   | Rapport | Contenu | Obligatoire |
   | --- | --- | --- |
   | **109** | Résultats des élèves aux épreuves | Oui |
   | **106** | Résultats des élèves question par question | Recommandé : sans lui, l'analyse par question est absente des rapports |

   Les classeurs peuvent être protégés par mot de passe. Exportez une année ou plusieurs ; l'outil
   accepte plusieurs fichiers à la fois et compare les années entre elles.

## Installation

### 1. Installer Python (une seule fois)

**Windows :**

1. Téléchargez la dernière version de Python sur
   [python.org/downloads](https://www.python.org/downloads/).
2. Lancez l'installateur et **cochez « Add python.exe to PATH »** au bas de la première fenêtre,
   puis cliquez sur *Install Now*.
3. Pour vérifier, ouvrez l'invite de commandes et tapez `python --version` : le numéro affiché doit
   être 3.10 ou plus.

Si vous n'avez pas les droits d'administrateur, l'installation « pour l'utilisateur seulement »
(choix par défaut) suffit.

**macOS ou Linux :** installez Python 3.10 ou plus récent depuis python.org ou le gestionnaire de
paquets du système, avec Tkinter (paquet `python3-tk` sur Debian et Ubuntu).

### 2. Récupérer le programme

- **Sans Git :** sur la [page du dépôt](https://github.com/cedriclejeune/generateur_rapports_resultats),
  cliquez sur *Code* puis *Download ZIP*, et décompressez l'archive dans un dossier de votre choix.
- **Avec Git :**
  ```
  git clone https://github.com/cedriclejeune/generateur_rapports_resultats.git
  ```

### 3. Lancer le programme

**Windows :** double-cliquez sur `lancer.bat`. Le premier lancement crée un environnement Python
dans le dossier `.venv` et installe les dépendances (`openpyxl`, `msoffcrypto-tool`, `numpy`) ;
il faut une connexion Internet et une minute environ. Les lancements suivants ouvrent directement
la fenêtre.

Si l'installation échoue, vérifiez la version de Python, puis relancez `lancer.bat`.

**macOS ou Linux :**

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python generateur_meq_gui.py
```

Pour les lancements suivants, seule la dernière commande est nécessaire.

### Essayer sans vos données

Le dossier `exemple/` contient deux classeurs fictifs au format des rapports 109
(`exemple_resultats.xlsx`) et 106 (`exemple_par_question.xlsx`). Ajoutez-les dans l'outil pour
voir le résultat avant d'utiliser de vraies données.

## Utilisation

1. **Fichiers :** cliquez sur *Ajouter* et choisissez les classeurs 109 et 106, indiquez leur mot
   de passe s'il y a lieu, puis cliquez sur *Analyser*. L'outil reconnaît chaque onglet à ses
   colonnes ; le nom des fichiers n'a pas d'importance.
2. **Paramètres :** vérifiez le préfixe d'organisme, nommez le centre et les écoles, indiquez au
   besoin les groupes à exclure.
3. **Enseignants :** Charlemagne ne fournit pas les enseignants. Associez-les aux groupes de la
   dernière année, de l'une de ces façons :
   - *Créer le modèle Excel* produit un classeur déjà rempli avec vos écoles, codes de cours et groupes.
     Complétez la colonne `Enseignant(s)`, puis cliquez sur *Importer le fichier Excel* ;
   - le modèle vierge [`modele/modele_enseignants.xlsx`](modele/modele_enseignants.xlsx) permet de
     préparer la liste d'avance ;
   - un double-clic sur un groupe.
4. **Générer :** choisissez le dossier, les rapports à produire et les codes de cours à inclure.
   La sélection s'applique aux trois types de rapports.

Sortie :

```
Rapports_MEQ_2024-2025/
  Rapport <centre>.html            toutes les matières et années, avec menus
  <École>/<Matière>/
    <Matière> - École.html         dernière année, sans groupe ni enseignant identifié
    <Matière> - <Enseignant>.html  ses groupes, comparés au reste de l'école
```

## Confidentialité

Les classeurs contiennent des renseignements personnels sur des élèves.

- **Aucune donnée ne quitte le poste.** Les classeurs sont lus en mémoire, sans copie déchiffrée
  sur le disque ; l'outil n'utilise pas le réseau.
- **Noms d'élèves absents par défaut.** Une case les ajoute aux rapports école et enseignant, jamais
  à celui du centre de services. Ils sont alors lisibles dans le fichier HTML.
- **Données réduites pour chaque destinataire.** Un rapport enseignant ne contient, à titre
  identifiable, que ses groupes ; les autres sont fusionnés avant l'écriture. Chaque fichier est
  vérifié, et n'est pas écrit si un nom ou un code permanent s'y trouve à tort.
- **Le rapport du centre de services nomme les enseignants** et compare groupes et écoles : réservez-le
  aux personnes autorisées.
- Le fichier `~/.generateur_meq.json` mémorise les paramètres (noms d'écoles, etc.), sans donnée
  sur les élèves ni les enseignants. Une liste d'enseignants remplie en Excel contient
  leurs noms.

Ne déposez jamais de vrais classeurs ou rapports dans ce dépôt.

## Règles de calcul

- Seuls les cours à épreuve unique et leurs compétences sont retenus.
- Seule la passation de **mai-juin** compte. Une session de janvier ou une reprise d'août est écartée.
- Les résultats d'un autre organisme sont écartés grâce au préfixe de `CD_ORGNS`.
- Pour un élève en double, la note finale la plus élevée est conservée.
- Une cellule de moins de 5 élèves est comptée dans les totaux, mais n'est pas affichée seule.
- Le corrigé des questions à choix multiples est déduit des réponses des meilleurs élèves ; le
  journal signale un accord faible.

## Annexe : colonnes lues

Si un export ne passe pas, vérifiez que ses colonnes portent ces noms.

| Rapport | Colonnes obligatoires | Colonnes utilisées si présentes |
| --- | --- | --- |
| 109 – résultats aux épreuves | `CD_PERMN`, `CD_ORGNS`, `CD_COURS`, `DT_OBTEN_RESLT`, `RESLT_FINAL` | `NOM`, `PRENM`, `AN_OBTEN_RESLT`, `NO_GROUP_ELEVE`, `NOTE_ECOLE_BRUT`, `NOTE_ECOLE_MODR`, `NOTE_MINST_CONVR` |
| 106 – résultats par question | `CD_PERMN`, `CD_ORGNS`, `CD_COURS`, `TYPE_QUEST`, `NO_QUEST`, `RESLT_QUEST` | `NO_GROUP_ELEVE`, `AN_EPREU`, `SESN_EPREU`, `DT_OBTEN_RESLT` |

## Tests

```
python -m unittest discover tests
```

Les tests n'utilisent que des données inventées. `exemple/generer_exemple.py` recrée les fichiers
d'exemple.

## Licence

© 2026 Centre de services scolaire des Laurentides.

Ce programme est distribué sous la licence
[Creative Commons Attribution - Pas d'utilisation commerciale - Partage dans les mêmes conditions 4.0 International (CC BY-NC-SA 4.0)](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.fr).
Vous pouvez le copier, le modifier et le redistribuer à des fins non commerciales, à condition
d'en citer la source et de diffuser vos modifications sous la même licence. Le texte complet se
trouve dans le fichier [LICENSE](LICENSE).

Le programme est fourni tel quel, sans aucune garantie d'exactitude des résultats. Vérifiez les
rapports avant de les diffuser ou de prendre des décisions à partir de ceux-ci.
