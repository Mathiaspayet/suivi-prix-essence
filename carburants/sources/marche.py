"""Données de marché : baril de Brent et taux de change euro/dollar.

Les deux séries viennent de la FRED (base de données économiques de la Réserve
fédérale de Saint-Louis), en CSV et sans clé d'API. Le Brent est coté en
dollars par baril ; pour le comparer au prix à la pompe il faut donc à la fois
le convertir en euros et le ramener au litre — d'où la seconde série.
"""
import csv
import datetime as dt
import io

import httpx

from carburants import config


def _telecharger_serie(serie):
    """Récupère une série FRED et renvoie une liste de (date, valeur).

    La FRED écrit « . » pour les jours sans cotation (week-ends, jours fériés
    américains). Ces lignes sont ignorées plutôt que converties en zéro, ce qui
    créerait des chutes de prix imaginaires.
    """
    url = config.URL_FRED_CSV.format(serie=serie)
    reponse = httpx.get(url, timeout=60.0, follow_redirects=True)
    reponse.raise_for_status()

    lecteur = csv.reader(io.StringIO(reponse.text))
    entete = next(lecteur)
    if len(entete) < 2:
        raise ValueError(f"Format inattendu pour la série {serie} : {entete}")

    valeurs = []
    for ligne in lecteur:
        if len(ligne) < 2:
            continue
        date_texte, valeur_texte = ligne[0], ligne[1]
        if valeur_texte in (".", "", "NA"):
            continue
        try:
            valeurs.append((date_texte, float(valeur_texte)))
        except ValueError:
            continue
    return valeurs


def recuperer_brent(depuis=None):
    """Prix du baril de Brent en dollars, un point par jour ouvré."""
    valeurs = _telecharger_serie(config.SERIE_BRENT)
    if depuis:
        valeurs = [(d, v) for d, v in valeurs if d >= depuis]
    return [(d, "brent_usd", v) for d, v in valeurs]


def recuperer_eurusd(depuis=None):
    """Taux de change : nombre de dollars pour un euro."""
    valeurs = _telecharger_serie(config.SERIE_EURUSD)
    if depuis:
        valeurs = [(d, v) for d, v in valeurs if d >= depuis]
    return [(d, "eurusd", v) for d, v in valeurs]


def brent_en_euros_par_litre(brent_usd, taux_eurusd):
    """Convertit un baril en dollars vers un prix en euros par litre.

    C'est la « matière première » contenue dans un litre de carburant, hors
    raffinage, transport, marges et taxes. À titre de repère, quand le baril
    vaut 100 $ et l'euro 1,10 $, cela représente environ 0,57 € par litre —
    soit à peine un tiers du prix affiché à la pompe. Le reste est
    essentiellement constitué de taxes.
    """
    if not brent_usd or not taux_eurusd:
        return None
    return brent_usd / taux_eurusd / config.LITRES_PAR_BARIL


def rafraichir(depuis=None, journal=print):
    """Télécharge les deux séries et les enregistre en base."""
    from carburants import base

    lignes = recuperer_brent(depuis) + recuperer_eurusd(depuis)
    base.enregistrer_marche(lignes)
    journal(f"  marché : {len(lignes)} valeurs enregistrées")
    return len(lignes)
