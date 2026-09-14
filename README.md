# Suivi du prix des carburants

Une petite application web, à héberger chez soi, qui répond à une question
précise : **faut-il faire le plein maintenant, ou attendre ?**

Elle fait trois choses :

- **comparer** les stations autour d'une commune, de la moins chère à la plus chère ;
- **suivre** l'évolution du prix et la comparer au cours du pétrole brut ;
- **prévoir** le sens de la prochaine variation, et prévenir par courriel quand il change.

---

## Ce que vaut la prévision, sans enjoliver

Ce point mérite d'être lu avant tout le reste, car il détermine la confiance à
accorder à l'outil.

**Le prix exact est imprévisible.** La première version de ce projet cherchait à
répondre à « combien vaudra le gazole dans quinze jours ». Elle y répondait
moins bien que la phrase « la même chose qu'aujourd'hui » — de 12 à 44 % moins
bien selon les cas. Ce n'est pas un défaut de réglage : le niveau futur d'un
prix de carburant est une marche aléatoire, et aucun algorithme n'y peut rien.

**Le sens de la variation, lui, se devine en partie.** Les stations répercutent
leurs hausses par paliers sur plusieurs jours, si bien qu'une tendance entamée a
de bonnes chances de se poursuivre. C'est ce que l'outil exploite, et c'est
aussi tout ce dont on a besoin pour décider de faire le plein ou non.

**Ce n'est pas l'algorithme le plus savant qui gagne.** Trois familles ont
concouru, et le classement est instructif. Les *arbres de gradient*, les plus
sophistiqués, arrivent derniers : chaque arbre corrigeant les erreurs du
précédent, ils finissent par apprendre le bruit par cœur. La *régression
logistique* fait honorablement, sa simplicité même l'empêchant de s'égarer. Et
c'est la *forêt aléatoire* qui l'emporte de trois à cinq points — cinq cents
arbres indépendants dont on moyenne les avis, si bien que leurs erreurs se
compensent au lieu de s'accumuler.

Une version antérieure de ce projet concluait que « les arbres sont mauvais
ici ». C'était faux, et l'erreur vaut d'être signalée : un seul essai avait été
fait, avec le gradient. La manière dont les arbres sont assemblés compte
davantage que le fait d'en employer.

Justesse mesurée sur des périodes que le modèle n'avait jamais vues
(2019-2026, validation glissante) :

Justesse **réellement constatée**, sur les prévisions déjà arrivées à échéance
(février 2025 → aujourd'hui, plus de 6 500 prévisions jugées) :

| Carburant | à 7 jours | à 14 jours | à 30 jours |
|-----------|-----------|------------|------------|
| Gazole    | 76 %      | 62 %       | 57 % ✗ |
| SP95      | **84 %**  | 67 %       | 57 % ✗ |
| SP98      | 81 %      | 65 %       | 55 % ✗ |
| E10       | 77 %      | 63 %       | 49 % ✗ |
| E85       | 88 %      | 83 %       | 65 % |
| GPLc      | —         | 85 %       | 81 % |

Les cases marquées ✗ tombent sous les 60 % : **l'application refuse d'y donner
un avis** et l'affiche comme « non communiqué ». Annoncer une tendance qu'on
sait fausse une fois sur deux rendrait un service douteux.

**Ces chiffres sont plus bas que ceux de la validation**, et l'écart mérite
d'être expliqué. La validation découpe l'historique en six périodes successives
et moyenne les résultats — mais certaines périodes anciennes, comme la flambée
de 2022, étaient bien plus faciles à prévoir que le marché actuel. Sur le gazole
à trente jours, la moyenne des six annonce 66 % là où la dernière période seule
en donne 58. Ce qui intéresse celui qui consulte la page n'est pas la moyenne
des six dernières années, mais si l'outil voit juste **en ce moment**. C'est
donc le palmarès réel qui s'affiche dès qu'il compte plus de cent prévisions
jugées.

Autrement dit : **à sept jours, l'outil se trompe environ une fois sur cinq.**
À quatorze, une fois sur trois. À trente, il se tait.

### Ce n'est pas le baril qu'il faut regarder

Une station n'achète pas de pétrole brut : elle achète du gazole ou de
l'essence **déjà raffinés**, dont le prix de gros a sa propre dynamique —
capacités de raffinage, saisonnalité, arbitrages entre continents. Le baril
n'en est qu'une composante.

Substituer ces cotations de gros au seul cours du brut fait gagner deux à
quatre points de justesse sur les essences : le SP95 à sept jours passe de
78 à 82 %. C'est le gain le plus net obtenu sur ce projet, et il ne vient pas
d'un algorithme plus savant mais d'une donnée mieux choisie.

Un indice de peur des marchés (l'OVX, volatilité du pétrole) a été testé dans
la foulée : il n'apporte rien du tout — corrélation de 0,03 avec les
variations à venir — et dégrade même légèrement les résultats. Il a donc été
écarté.

### Pourquoi deux méthodes selon les carburants

Le modèle statistique n'est pas retenu partout. Sur l'E85 et le GPLc, il se fait
battre de dix à vingt-cinq points par une simple règle de tendance. La raison
est limpide : ces carburants ne suivent pas le pétrole. L'E85 est de l'éthanol,
dont le prix dépend de la betterave et de la canne à sucre ; le GPLc est du
propane, négocié sur un autre marché. Les variables construites autour du baril
de Brent n'y apportent rien et égarent le modèle.

Le programme mesure les deux méthodes à chaque entraînement et conserve celle
qui a réellement gagné, carburant par carburant et horizon par horizon. La page
d'accueil indique toujours laquelle a été employée.

### Pistes explorées et écartées

Consignées ici pour éviter de refaire le trajet. Toutes ont été mesurées, pas
supposées.

| Piste | Résultat |
|-------|----------|
| Prévoir le prix exact | 12 à 44 % **moins bien** que « le même prix qu'aujourd'hui » |
| Arbres de gradient | derniers des trois familles testées |
| Indice de peur du pétrole (OVX) | corrélation 0,03 avec l'avenir ; dégrade le modèle |
| Marge de raffinage | n'ajoute rien aux cotations de gros dont elle dérive |
| Indice base 100 pour le graphique | amplitudes trop inégales, les courbes ne se superposent pas |
| **Entraîner sur les 13 régions** | **neutre à 7 jours, −7 points à 14 jours** |
| Dispersion entre régions comme signal | neutre (±0,3 point) |

La piste régionale méritait d'être tentée : treize séries de 2 800 jours, c'est
soixante-treize fois plus de lignes d'entraînement. Elle échoue pour une raison
qui saute aux yeux une fois mesurée — les régions corrèlent à **0,99** avec la
moyenne nationale et bougent le **même jour** qu'elle. Ce ne sont pas treize
informations, mais treize copies. Le modèle s'y dilue en apprenant une « région
moyenne » qui ne correspond à aucune.

Quant aux niveaux de prix, ils diffèrent bien d'une région à l'autre, mais de
5 centimes entre les extrêmes — là où les stations d'un même bassin de vie
s'étalent couramment sur 25 centimes. Le comparateur de stations répond déjà à
cette question, et bien mieux.

---

## Installation sur un NAS Synology

L'image est compilée automatiquement par GitHub à chaque modification du code,
puis publiée sur `ghcr.io`. Le NAS se contente de la récupérer : il ne compile
rien, ce qui lui épargne un travail dont il est bien incapable.

### 1. Créer le projet dans Container Manager

**Container Manager** → **Projet** → **Créer** → *Créer un fichier
docker-compose.yml*, puis coller le contenu de
[`docker-compose.synology.yml`](docker-compose.synology.yml).

L'application est ensuite accessible sur `http://adresse-du-nas:8100`.

> Le port 8100 est celui du NAS ; le conteneur, lui, écoute toujours en 8000.
> En cas de conflit, seul le nombre de **gauche** est à changer dans la ligne
> `- "8100:8000"`.

Au premier démarrage, l'application constitue seule son historique : environ
210 Mo d'archives à télécharger et à analyser, soit **cinq à dix minutes**. La
page reste accessible pendant ce temps, simplement dépeuplée. Ensuite, elle se
met à jour toute seule chaque jour à 11 h.

### 2. Mises à jour automatiques

Le conteneur porte l'étiquette
`com.centurylinklabs.watchtower.scope=gestion-locative`, qui le place sous la
surveillance du Watchtower déjà en service sur le NAS. Aucun second Watchtower
n'est à lancer — et il ne le faudrait pas, le nom de conteneur entrerait en
conflit.

Le cycle complet, sans intervention : modification du code → push sur `main` →
GitHub compile et publie → Watchtower le remarque dans les cinq minutes →
le conteneur redémarre sur la nouvelle version. Les données, logées dans un
volume nommé, traversent l'opération intactes.

Une modification portant uniquement sur la documentation ne déclenche aucune
compilation : recompiler et redéployer une application dont le code n'a pas
bougé ne ferait que la redémarrer pour rien.

### En cas d'erreur « unauthorized » au téléchargement

L'image est publiée publiquement et se télécharge sans identification. Si le
NAS venait malgré tout à se plaindre, c'est que la visibilité du paquet a été
modifiée : `github.com/Mathiaspayet?tab=packages` → **suivi-prix-essence** →
*Package settings* → *Change visibility* → **Public**.

### Alertes par courriel (facultatif)

Décommentez les six lignes `SMTP_*` du fichier compose et complétez-les.
Avec Gmail, il faut créer un **mot de passe d'application** dans les réglages
de sécurité du compte Google : le mot de passe habituel est refusé par les
programmes.

Trois événements déclenchent un message, et uniquement au moment où la situation
bascule — jamais tant qu'elle se maintient :

1. la prévision passe à la baisse (inutile de faire le plein tout de suite) ;
2. la prévision passe à la hausse (mieux vaut ne pas attendre) ;
3. une station suivie descend sous le seuil qu'on lui a fixé.

---

## Installation sans Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python scripts/initialiser.py      # une seule fois : constitue l'historique
python scripts/entrainer.py        # entraîne les modèles

# Par la suite :
python scripts/entrainer.py --reajuster   # rapide, quotidien
python scripts/entrainer.py --valider     # complet, une fois par mois
uvicorn carburants.web.app:application --host 0.0.0.0 --port 8100
```

---

## D'où viennent les données

| Donnée | Source | Fréquence |
|--------|--------|-----------|
| Prix de ~9 800 stations | [data.economie.gouv.fr](https://data.economie.gouv.fr/explore/dataset/prix-des-carburants-en-france-flux-instantane-v2/) | continue |
| Historique depuis 2019 | [donnees.roulez-eco.fr](https://donnees.roulez-eco.fr/) | quotidienne |
| Baril de Brent | [FRED](https://fred.stlouisfed.org/series/DCOILBRENTEU) (Réserve fédérale de Saint-Louis) | jours ouvrés |
| Taux euro/dollar | [FRED](https://fred.stlouisfed.org/series/DEXUSEU) | jours ouvrés |

Toutes sont gratuites et ne demandent aucune inscription.

> **Outre-mer :** les départements 971, 972, 973, 974 et 976 ne figurent pas
> dans ces données. Le prix y est fixé chaque mois par arrêté préfectoral et
> s'impose à toutes les stations, qui n'ont donc aucun prix à déclarer. La
> comparaison entre stations n'y aurait de toute façon pas d'objet.

---

## Comment le projet est organisé

```
carburants/
├── config.py              tous les réglages, regroupés ici
├── base.py                schéma de la base SQLite
├── alertes.py             courriels
├── sources/
│   ├── stations.py        prix station par station (flux instantané)
│   ├── historique.py      reconstitution de l'historique depuis les archives
│   └── marche.py          Brent et taux de change
├── modele/
│   ├── caracteristiques.py   ce qu'on donne à voir au modèle
│   └── entrainement.py       entraînement, évaluation, prévision
└── web/
    ├── app.py             l'application web (FastAPI)
    └── templates/         la page
scripts/
├── initialiser.py         constitution de l'historique, à lancer une fois
├── mettre_a_jour.py       tâche quotidienne
└── entrainer.py           réentraînement à la demande
```

Pour comprendre le projet, deux fichiers suffisent : `config.py` pour les
réglages, et `modele/caracteristiques.py` pour la manière dont la prévision
est construite. Chacun est abondamment commenté.

---

## Une subtilité qui compte

Le fichier officiel ne contient pas un relevé quotidien par station : une
station n'y publie une ligne que lorsqu'elle **change** son prix. Calculer
naïvement la moyenne des lignes d'un jour donné reviendrait à ne moyenner que
les stations ayant bougé ce jour-là — un échantillon tout sauf représentatif.

`sources/historique.py` reconstitue donc, pour chaque station, le prix en
vigueur chaque jour en propageant le dernier changement connu. C'est ce qui rend
les moyennes comparables d'un jour à l'autre.

---

## Licence

MIT.
