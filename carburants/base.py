"""Base de données SQLite : création du schéma et accès.

SQLite stocke toute la base dans un unique fichier (donnees/carburants.sqlite).
Aucun serveur à installer, et la sauvegarde consiste à copier ce fichier —
ce qui est exactement ce qu'on veut sur un NAS.
"""
import sqlite3
from contextlib import contextmanager

from carburants import config

# Le schéma est décrit une fois pour toutes ici. « IF NOT EXISTS » rend le
# script rejouable : on peut le relancer sans rien casser.
SCHEMA = """
-- Moyenne nationale d'un carburant, un enregistrement par jour.
-- C'est la table qui sert à entraîner le modèle de prévision.
CREATE TABLE IF NOT EXISTS prix_national (
    date        TEXT    NOT NULL,
    carburant   TEXT    NOT NULL,
    prix_moyen  REAL    NOT NULL,
    prix_mini   REAL,
    prix_maxi   REAL,
    nb_stations INTEGER NOT NULL,
    PRIMARY KEY (date, carburant)
);

-- Indicateurs de marché : baril de Brent, taux de change euro/dollar.
CREATE TABLE IF NOT EXISTS marche (
    date       TEXT NOT NULL,
    indicateur TEXT NOT NULL,
    valeur     REAL NOT NULL,
    PRIMARY KEY (date, indicateur)
);

-- Référentiel des stations : leur identité et leur position.
CREATE TABLE IF NOT EXISTS station (
    id               TEXT PRIMARY KEY,
    adresse          TEXT,
    ville            TEXT,
    code_postal      TEXT,
    latitude         REAL,
    longitude        REAL,
    departement      TEXT,
    code_departement TEXT,
    region           TEXT,
    maj              TEXT
);

-- Relevé quotidien du prix de chaque station (alimenté par le flux instantané).
CREATE TABLE IF NOT EXISTS prix_station (
    date       TEXT NOT NULL,
    station_id TEXT NOT NULL,
    carburant  TEXT NOT NULL,
    prix       REAL NOT NULL,
    PRIMARY KEY (date, station_id, carburant)
);
CREATE INDEX IF NOT EXISTS idx_prix_station_station
    ON prix_station (station_id, carburant, date);

-- Stations que l'utilisateur a choisi de surveiller.
CREATE TABLE IF NOT EXISTS favori (
    station_id TEXT PRIMARY KEY,
    surnom     TEXT,
    seuil      REAL,          -- alerte si le prix descend sous cette valeur
    ajoute_le  TEXT NOT NULL
);

-- Mémoire des alertes déjà envoyées, pour ne pas répéter le même message
-- chaque jour tant que la situation ne change pas.
CREATE TABLE IF NOT EXISTS etat_alerte (
    cle          TEXT PRIMARY KEY,
    valeur       TEXT NOT NULL,
    envoye_le    TEXT NOT NULL
);

-- Prévisions calculées, conservées pour pouvoir juger le modèle après coup.
CREATE TABLE IF NOT EXISTS prevision (
    date_calcul    TEXT NOT NULL,
    carburant      TEXT NOT NULL,
    horizon_jours  INTEGER NOT NULL,
    date_cible     TEXT NOT NULL,
    prix_actuel    REAL NOT NULL,
    prix_prevu     REAL NOT NULL,
    marge_erreur   REAL NOT NULL,
    PRIMARY KEY (date_calcul, carburant, horizon_jours)
);
"""


@contextmanager
def connexion():
    """Ouvre la base, valide les écritures à la sortie, et referme toujours.

    Employé avec « with », ce qui garantit la fermeture même en cas d'erreur :

        with connexion() as cx:
            cx.execute("SELECT ...")
    """
    config.DOSSIER_DONNEES.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(config.BASE_SQLITE)
    cx.row_factory = sqlite3.Row          # accès aux colonnes par leur nom
    cx.execute("PRAGMA journal_mode = WAL")   # lectures possibles pendant l'écriture
    try:
        yield cx
        cx.commit()
    finally:
        cx.close()


def initialiser():
    """Crée les tables manquantes et complète celles d'une version antérieure."""
    with connexion() as cx:
        cx.executescript(SCHEMA)
        # Une base créée par une version plus ancienne du projet peut manquer
        # de colonnes ajoutées depuis. SQLite ne sachant pas les ajouter
        # conditionnellement, on regarde d'abord ce qui existe.
        colonnes = {l["name"] for l in cx.execute("PRAGMA table_info(favori)")}
        if "seuil" not in colonnes:
            cx.execute("ALTER TABLE favori ADD COLUMN seuil REAL")


def enregistrer_prix_national(lignes):
    """Insère ou met à jour des moyennes nationales.

    « lignes » est une liste de tuples
    (date, carburant, prix_moyen, prix_mini, prix_maxi, nb_stations).
    """
    with connexion() as cx:
        cx.executemany(
            """INSERT INTO prix_national
                   (date, carburant, prix_moyen, prix_mini, prix_maxi, nb_stations)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date, carburant) DO UPDATE SET
                   prix_moyen  = excluded.prix_moyen,
                   prix_mini   = excluded.prix_mini,
                   prix_maxi   = excluded.prix_maxi,
                   nb_stations = excluded.nb_stations""",
            lignes,
        )
        return cx.total_changes


def enregistrer_marche(lignes):
    """Insère ou met à jour des valeurs de marché (date, indicateur, valeur)."""
    with connexion() as cx:
        cx.executemany(
            """INSERT INTO marche (date, indicateur, valeur)
               VALUES (?, ?, ?)
               ON CONFLICT(date, indicateur) DO UPDATE SET
                   valeur = excluded.valeur""",
            lignes,
        )
        return cx.total_changes


def annees_deja_importees():
    """Renvoie les années pour lesquelles on a déjà des moyennes nationales.

    Sert à ne pas retélécharger 26 Mo d'archive pour rien.
    """
    with connexion() as cx:
        lignes = cx.execute(
            """SELECT substr(date, 1, 4) AS annee, COUNT(*) AS n
               FROM prix_national GROUP BY annee ORDER BY annee"""
        ).fetchall()
    return {int(l["annee"]): l["n"] for l in lignes}
