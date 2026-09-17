"""Ce que les prix viennent de faire, par opposition à ce qu'ils vont faire.

Trois grandeurs répondent à la même question — « ça monte ou ça descend en ce
moment ? » — mais à trois étages : la matière première cotée sur les marchés,
la moyenne payée à la pompe en France, et les stations autour de chez soi. Les
mettre côte à côte, c'est voir la répercussion arriver : le baril grimpe de
trois pour cent quand la pompe n'a pris qu'un demi-centime, et l'on sait ce
qui attend le prochain plein.

Deux précautions traversent tout le module.

La première tient au fichier officiel, qui n'enregistre qu'un *changement* de
prix. Un relevé peut donc manquer à une date donnée sans que rien ne soit
anormal — simplement, la station n'a pas bougé. On prend alors le dernier
relevé connu à cette date ou avant, ce qui est aussi la lecture juste.

La seconde tient aux marchés, qui ne cotent ni le week-end ni les jours
fériés, et dont les données publiques accusent quelques jours de retard. Une
« variation sur 24 heures » y serait un mensonge : on parle de la *dernière
séance*, et l'on affiche sa date.
"""

import datetime as dt

from carburants import base


def _releve_le_plus_recent(serie, cible):
    """Dernière valeur connue à la date visée ou avant, et sa date.

    « serie » est une liste de (date, valeur) triée par date croissante.
    """
    retenu = None
    for date, valeur in serie:
        if date <= cible:
            retenu = (date, valeur)
        else:
            break
    return retenu


def _recul(date_texte, jours):
    return (dt.date.fromisoformat(date_texte) - dt.timedelta(days=jours)).isoformat()


def _ecart(depart, arrivee):
    """Variation absolue et relative entre deux valeurs, ou None."""
    if depart is None or arrivee is None or not depart:
        return None, None
    return arrivee - depart, (arrivee - depart) / depart * 100


def _serie_marche(cx, indicateur, depuis):
    lignes = cx.execute(
        """SELECT date, valeur FROM marche
           WHERE indicateur = ? AND date >= ? ORDER BY date""",
        (indicateur, depuis),
    ).fetchall()
    return [(l["date"], l["valeur"]) for l in lignes]


def brut():
    """Cours du Brent : dernière séance et sept jours, en dollars le baril.

    Le repère de « 24 heures » est ici la cotation précédente, quelle que
    soit sa date : un lundi se compare au vendredi qui le précède.
    """
    with base.connexion() as cx:
        fin = cx.execute(
            "SELECT MAX(date) FROM marche WHERE indicateur = 'brent_usd'"
        ).fetchone()[0]
        if not fin:
            return None
        serie = _serie_marche(cx, "brent_usd", _recul(fin, 30))

    if len(serie) < 2:
        return None
    date_fin, valeur = serie[-1]
    date_avant, valeur_avant = serie[-2]
    precedent_7j = _releve_le_plus_recent(serie, _recul(date_fin, 7))

    seance_abs, seance_pct = _ecart(valeur_avant, valeur)
    semaine_abs, semaine_pct = _ecart(precedent_7j[1] if precedent_7j else None, valeur)
    return {
        "valeur": round(valeur, 2),
        "unite": "$ / baril",
        "date": date_fin,
        "date_precedente": date_avant,
        "court_pct": None if seance_pct is None else round(seance_pct, 1),
        "court_abs": None if seance_abs is None else round(seance_abs, 2),
        "semaine_pct": None if semaine_pct is None else round(semaine_pct, 1),
        "semaine_abs": None if semaine_abs is None else round(semaine_abs, 2),
        "retard_jours": (dt.date.today() - dt.date.fromisoformat(date_fin)).days,
    }


def pompe(carburant):
    """Moyenne nationale à la pompe : 24 heures et sept jours, en centimes."""
    with base.connexion() as cx:
        lignes = cx.execute(
            """SELECT date, prix_moyen FROM prix_national
               WHERE carburant = ? ORDER BY date DESC LIMIT 40""",
            (carburant,),
        ).fetchall()
    serie = [(l["date"], l["prix_moyen"]) for l in reversed(lignes)]
    if len(serie) < 2:
        return None

    date_fin, valeur = serie[-1]
    veille = _releve_le_plus_recent(serie, _recul(date_fin, 1))
    semaine = _releve_le_plus_recent(serie, _recul(date_fin, 7))
    court_abs, court_pct = _ecart(veille[1] if veille else None, valeur)
    semaine_abs, semaine_pct = _ecart(semaine[1] if semaine else None, valeur)
    return {
        "valeur": round(valeur, 3),
        "unite": "€ / L",
        "date": date_fin,
        "court_cts": None if court_abs is None else round(court_abs * 100, 1),
        "court_pct": None if court_pct is None else round(court_pct, 1),
        "semaine_cts": None if semaine_abs is None else round(semaine_abs * 100, 1),
        "semaine_pct": None if semaine_pct is None else round(semaine_pct, 1),
    }
