"""Réglages du projet, regroupés en un seul endroit.

Tout ce qui pourrait avoir besoin d'être modifié un jour est ici, plutôt que
dispersé dans le code. C'est la première chose à lire pour comprendre le projet.
"""
import os
from pathlib import Path

# --- Emplacements ---------------------------------------------------------
RACINE = Path(__file__).resolve().parent.parent
# Emplacement de la base et des modèles. Déplaçable par variable
# d'environnement, ce qui permet de pointer vers un volume du NAS ou de faire
# tourner un essai sans toucher aux vraies données.
DOSSIER_DONNEES = Path(os.environ.get("DOSSIER_DONNEES", RACINE / "donnees"))
BASE_SQLITE = DOSSIER_DONNEES / "carburants.sqlite"
DOSSIER_CACHE = DOSSIER_DONNEES / "cache"

# --- Préférences d'affichage ----------------------------------------------
# Commune ouverte par défaut, pour ne pas avoir à la retaper à chaque visite.
COMMUNE_PAR_DEFAUT = os.environ.get("COMMUNE_PAR_DEFAUT", "Mimizan")

# Rayon de recherche par défaut, en kilomètres. Trente convient mieux qu'une
# valeur plus courte en zone rurale : autour de Mimizan, passer de 15 à 30 km
# fait passer le choix de trois à treize stations, et l'écart entre la moins
# chère et la plus chère de 2 à 14 € par plein de 50 litres. Le voisinage
# immédiat cache souvent l'essentiel de l'économie possible.
RAYON_PAR_DEFAUT_KM = int(os.environ.get("RAYON_PAR_DEFAUT_KM", "30"))

# --- Carburants suivis ----------------------------------------------------
# Les noms sont ceux employés par le fichier officiel : on ne les invente pas.
CARBURANTS = ["Gazole", "SP95", "SP98", "E10", "E85", "GPLc"]

# Garde-fou : tout prix hors de cette fourchette est une erreur de saisie
# d'une station (on en trouve régulièrement : des 0.001 ou des 9.999).
PRIX_MINI_PLAUSIBLE = 0.30
PRIX_MAXI_PLAUSIBLE = 5.00

# --- Sources de données ---------------------------------------------------
# Prix instantanés des ~10 000 stations (mis à jour en continu).
URL_FLUX_INSTANTANE = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/records"
)
# Archive complète d'une année, au format ZIP contenant un gros XML.
URL_ARCHIVE_ANNUELLE = "https://donnees.roulez-eco.fr/opendata/annee/{annee}"
PREMIERE_ANNEE_DISPONIBLE = 2019

# Séries économiques de la Réserve fédérale de Saint-Louis (FRED).
# Téléchargeables en CSV sans clé d'API, ce qui évite toute inscription.
URL_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}"
SERIE_BRENT = "DCOILBRENTEU"   # baril de Brent, en dollars
SERIE_EURUSD = "DEXUSEU"       # combien de dollars pour 1 euro

# Produits déjà raffinés, cotés au port de New York. Ce ne sont pas des
# curiosités américaines : les marchés du raffiné sont mondiaux et étroitement
# liés, et ces deux séries sont les seules cotations quotidiennes gratuites
# disponibles. Le pétrole brut ne se met pas dans un réservoir ; une station
# achète du gazole ou de l'essence déjà raffinés, dont le prix a sa propre
# dynamique — pénuries de raffinage, saisonnalité, arbitrages. Les substituer
# au brut fait gagner environ deux points de justesse.
SERIE_GAZOLE_RAFFINE = "DHOILNYH"    # fioul domestique, très proche du gazole
SERIE_ESSENCE_RAFFINEE = "DGASNYH"   # essence conventionnelle

# À quel produit de gros rattacher chaque carburant de la pompe.
# L'E85 et le GPLc n'y figurent pas : le premier est de l'éthanol, le second du
# propane, et ni l'un ni l'autre ne suit le marché du pétrole.
RAFFINE_PAR_CARBURANT = {
    "Gazole": SERIE_GAZOLE_RAFFINE,
    "SP95": SERIE_ESSENCE_RAFFINEE,
    "SP98": SERIE_ESSENCE_RAFFINEE,
    "E10": SERIE_ESSENCE_RAFFINEE,
}

# Ces cotations sont en dollars par gallon américain.
LITRES_PAR_GALLON = 3.785411784

# Un baril « pétrolier » vaut exactement 42 gallons américains.
LITRES_PAR_BARIL = 158.987294928

# --- Reconstruction du prix théorique -------------------------------------
# La TVA s'applique sur le prix complet, taxes comprises. Une hausse d'un
# centime du baril arrive donc à la pompe amplifiée de 20 %.
TAUX_TVA = 1.20

# Fenêtre sur laquelle on suit les taxes et les marges. Elles dérivent
# lentement : les figer sur une moyenne fixe donne 12,6 centimes d'erreur,
# les suivre sur trois mois la ramène à 4,4. Une fenêtre plus courte
# collerait mieux encore, mais absorberait le retard qu'on cherche
# justement à faire voir.
FENETRE_ECART_JOURS = 90

# --- Alertes --------------------------------------------------------------
# Une alerte n'a de valeur que si elle est rare. Ces seuils sont calibrés sur
# l'historique pour produire ensemble une trentaine de courriels par an, soit
# un tous les douze jours environ. Les relever les espace encore.

# Un mouvement est jugé brutal quand la variation sur trois jours dépasse ce
# multiple de la variation habituelle. À 4, cela représente environ sept
# baisses signalées par an sur le gazole.
FACTEUR_MOUVEMENT_BRUTAL = 4.0

# Écart minimal, en euros par litre, pour signaler qu'une prévision a été
# démentie. En dessous de trois centimes, l'erreur ne mérite pas un courriel.
ECART_PREVISION_DEMENTIE = 0.03

# Silence imposé après un signalement de prévision démentie. Les prévisions de
# jours voisins portent sur des fenêtres qui se recouvrent : quand le marché
# part à contresens, chacune est démentie à son tour et l'on recevrait le même
# avertissement trois jours de suite. Un seul message par épisode suffit.
JOURS_SILENCE_APRES_DEMENTI = 14

# --- Modèle de prévision --------------------------------------------------
# Espacement des validations complètes. Départager les méthodes coûte près de
# neuf dixièmes du temps de calcul — six plis fois deux candidats, soit douze
# entraînements par carburant et par horizon, contre un seul pour le
# réajustement. Or ce choix est stable sur des mois : rien ne justifie de le
# refaire chaque nuit sur le processeur d'un NAS. Entre deux validations, la
# méthode retenue est simplement réajustée aux données du jour (205 s contre 20).
JOURS_ENTRE_VALIDATIONS = 30
# À combien de jours d'avance on cherche à prévoir.
HORIZONS_JOURS = [7, 14, 30]
# Fiabilité d'une moyenne quotidienne. Deux garde-fous complémentaires :
#  - un plancher absolu, sous lequel l'échantillon est trop petit ;
#  - une part minimale de la couverture habituelle du carburant, pour écarter
#    les premiers jours d'une archive où l'on ne connaît encore qu'une fraction
#    des stations. Le seuil est relatif à chaque carburant : le GPLc n'est
#    vendu que dans ~1 700 stations, contre ~9 800 pour le gazole.
NB_STATIONS_MINIMUM = 300
PART_MINIMALE_COUVERTURE = 0.5
