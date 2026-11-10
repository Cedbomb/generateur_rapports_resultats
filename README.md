# Générateur de rapports MEQ

Outil de bureau qui transforme les rapports **Charlemagne** des épreuves ministérielles en
rapports HTML interactifs, pour un centre de services, ses écoles et ses enseignants.

Les rapports sont des fichiers autonomes : ils s'ouvrent dans un navigateur, sans serveur ni
connexion Internet.

## Installation

Il faut Python 3.10 ou plus récent ([python.org](https://www.python.org/downloads/)), avec Tkinter
(inclus dans l'installateur Windows).

**Windows :** double-cliquez sur `lancer.bat`. Le premier lancement installe les dépendances.

**Autre système :**

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python generateur_meq_gui.py
```

Pour essayer sans vos données, ajoutez les deux fichiers fictifs du dossier `exemple/`.

## Fichiers attendus

Des classeurs `.xlsx` exportés de Charlemagne, protégés par mot de passe ou non. L'outil reconnaît
chaque onglet à ses colonnes. Plusieurs fichiers et plusieurs années peuvent être ajoutés ensemble.

| Fichier | Colonnes obligatoires | Colonnes utilisées si présentes |
| --- | --- | --- |
| Résultats aux épreuves | `CD_PERMN`, `CD_ORGNS`, `CD_COURS`, `DT_OBTEN_RESLT`, `RESLT_FINAL` | `NOM`, `PRENM`, `AN_OBTEN_RESLT`, `NO_GROUP_ELEVE`, `NOTE_ECOLE_BRUT`, `NOTE_ECOLE_MODR`, `NOTE_MINST_CONVR` |
| Résultats par question (facultatif) | `CD_PERMN`, `CD_ORGNS`, `CD_COURS`, `TYPE_QUEST`, `NO_QUEST`, `RESLT_QUEST` | `NO_GROUP_ELEVE`, `AN_EPREU`, `SESN_EPREU`, `DT_OBTEN_RESLT` |

## Utilisation

1. **Fichiers :** ajoutez les classeurs, indiquez leur mot de passe s'il y a lieu, puis cliquez sur
   *Analyser*.
2. **Paramètres :** vérifiez le préfixe d'organisme, nommez le centre et les écoles, indiquez au
   besoin les groupes à exclure.
3. **Enseignants :** Charlemagne ne fournit pas les enseignants. Associez-les aux groupes de la
   dernière année, de l'une de ces façons :
   - *Créer le modèle Excel* produit un classeur déjà rempli avec vos écoles, codes de cours et groupes.
     Complétez la colonne `Enseignant(s)`, puis cliquez sur *Importer le fichier Excel* ;
   - le modèle vierge [`modele/modele_enseignants.xlsx`](modele/modele_enseignants.xlsx) permet de
     préparer la liste d'avance ;
   - un double-clic sur un groupe, ou un CSV (colonnes `ecole;matiere;groupe;enseignant`).
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
  sur les élèves ni les enseignants. Une liste d'enseignants remplie, en Excel ou en CSV, contient
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

## Tests

```
python -m unittest discover tests
```

Les tests n'utilisent que des données inventées. `exemple/generer_exemple.py` recrée les fichiers
d'exemple.
