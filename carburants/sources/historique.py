"""Reconstitution de l'historique des prix à partir des archives annuelles.

Le fichier officiel ne contient pas un relevé par jour : une station n'y publie
une ligne que lorsqu'elle **change** son prix. Pour obtenir une moyenne
nationale quotidienne, il faut donc « propager » le dernier prix connu de chaque
station jusqu'au changement suivant. C'est tout l'objet de ce module.

Exemple, pour une station qui n'a publié que deux lignes en janvier :

    02/01 -> 1,638      03/01 -> 1,649

    ... son prix vaut 1,638 le 2, puis 1,649 du 3 janvier jusqu'à son
    prochain changement. Sans cette propagation, la moyenne du 4 janvier
    serait calculée sur les rares stations ayant publié ce jour-là,
    c'est-à-dire sur un échantillon biaisé.
"""
import datetime as dt
import xml.etree.ElementTree as ET
import zipfile

import numpy as np

from carburants import config

# Le fichier officiel nomme les carburants ainsi ; on garde ses noms.
NOMS_XML = {
    "Gazole": "Gazole",
    "SP95": "SP95",
    "SP98": "SP98",
    "E10": "E10",
    "E85": "E85",
    "GPLc": "GPLc",
}


def chemin_archive(annee):
    """Emplacement local du ZIP d'une année."""
    return config.DOSSIER_CACHE / f"PrixCarburants_annuel_{annee}.zip"


def telecharger_archive(annee, forcer=False):
    """Télécharge l'archive d'une année, sauf si elle est déjà en cache.

    Chaque archive pèse ~25 Mo. On la garde sur le disque pour éviter de la
    retélécharger à chaque essai.
    """
    import httpx

    destination = chemin_archive(annee)
    if destination.exists() and not forcer:
        return destination

    config.DOSSIER_CACHE.mkdir(parents=True, exist_ok=True)
    url = config.URL_ARCHIVE_ANNUELLE.format(annee=annee)
    temporaire = destination.with_suffix(".part")
    with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as reponse:
        reponse.raise_for_status()
        with open(temporaire, "wb") as sortie:
            for morceau in reponse.iter_bytes(chunk_size=1 << 20):
                sortie.write(morceau)
    temporaire.rename(destination)          # renommage atomique : pas de fichier à moitié écrit
    return destination


def _normaliser_prix(brut):
    """Convertit la valeur du fichier en euros par litre, ou None si invalide.

    Les archives anciennes expriment parfois le prix en millièmes d'euro
    (« 1430 » pour 1,430 €). On rattrape ce cas, puis on écarte tout ce qui
    reste hors d'une fourchette plausible : les erreurs de saisie des stations
    (0,001 € ou 9,999 €) fausseraient la moyenne nationale.
    """
    try:
        valeur = float(brut)
    except (TypeError, ValueError):
        return None
    if valeur > config.PRIX_MAXI_PLAUSIBLE:
        valeur = valeur / 1000.0
    if config.PRIX_MINI_PLAUSIBLE <= valeur <= config.PRIX_MAXI_PLAUSIBLE:
        return valeur
    return None


def _propager(serie):
    """Reporte chaque valeur connue sur les jours suivants (« forward fill »).

    Entrée  : [nan, 1.6, nan, nan, 1.7, nan]
    Sortie  : [nan, 1.6, 1.6, 1.6, 1.7, 1.7]

    Les jours situés **avant** le premier relevé restent à nan : on ne sait
    rien du prix de cette station à ce moment-là, et inventer une valeur
    fausserait la moyenne.
    """
    connus = ~np.isnan(serie)
    if not connus.any():
        return serie
    # Pour chaque position, l'indice du dernier relevé connu à sa gauche.
    indices = np.where(connus, np.arange(serie.size), 0)
    np.maximum.accumulate(indices, out=indices)
    propagee = serie[indices]
    premier = int(np.argmax(connus))
    propagee[:premier] = np.nan
    return propagee


def extraire_stations(annee, identifiants, journal=print):
    """Historique quotidien de quelques stations nommément désignées.

    Conserver l'historique des 9 800 stations représenterait neuf millions de
    lignes et près de quatre cents mégaoctets pour la seule année en cours —
    disproportionné sur un NAS, et sans objet : personne ne consulte la courbe
    d'une station qu'il ne fréquentera jamais. On n'extrait donc que celles du
    voisinage et les stations suivies.

    Les lignes rejoignent la table « prix_station », celle-là même que la
    collecte quotidienne alimente : l'historique reconstitué et les relevés du
    jour s'y raccordent sans couture.
    """
    identifiants = set(identifiants)
    if not identifiants:
        return []

    debut_annee = dt.date(annee, 1, 1)
    fin_annee = dt.date(annee, 12, 31)
    derniere_date = min(fin_annee, dt.date.today())
    nb_jours = (fin_annee - debut_annee).days + 1
    nb_jours_utiles = (derniere_date - debut_annee).days + 1

    lignes = []
    with zipfile.ZipFile(chemin_archive(annee)) as zip_ouvert:
        with zip_ouvert.open(zip_ouvert.namelist()[0]) as flux:
            contexte = ET.iterparse(flux, events=("start", "end"))
            _, racine = next(contexte)
            for evenement, element in contexte:
                if evenement != "end" or element.tag != "pdv":
                    continue
                identifiant = str(element.get("id") or "").strip()
                if identifiant not in identifiants:
                    element.clear(); racine.clear()
                    continue

                releves = {}
                for prix in element.findall("prix"):
                    nom = prix.get("nom")
                    if nom not in NOMS_XML:
                        continue
                    horodatage = prix.get("maj") or ""
                    valeur = _normaliser_prix(prix.get("valeur"))
                    if valeur is None or len(horodatage) < 10:
                        continue
                    try:
                        jour = dt.date.fromisoformat(horodatage[:10])
                    except ValueError:
                        continue
                    indice = (jour - debut_annee).days
                    if 0 <= indice < nb_jours:
                        releves.setdefault(nom, {})[indice] = valeur

                for nom, par_jour in releves.items():
                    serie = np.full(nb_jours, np.nan)
                    serie[list(par_jour.keys())] = list(par_jour.values())
                    serie = _propager(serie)
                    for indice in range(nb_jours_utiles):
                        valeur = serie[indice]
                        if np.isnan(valeur):
                            continue
                        lignes.append((
                            (debut_annee + dt.timedelta(days=indice)).isoformat(),
                            identifiant, nom, round(float(valeur), 3),
                        ))

                element.clear(); racine.clear()

    journal(f"    {annee} : {len(lignes)} relevés pour {len(identifiants)} stations")
    return lignes


def agreger_annee(annee, journal=print):
    """Calcule les moyennes nationales quotidiennes d'une année.

    Renvoie une liste de tuples prête à insérer en base :
    (date, carburant, prix_moyen, prix_mini, prix_maxi, nb_stations).
    """
    debut_annee = dt.date(annee, 1, 1)
    fin_annee = dt.date(annee, 12, 31)
    aujourdhui = dt.date.today()
    # Pour l'année en cours, on s'arrête à aujourd'hui : propager au-delà
    # inventerait des prix futurs.
    derniere_date = min(fin_annee, aujourdhui)
    nb_jours = (fin_annee - debut_annee).days + 1
    nb_jours_utiles = (derniere_date - debut_annee).days + 1

    # Accumulateurs : une case par jour et par carburant.
    somme = {c: np.zeros(nb_jours) for c in NOMS_XML}
    compte = {c: np.zeros(nb_jours, dtype=np.int32) for c in NOMS_XML}
    mini = {c: np.full(nb_jours, np.nan) for c in NOMS_XML}
    maxi = {c: np.full(nb_jours, np.nan) for c in NOMS_XML}

    archive = chemin_archive(annee)
    nb_stations = 0
    nb_prix_ignores = 0

    with zipfile.ZipFile(archive) as zip_ouvert:
        nom_xml = zip_ouvert.namelist()[0]
        # On lit le XML directement depuis le ZIP, sans jamais écrire les
        # ~290 Mo décompressés sur le disque.
        with zip_ouvert.open(nom_xml) as flux:
            contexte = ET.iterparse(flux, events=("start", "end"))
            _, racine = next(contexte)

            for evenement, element in contexte:
                if evenement != "end" or element.tag != "pdv":
                    continue

                # Regroupe les relevés de cette station par carburant et par jour.
                releves = {}
                for prix in element.findall("prix"):
                    nom = prix.get("nom")
                    if nom not in NOMS_XML:
                        continue
                    horodatage = prix.get("maj") or ""
                    valeur = _normaliser_prix(prix.get("valeur"))
                    if valeur is None or len(horodatage) < 10:
                        nb_prix_ignores += 1
                        continue
                    try:
                        jour = dt.date.fromisoformat(horodatage[:10])
                    except ValueError:
                        nb_prix_ignores += 1
                        continue
                    indice = (jour - debut_annee).days
                    if not 0 <= indice < nb_jours:
                        continue
                    # Plusieurs relevés le même jour : on garde le dernier.
                    releves.setdefault(nom, {})[indice] = valeur

                for nom, par_jour in releves.items():
                    serie = np.full(nb_jours, np.nan)
                    serie[list(par_jour.keys())] = list(par_jour.values())
                    serie = _propager(serie)

                    connus = ~np.isnan(serie)
                    if not connus.any():
                        continue
                    somme[nom][connus] += serie[connus]
                    compte[nom][connus] += 1
                    # np.fmin/np.fmax ignorent les nan, ce qui évite de les propager.
                    np.fmin(mini[nom], serie, out=mini[nom])
                    np.fmax(maxi[nom], serie, out=maxi[nom])

                nb_stations += 1
                if nb_stations % 2000 == 0:
                    journal(f"    {annee} : {nb_stations} stations lues…")

                # Libère la mémoire au fur et à mesure, sinon l'arbre XML
                # entier finirait en RAM.
                element.clear()
                racine.clear()

    journal(
        f"    {annee} : {nb_stations} stations, {nb_prix_ignores} relevés écartés"
    )

    lignes = []
    for nom in NOMS_XML:
        # Couverture habituelle de ce carburant sur l'année : sert de référence
        # pour repérer les jours où l'on ne connaît qu'une poignée de stations.
        couverture_max = int(compte[nom][:nb_jours_utiles].max(initial=0))
        if couverture_max == 0:
            continue
        seuil = max(
            config.NB_STATIONS_MINIMUM,
            int(couverture_max * config.PART_MINIMALE_COUVERTURE),
        )
        for indice in range(nb_jours_utiles):
            n = int(compte[nom][indice])
            if n < seuil:
                continue
            date = (debut_annee + dt.timedelta(days=indice)).isoformat()
            lignes.append(
                (
                    date,
                    nom,
                    round(somme[nom][indice] / n, 4),
                    round(float(mini[nom][indice]), 3),
                    round(float(maxi[nom][indice]), 3),
                    n,
                )
            )
    return lignes
