"""Construction du tableau qui servira à entraîner le modèle.

Le principe d'un modèle de prévision : on lui montre des milliers de situations
passées sous la forme « voilà ce qu'on savait ce jour-là (les *caractéristiques*),
voilà ce qui s'est produit ensuite (la *cible*) », et il en tire des régularités.

Deux règles gouvernent tout ce module :

1. **Ne jamais utiliser une information du futur.** Une caractéristique calculée
   au jour J ne doit dépendre que de données connues au jour J. C'est l'erreur
   classique en prévision : elle donne des résultats spectaculaires à
   l'entraînement, et parfaitement inutiles en vrai.

2. **Prévoir la variation, pas le niveau.** Si l'on demande au modèle le prix
   dans 15 jours, il répondra « à peu près celui d'aujourd'hui » et affichera
   une précision flatteuse sans rien apporter. En lui demandant *de combien* le
   prix va bouger, on l'oblige à produire une information réellement nouvelle.
"""
import numpy as np
import pandas as pd

from carburants import base, config


def charger_series(carburant):
    """Assemble, jour par jour, le prix à la pompe et les données de marché.

    Les cotations de marché n'existent que les jours ouvrés : on reporte la
    dernière connue sur les week-ends et jours fériés. C'est légitime, puisque
    c'est bien la dernière information disponible ce jour-là.
    """
    with base.connexion() as cx:
        pompe = pd.read_sql_query(
            """SELECT date, prix_moyen, nb_stations FROM prix_national
               WHERE carburant = ? ORDER BY date""",
            cx, params=(carburant,), parse_dates=["date"],
        )
        marche_brut = pd.read_sql_query(
            "SELECT date, indicateur, valeur FROM marche ORDER BY date",
            cx, parse_dates=["date"],
        )

    if pompe.empty:
        raise ValueError(f"Aucune donnée en base pour le carburant {carburant!r}")

    pompe = pompe.set_index("date")
    marche = marche_brut.pivot(index="date", columns="indicateur", values="valeur")

    # Calendrier continu, du premier au dernier jour connu à la pompe.
    calendrier = pd.date_range(pompe.index.min(), pompe.index.max(), freq="D")
    tableau = pd.DataFrame(index=calendrier)
    tableau["prix"] = pompe["prix_moyen"].reindex(calendrier)
    tableau["nb_stations"] = pompe["nb_stations"].reindex(calendrier)

    # Report de la dernière cotation connue (jamais d'interpolation, qui
    # reviendrait à deviner une valeur à partir du futur).
    for colonne in ("brent_usd", "eurusd"):
        if colonne in marche.columns:
            tableau[colonne] = marche[colonne].reindex(calendrier).ffill()
        else:
            tableau[colonne] = np.nan

    # Le coût de la matière première contenue dans un litre.
    tableau["brent_eur_l"] = (
        tableau["brent_usd"] / tableau["eurusd"] / config.LITRES_PAR_BARIL
    )
    return tableau


def construire(carburant, horizon):
    """Produit le tableau (caractéristiques + cible) pour un horizon donné.

    « horizon » est le nombre de jours d'avance : 7, 14 ou 30.
    """
    t = charger_series(carburant)

    # --- L'écart à la pompe -------------------------------------------------
    # Différence entre le prix affiché et le coût de la matière première.
    # Il représente les taxes et les marges. Les taxes bougeant peu, cet écart
    # oscille autour d'une valeur d'équilibre : quand il s'en éloigne beaucoup,
    # il a tendance à y revenir. C'est le signal le plus utile du modèle.
    t["ecart"] = t["prix"] - t["brent_eur_l"]

    # Position de l'écart par rapport à son habitude récente, exprimée en
    # écarts-types. Une valeur de +2 signifie « les marges sont
    # exceptionnellement élevées » — donc une baisse probable ; -2 l'inverse.
    moyenne_ecart = t["ecart"].rolling(90, min_periods=30).mean()
    ecart_type = t["ecart"].rolling(90, min_periods=30).std()
    t["ecart_normalise"] = (t["ecart"] - moyenne_ecart) / ecart_type.replace(0, np.nan)

    # --- Dynamique récente --------------------------------------------------
    # Délai de répercussion mesuré sur 2019-2026 : la variation hebdomadaire à
    # la pompe épouse le mieux celle du baril décalée de **quatre jours**
    # (corrélation 0,68), et le lien s'éteint au-delà de deux semaines. La
    # répercussion française est donc rapide — bien plus que ne le laisse
    # entendre la littérature sur l'effet « fusée et plume », écrite à une
    # époque où les prix n'étaient pas publiés quotidiennement. Les fenêtres
    # courtes sont par conséquent les plus informatives ; les longues servent
    # surtout à situer la tendance de fond.
    for jours in (7, 14, 30, 60):
        t[f"var_brent_{jours}j"] = t["brent_eur_l"].diff(jours)
        t[f"var_pompe_{jours}j"] = t["prix"].diff(jours)

    # Part de la hausse du baril déjà répercutée à la pompe. Si le baril a
    # monté de 10 centimes et la pompe de 2, il reste 8 centimes « en attente ».
    t["rattrapage_en_attente"] = t["var_brent_30j"] - t["var_pompe_30j"]

    # Agitation du marché : une forte volatilité rend toute prévision plus fragile.
    t["volatilite_brent_30j"] = t["brent_eur_l"].diff().rolling(30).std()

    # Effet du change seul, isolé du prix du pétrole.
    t["var_eurusd_30j"] = t["eurusd"].diff(30)

    # --- Saisonnalité -------------------------------------------------------
    # La demande de carburant varie au fil de l'année (départs en vacances,
    # chauffage). Encodée par un sinus et un cosinus pour que décembre et
    # janvier restent voisins, ce qu'un simple numéro de mois ne traduirait pas.
    jour_annee = t.index.dayofyear
    t["saison_sin"] = np.sin(2 * np.pi * jour_annee / 365.25)
    t["saison_cos"] = np.cos(2 * np.pi * jour_annee / 365.25)

    # --- La cible -----------------------------------------------------------
    # De combien le prix aura-t-il bougé dans « horizon » jours ?
    # shift(-horizon) va chercher une valeur future : c'est la seule colonne
    # autorisée à le faire, puisque c'est précisément ce qu'on cherche à prévoir.
    t["cible"] = t["prix"].shift(-horizon) - t["prix"]

    return t


COLONNES_CARACTERISTIQUES = [
    "brent_eur_l",
    "ecart",
    "ecart_normalise",
    "var_brent_7j", "var_brent_14j", "var_brent_30j", "var_brent_60j",
    "var_pompe_7j", "var_pompe_14j", "var_pompe_30j", "var_pompe_60j",
    "rattrapage_en_attente",
    "volatilite_brent_30j",
    "var_eurusd_30j",
    "saison_sin", "saison_cos",
]


def separer(tableau, pour_entrainement=True):
    """Sépare le tableau en caractéristiques (X) et cible (y).

    Avec pour_entrainement=True, on ne garde que les jours complets : ceux dont
    on connaît à la fois toutes les caractéristiques et le résultat futur.
    """
    colonnes = COLONNES_CARACTERISTIQUES
    if pour_entrainement:
        complet = tableau.dropna(subset=colonnes + ["cible"])
        return complet[colonnes], complet["cible"], complet.index
    complet = tableau.dropna(subset=colonnes)
    return complet[colonnes], None, complet.index
