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

-- Journal des prévisions : chacune est conservée avec ce qui s'est réellement
-- produit à l'échéance. C'est ce qui permet de dire « l'outil a vu juste 78 %
-- du temps depuis son installation » plutôt que de s'en tenir aux chiffres
-- mesurés en laboratoire.
CREATE TABLE IF NOT EXISTS prevision (
    date_calcul        TEXT    NOT NULL,
    carburant          TEXT    NOT NULL,
    horizon_jours      INTEGER NOT NULL,
    date_cible         TEXT    NOT NULL,
    prix_actuel        REAL    NOT NULL,
    prix_prevu         REAL    NOT NULL,
    probabilite_hausse REAL    NOT NULL,
    sens               TEXT    NOT NULL,
    methode            TEXT,
    origine            TEXT    NOT NULL DEFAULT 'directe',
    -- Renseignés une fois la date cible atteinte, jamais avant.
    prix_reel          REAL,
    sens_correct       INTEGER,
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
        # Les toutes premières versions déclaraient une table « prevision »
        # d'une autre forme, que rien n'alimentait jamais. On la remplace,
        # après s'être assuré qu'elle est bien vide : supprimer une table
        # contenant des données serait une tout autre affaire.
        obsolete = cx.execute(
            """SELECT 1 FROM pragma_table_info('prevision')
               WHERE name = 'marge_erreur'"""
        ).fetchone()
        if obsolete:
            reste = cx.execute("SELECT COUNT(*) FROM prevision").fetchone()[0]
            if reste == 0:
                cx.execute("DROP TABLE prevision")

        cx.executescript(SCHEMA)
        # Une base créée par une version plus ancienne du projet peut manquer
        # de colonnes ajoutées depuis. SQLite ne sachant pas les ajouter
        # conditionnellement, on regarde d'abord ce qui existe.
        colonnes = {l["name"] for l in cx.execute("PRAGMA table_info(favori)")}
        if "seuil" not in colonnes:
            cx.execute("ALTER TABLE favori ADD COLUMN seuil REAL")

        colonnes = {l["name"] for l in cx.execute("PRAGMA table_info(prevision)")}
        for nom, type_sql in (
            ("probabilite_hausse", "REAL NOT NULL DEFAULT 0"),
            ("sens", "TEXT NOT NULL DEFAULT 'hausse'"),
            ("methode", "TEXT"),
            ("origine", "TEXT NOT NULL DEFAULT 'directe'"),
            ("prix_reel", "REAL"),
            ("sens_correct", "INTEGER"),
        ):
            if nom not in colonnes:
                cx.execute(f"ALTER TABLE prevision ADD COLUMN {nom} {type_sql}")

        # Créé après la migration : il porte sur une colonne que les bases
        # antérieures n'avaient pas encore.
        cx.execute(
            """CREATE INDEX IF NOT EXISTS idx_prevision_echeance
               ON prevision (date_cible, prix_reel)"""
        )


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


# --- Journal des prévisions ------------------------------------------------

def enregistrer_previsions(lignes):
    """Consigne les prévisions du jour, sans écraser celles déjà jugées.

    Une prévision déjà confrontée à la réalité n'est jamais réécrite : ce
    serait s'autoriser à corriger sa copie après coup.
    """
    with connexion() as cx:
        cx.executemany(
            """INSERT INTO prevision
                   (date_calcul, carburant, horizon_jours, date_cible,
                    prix_actuel, prix_prevu, probabilite_hausse, sens,
                    methode, origine)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date_calcul, carburant, horizon_jours) DO UPDATE SET
                   prix_prevu         = excluded.prix_prevu,
                   probabilite_hausse = excluded.probabilite_hausse,
                   sens               = excluded.sens,
                   methode            = excluded.methode
               WHERE prevision.prix_reel IS NULL""",
            lignes,
        )


def evaluer_previsions(journal=None):
    """Confronte à la réalité les prévisions arrivées à échéance.

    Une prévision n'est jugée que sur le sens annoncé, seul engagement pris —
    et seulement si le prix a bougé d'au moins un demi-centime, en deçà duquel
    parler de hausse ou de baisse n'a pas de sens.
    """
    with connexion() as cx:
        lignes = cx.execute(
            """SELECT p.rowid AS id, p.prix_actuel, p.sens, n.prix_moyen AS reel
               FROM prevision p
               JOIN prix_national n
                 ON n.date = p.date_cible AND n.carburant = p.carburant
               WHERE p.prix_reel IS NULL"""
        ).fetchall()

        jugements = []
        for ligne in lignes:
            variation = ligne["reel"] - ligne["prix_actuel"]
            if abs(variation) <= 0.005:
                correct = None           # trop plat pour trancher
            else:
                correct = int((variation > 0) == (ligne["sens"] == "hausse"))
            jugements.append((ligne["reel"], correct, ligne["id"]))

        cx.executemany(
            "UPDATE prevision SET prix_reel = ?, sens_correct = ? WHERE rowid = ?",
            jugements,
        )
    if journal and jugements:
        journal(f"  prévisions : {len(jugements)} arrivées à échéance et jugées")
    return len(jugements)


def palmares(carburant=None, horizon=None):
    """Bilan des prévisions réellement rendues, par carburant et par horizon."""
    conditions, parametres = ["sens_correct IS NOT NULL"], []
    if carburant:
        conditions.append("carburant = ?"); parametres.append(carburant)
    if horizon:
        conditions.append("horizon_jours = ?"); parametres.append(horizon)
    ou = " AND ".join(conditions)

    with connexion() as cx:
        global_ = cx.execute(
            f"""SELECT COUNT(*) AS n, SUM(sens_correct) AS justes,
                       MIN(date_calcul) AS depuis
                FROM prevision WHERE {ou}""",
            parametres,
        ).fetchone()
        detail = cx.execute(
            f"""SELECT carburant, horizon_jours, COUNT(*) AS n,
                       SUM(sens_correct) AS justes
                FROM prevision WHERE {ou}
                GROUP BY carburant, horizon_jours
                ORDER BY carburant, horizon_jours""",
            parametres,
        ).fetchall()
        en_attente = cx.execute(
            "SELECT COUNT(*) FROM prevision WHERE sens_correct IS NULL AND prix_reel IS NULL"
        ).fetchone()[0]

    def taux(justes, total):
        return round(justes / total * 100, 1) if total else None

    return {
        "nb_jugees": global_["n"],
        "nb_justes": global_["justes"] or 0,
        "taux_reussite": taux(global_["justes"] or 0, global_["n"]),
        "depuis": global_["depuis"],
        "en_attente": en_attente,
        "detail": [
            {
                "carburant": d["carburant"],
                "horizon": d["horizon_jours"],
                "nb": d["n"],
                "taux": taux(d["justes"] or 0, d["n"]),
            }
            for d in detail
        ],
    }
