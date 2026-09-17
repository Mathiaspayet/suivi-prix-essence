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


def rafraichir(journal=print, correspondance=None):
    """Met à jour l'enseigne de chaque station connue.

    « correspondance » permet de réutiliser un référentiel déjà téléchargé.
    Ce n'est pas une optimisation cosmétique : le téléchargement prend près
    d'une minute, et la tâche quotidienne en avait besoin deux fois — pour
    nommer les stations, puis pour agréger les prix par enseigne. Le
    récupérer une seule fois épargne une minute par nuit.
    """
    if correspondance is None:
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
