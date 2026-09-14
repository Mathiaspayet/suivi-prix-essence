"""Prix relevés station par station, à partir du flux instantané officiel.

Ce flux donne le prix actuel d'environ 9 800 stations de France
métropolitaine. Il alimente la comparaison locale et le suivi des stations
favorites.

Attention : les départements d'outre-mer n'y figurent pas. Le prix des
carburants y est fixé chaque mois par arrêté préfectoral et s'impose à toutes
les stations, qui n'ont donc aucun prix à déclarer.
"""
import datetime as dt
import math

import httpx

from carburants import base, config

# Correspondance entre les colonnes du flux et nos noms de carburants.
CHAMPS_PRIX = {
    "Gazole": "gazole_prix",
    "SP95": "sp95_prix",
    "SP98": "sp98_prix",
    "E10": "e10_prix",
    "E85": "e85_prix",
    "GPLc": "gplc_prix",
}


def telecharger_flux():
    """Récupère l'intégralité du flux instantané en une seule requête.

    Le point d'entrée « exports » renvoie tout le jeu de données d'un coup,
    là où l'interrogation ordinaire est plafonnée à 100 enregistrements et
    demanderait une centaine d'allers-retours.
    """
    url = config.URL_FLUX_INSTANTANE.replace("/records", "/exports/json")
    reponse = httpx.get(url, timeout=180.0, follow_redirects=True)
    reponse.raise_for_status()
    return reponse.json()


def rafraichir(journal=print):
    """Met à jour le référentiel des stations et enregistre les prix du jour."""
    enregistrements = telecharger_flux()
    aujourdhui = dt.date.today().isoformat()

    stations, prix = [], []
    for e in enregistrements:
        identifiant = str(e.get("id") or "").strip()
        if not identifiant:
            continue
        geo = e.get("geom") or {}
        stations.append((
            identifiant,
            (e.get("adresse") or "").strip(),
            (e.get("ville") or "").strip(),
            (e.get("cp") or "").strip(),
            geo.get("lat"),
            geo.get("lon"),
            e.get("departement"),
            e.get("code_departement"),
            e.get("region"),
            aujourdhui,
        ))
        for carburant, champ in CHAMPS_PRIX.items():
            valeur = e.get(champ)
            if valeur is None:
                continue
            try:
                valeur = float(valeur)
            except (TypeError, ValueError):
                continue
            # Même garde-fou que pour l'historique : on écarte les saisies
            # manifestement erronées plutôt que de les afficher.
            if config.PRIX_MINI_PLAUSIBLE <= valeur <= config.PRIX_MAXI_PLAUSIBLE:
                prix.append((aujourdhui, identifiant, carburant, valeur))

    with base.connexion() as cx:
        cx.executemany(
            """INSERT INTO station (id, adresse, ville, code_postal, latitude,
                                    longitude, departement, code_departement,
                                    region, maj)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   adresse=excluded.adresse, ville=excluded.ville,
                   code_postal=excluded.code_postal, latitude=excluded.latitude,
                   longitude=excluded.longitude, departement=excluded.departement,
                   code_departement=excluded.code_departement,
                   region=excluded.region, maj=excluded.maj""",
            stations,
        )
        cx.executemany(
            """INSERT INTO prix_station (date, station_id, carburant, prix)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date, station_id, carburant) DO UPDATE SET
                   prix = excluded.prix""",
            prix,
        )

    journal(f"  stations : {len(stations)} stations, {len(prix)} prix relevés")
    return len(stations), len(prix)


def _distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau entre deux points, en kilomètres (formule de haversine)."""
    rayon_terre = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * rayon_terre * math.asin(math.sqrt(a))


def chercher_commune(terme):
    """Trouve des communes par nom ou code postal, pour la barre de recherche."""
    terme = (terme or "").strip()
    if len(terme) < 2:
        return []
    with base.connexion() as cx:
        lignes = cx.execute(
            """SELECT ville, code_postal, AVG(latitude) AS lat, AVG(longitude) AS lon,
                      COUNT(*) AS nb_stations
               FROM station
               WHERE (ville LIKE ? OR code_postal LIKE ?)
                 AND latitude IS NOT NULL
               GROUP BY ville, code_postal
               ORDER BY nb_stations DESC
               LIMIT 12""",
            (f"{terme}%", f"{terme}%"),
        ).fetchall()
    return [dict(l) for l in lignes]


def stations_autour(latitude, longitude, carburant, rayon_km=15, limite=40):
    """Stations proposant ce carburant dans un rayon donné, les moins chères d'abord.

    Le tri par prix est le cœur de la fonction : l'écart entre la station la
    moins chère et la plus chère d'une même agglomération dépasse souvent
    quinze centimes par litre, soit plusieurs euros par plein.
    """
    # Pré-filtre rectangulaire avant le calcul exact : à cette latitude, un
    # degré vaut environ 111 km. Cela évite de calculer 9 800 distances.
    marge_lat = rayon_km / 111.0
    marge_lon = rayon_km / (111.0 * max(math.cos(math.radians(latitude)), 0.01))

    with base.connexion() as cx:
        derniere_date = cx.execute(
            "SELECT MAX(date) FROM prix_station"
        ).fetchone()[0]
        if not derniere_date:
            return []
        lignes = cx.execute(
            """SELECT s.id, s.adresse, s.ville, s.code_postal, s.latitude,
                      s.longitude, p.prix, p.date,
                      EXISTS(SELECT 1 FROM favori f WHERE f.station_id = s.id) AS favori
               FROM station s
               JOIN prix_station p ON p.station_id = s.id
               WHERE p.carburant = ? AND p.date = ?
                 AND s.latitude BETWEEN ? AND ?
                 AND s.longitude BETWEEN ? AND ?""",
            (carburant, derniere_date,
             latitude - marge_lat, latitude + marge_lat,
             longitude - marge_lon, longitude + marge_lon),
        ).fetchall()

    resultats = []
    for l in lignes:
        distance = _distance_km(latitude, longitude, l["latitude"], l["longitude"])
        if distance > rayon_km:
            continue
        ligne = dict(l)
        ligne["distance_km"] = round(distance, 1)
        resultats.append(ligne)

    resultats.sort(key=lambda r: r["prix"])
    resultats = resultats[:limite]

    # Tous les carburants de chaque station retenue, pour la fiche qui s'ouvre
    # au clic sur la carte. Une seule requête plutôt qu'une par station.
    if resultats:
        identifiants = [r["id"] for r in resultats]
        trous = ",".join("?" * len(identifiants))
        with base.connexion() as cx:
            autres = cx.execute(
                f"""SELECT station_id, carburant, prix FROM prix_station
                    WHERE date = ? AND station_id IN ({trous})""",
                [derniere_date] + identifiants,
            ).fetchall()
        par_station = {}
        for a in autres:
            par_station.setdefault(a["station_id"], {})[a["carburant"]] = a["prix"]
        for r in resultats:
            r["tous_carburants"] = par_station.get(r["id"], {})

    return resultats


def historique_station(station_id, carburant, jours=180):
    """Évolution du prix d'une station donnée, pour le suivi des favorites."""
    with base.connexion() as cx:
        lignes = cx.execute(
            """SELECT date, prix FROM prix_station
               WHERE station_id = ? AND carburant = ?
               ORDER BY date DESC LIMIT ?""",
            (station_id, carburant, jours),
        ).fetchall()
    return [dict(l) for l in reversed(lignes)]
