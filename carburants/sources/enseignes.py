"""Enseignes des stations : d'où elles viennent, et comment on les normalise.

Le fichier officiel des prix ne publie pas l'enseigne — quarante-sept champs,
aucun ne la porte. On la récupère donc d'un référentiel communautaire publié
sur data.gouv.fr, qui associe l'identifiant officiel de chaque station à un nom
normalisé, obtenu par croisement avec OpenStreetMap. Couverture constatée :
98 % des stations en service.

Ce référentiel demande néanmoins un second nettoyage, car OpenStreetMap est
alimenté par des contributeurs indépendants qui n'écrivent pas tous pareil :
« E.Leclerc » et « E. Leclerc » y coexistent, tout comme « Total » et
« TotalEnergies » — le premier n'étant que l'ancien nom du second, encore
présent là où personne n'a mis à jour la carte.
"""
import csv
import io
import re
import time

import httpx

from carburants import base

# Référentiel publié sous licence ODbL : sa mention est obligatoire, et elle
# figure au pied de la page.
URL_REFERENTIEL = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "referentiel-des-noms-et-enseignes-de-stations-service-enrichi-par-openstreetmap/"
)

# Regroupements appliqués aux noms bruts. Deux cas bien distincts :
#
#   - les variantes d'orthographe, qui sont du bruit pur et qu'il faut fondre ;
#   - les formats commerciaux réellement différents, qu'il faut au contraire
#     garder séparés. « Total Access » n'est pas « TotalEnergies » : c'est le
#     format à bas coût du même groupe, avec sa propre politique de prix.
REGROUPEMENTS = [
    (r"^(e\.?\s*leclerc|leclerc)$",                    "E.Leclerc"),
    (r"^total\s*access$",                              "Total Access"),
    (r"^(total\s*energies|totalenergies|total)$",      "TotalEnergies"),
    (r"^(super\s*u|syst[eè]me\s*u|station\s*u|u\s*express|u)$", "U"),
    (r"^intermarch[eé].*$",                            "Intermarché"),
    (r"^carrefour\s*market$",                          "Carrefour Market"),
    (r"^carrefour\s*(contact|express|city)$",          "Carrefour Contact"),
    (r"^carrefour.*$",                                 "Carrefour"),
    (r"^esso\s*express$",                              "Esso Express"),
    (r"^esso$",                                        "Esso"),
    (r"^auchan.*$",                                    "Auchan"),
    (r"^avia.*$",                                      "Avia"),
    (r"^(g[ée]ant|casino).*$",                         "Casino"),
]


def normaliser(nom):
    """Ramène un nom brut à son enseigne canonique, ou None s'il est vide."""
    propre = " ".join((nom or "").strip().split())
    if not propre:
        return None
    minuscule = propre.lower()
    for motif, canonique in REGROUPEMENTS:
        if re.match(motif, minuscule):
            return canonique
    return propre


def _recuperer(url, delai=60):
    """Télécharge une adresse en réessayant les coupures passagères.

    Les serveurs de data.gouv ferment régulièrement la connexion en cours
    d'échange, sans que rien ne soit en panne : un simple nouvel essai aboutit.
    Sans cette obstination, la mise à jour du jour échouerait pour une raison
    qui n'existe plus une seconde plus tard.
    """
    derniere = None
    for tentative in range(5):
        try:
            reponse = httpx.get(url, timeout=delai, follow_redirects=True)
            reponse.raise_for_status()
            return reponse
        except Exception as erreur:
            derniere = erreur
            time.sleep(2 * (tentative + 1))
    raise derniere


def _url_du_fichier():
    """Trouve l'adresse du CSV courant en interrogeant l'API de data.gouv.

    L'adresse du fichier contient sa date de publication et change donc à
    chaque mise à jour : la coder en dur condamnerait le programme à
    télécharger éternellement la même version.
    """
    reponse = _recuperer(URL_REFERENTIEL)
    for ressource in reponse.json().get("resources", []):
        if (ressource.get("format") or "").lower() == "csv":
            return ressource["url"]
    raise ValueError("Aucun fichier CSV dans le référentiel des enseignes.")


def telecharger():
    """Renvoie {identifiant de station: enseigne normalisée}."""
    reponse = _recuperer(_url_du_fichier(), delai=180)
    lecteur = csv.DictReader(io.StringIO(reponse.text))
    correspondance = {}
    for ligne in lecteur:
        identifiant = str(ligne.get("id_station_officiel", "")).strip()
        enseigne = normaliser(ligne.get("nom_normalise"))
        if identifiant and enseigne:
            correspondance[identifiant] = enseigne
    return correspondance


def rafraichir(journal=print):
    """Met à jour l'enseigne de chaque station connue."""
    correspondance = telecharger()
    with base.connexion() as cx:
        connues = [l["id"] for l in cx.execute("SELECT id FROM station")]
        a_ecrire = [
            (correspondance[i], i) for i in connues if i in correspondance
        ]
        cx.executemany("UPDATE station SET enseigne = ? WHERE id = ?", a_ecrire)

    part = len(a_ecrire) / len(connues) * 100 if connues else 0
    journal(f"  enseignes : {len(a_ecrire)} stations nommées ({part:.0f} %)")
    return len(a_ecrire)


def classement(carburant="Gazole", hors_autoroute=True, minimum=40):
    """Prix médian par enseigne, du moins cher au plus cher.

    Les stations d'autoroute sont écartées par défaut, et ce n'est pas un
    détail : elles se vendent nettement plus cher, et les réseaux n'en
    comportent pas la même proportion — Shell en compte sept sur dix, les
    supermarchés aucune. Les mélanger reviendrait à imputer à la politique
    commerciale d'une enseigne ce qui ne tient qu'à l'emplacement de ses
    stations.
    """
    condition = "AND s.sur_autoroute = 0" if hors_autoroute else ""
    with base.connexion() as cx:
        lignes = cx.execute(
            f"""SELECT s.enseigne, p.prix
                FROM prix_station p JOIN station s ON s.id = p.station_id
                WHERE p.carburant = ?
                  AND p.date = (SELECT MAX(date) FROM prix_station)
                  AND s.enseigne IS NOT NULL {condition}""",
            (carburant,),
        ).fetchall()

    par_enseigne = {}
    for ligne in lignes:
        par_enseigne.setdefault(ligne["enseigne"], []).append(ligne["prix"])

    retenues = {e: v for e, v in par_enseigne.items() if len(v) >= minimum}
    if not retenues:
        return []

    def mediane(valeurs):
        ordonnees = sorted(valeurs)
        milieu = len(ordonnees) // 2
        if len(ordonnees) % 2:
            return ordonnees[milieu]
        return (ordonnees[milieu - 1] + ordonnees[milieu]) / 2

    toutes = [p for v in retenues.values() for p in v]
    reference = mediane(toutes)
    resultat = [
        {
            "enseigne": enseigne,
            "prix_median": round(mediane(valeurs), 3),
            "ecart_cts": round((mediane(valeurs) - reference) * 100, 1),
            "nb_stations": len(valeurs),
        }
        for enseigne, valeurs in retenues.items()
    ]
    resultat.sort(key=lambda r: r["prix_median"])
    return resultat


def comparatif(carburant="Gazole", minimum=50):
    """Tableau comparatif des enseignes : niveau de prix, marge, réactivité.

    **Sur la marge.** Les taxes sont identiques pour toutes les enseignes sur
    un même carburant, et le carburant de gros s'achète à peu près au même
    prix. L'écart de prix entre deux réseaux est donc, à la TVA près, un écart
    de marge — ce que l'on peut affirmer sans connaître le montant des taxes,
    qui s'annule dans la soustraction.

    Le prix affiché comprend la TVA : un écart de trente centimes à la pompe
    correspond à vingt-cinq centimes de marge, puisque la marge supplémentaire
    est elle aussi taxée à 20 %.

    **Sur la réactivité.** La variation quotidienne moyenne mesure la fréquence
    des ajustements. Une enseigne réactive suit le marché de près, à la hausse
    comme à la baisse ; une enseigne inerte lisse davantage. Ce n'est ni une
    qualité ni un défaut, mais cela explique pourquoi certaines paraissent
    « baisser en premier » alors qu'elles ne font que bouger plus souvent.
    """
    from carburants import config

    niveaux = classement(carburant, hors_autoroute=True, minimum=minimum)
    if not niveaux:
        return []

    with base.connexion() as cx:
        agitation = {
            l["enseigne"]: l["agitation"]
            for l in cx.execute(
                """SELECT enseigne,
                          AVG(ABS(prix_moyen - precedent)) * 100 AS agitation
                   FROM (SELECT enseigne, date, prix_moyen,
                                LAG(prix_moyen) OVER (PARTITION BY enseigne ORDER BY date)
                                  AS precedent
                         FROM prix_enseigne
                         WHERE carburant = ? AND date >= date('now', '-365 day'))
                   WHERE precedent IS NOT NULL
                   GROUP BY enseigne""",
                (carburant,),
            )
        }

    moins_cher = niveaux[0]["prix_median"]
    for rang, ligne in enumerate(niveaux, start=1):
        surcout = ligne["prix_median"] - moins_cher
        ligne["rang"] = rang
        ligne["surcout_cts"] = round(surcout * 100, 1)
        # La marge supplémentaire est elle-même soumise à la TVA : on la retire
        # pour ne garder que ce que l'enseigne encaisse réellement en plus.
        ligne["marge_supplementaire_cts"] = round(surcout / config.TAUX_TVA * 100, 1)
        ligne["surcout_plein_50l"] = round(surcout * 50, 2)
        ligne["agitation_cts"] = round(agitation.get(ligne["enseigne"], 0), 2)
    return niveaux


def historique(carburant="Gazole", jours=365, minimum_stations=60):
    """Séries quotidiennes par enseigne, pour le graphique comparatif."""
    with base.connexion() as cx:
        lignes = cx.execute(
            """SELECT date, enseigne, prix_moyen FROM prix_enseigne
               WHERE carburant = ? AND date >= date('now', ?)
                 AND enseigne IN (
                     SELECT enseigne FROM prix_enseigne
                     WHERE carburant = ?
                     GROUP BY enseigne HAVING AVG(nb_stations) >= ?)
               ORDER BY date""",
            (carburant, f"-{jours} day", carburant, minimum_stations),
        ).fetchall()

    par_enseigne = {}
    for ligne in lignes:
        par_enseigne.setdefault(ligne["enseigne"], []).append(
            {"date": ligne["date"], "prix": round(ligne["prix_moyen"], 3)}
        )
    return par_enseigne
