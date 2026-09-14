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

Justesse mesurée sur des périodes que le modèle n'avait jamais vues
(2019-2026, validation glissante) :

| Carburant | à 7 jours | à 14 jours | à 30 jours | Méthode retenue |
|-----------|-----------|------------|------------|-----------------|
| Gazole    | 74 %      | 68 %       | 65 %       | tendance, puis modèle à 30 j |
| SP95      | 78 %      | 72 %       | 62 %       | modèle |
| SP98      | 77 %      | 71 %       | 63 %       | modèle |
| E10       | 73 %      | 68 %       | 61 %       | modèle |
| E85       | 76 %      | 82 %       | 69 %       | tendance |
| GPLc      | 74 %      | 78 %       | 67 %       | tendance |

Autrement dit : **à sept jours, l'outil se trompe environ une fois sur quatre.**
À trente jours, une fois sur trois. Et il ne verra jamais venir une crise
géopolitique ni un changement de fiscalité.

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

---

## Installation sur un NAS

Il faut Docker, disponible sur la plupart des NAS Synology et QNAP.

```bash
git clone https://github.com/Mathiaspayet/suivi-prix-essence.git
cd suivi-prix-essence
docker compose up -d
```

Puis ouvrez `http://adresse-de-votre-nas:8000`.

Au premier démarrage, l'application constitue seule son historique : environ
210 Mo d'archives à télécharger et à analyser, soit **cinq à dix minutes**. La
page reste accessible pendant ce temps, simplement dépeuplée. Ensuite, elle se
met à jour toute seule chaque jour à 11 h.

### Alertes par courriel (facultatif)

```bash
cp .env.exemple .env
nano .env          # renseignez vos identifiants de messagerie
docker compose up -d --force-recreate
```

Avec Gmail, il faut créer un **mot de passe d'application** dans les réglages de
sécurité du compte Google : le mot de passe habituel est refusé par les
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
uvicorn carburants.web.app:application --host 0.0.0.0 --port 8000
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
