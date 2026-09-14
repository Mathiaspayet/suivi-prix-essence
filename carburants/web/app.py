"""Application web : tableau de bord, comparateur de stations, prévisions.

FastAPI sert à la fois la page et les données qu'elle consomme. Le tout tient
dans un seul processus, sans base de données à administrer : c'est ce qui rend
l'installation sur un NAS triviale.
"""
import datetime as dt
import os
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from carburants import base, config
from carburants.modele import entrainement
from carburants.sources import stations

DOSSIER_WEB = config.RACINE / "carburants" / "web"

# Heure de la collecte quotidienne. Le fichier officiel est alimenté en continu
# par les stations ; en fin de matinée, les relevés de la nuit y figurent.
HEURE_COLLECTE = int(os.environ.get("HEURE_COLLECTE", "11"))

# --- Collecte automatique -------------------------------------------------

planificateur = BackgroundScheduler(timezone=os.environ.get("FUSEAU", "Europe/Paris"))


def _collecte_quotidienne():
    """Lancée chaque jour par le planificateur intégré.

    Intégrer la tâche à l'application évite d'avoir à configurer une tâche
    planifiée sur le NAS : un seul conteneur suffit, et il se suffit à lui-même.
    """
    from scripts.mettre_a_jour import mettre_a_jour
    mettre_a_jour()


@asynccontextmanager
async def cycle_de_vie(app):
    """Démarre le planificateur à l'ouverture, l'arrête à la fermeture.

    Ce que Python appelle un « gestionnaire de contexte » : ce qui précède le
    yield s'exécute au démarrage, ce qui le suit à l'extinction — y compris si
    l'application s'arrête sur une erreur.
    """
    base.initialiser()
    planificateur.add_job(
        _collecte_quotidienne, "cron", hour=HEURE_COLLECTE, minute=0,
        id="collecte", replace_existing=True, misfire_grace_time=3600,
    )
    planificateur.start()

    # Au tout premier démarrage la base est vide : on collecte immédiatement,
    # en arrière-plan, pour que la page ne s'ouvre pas sur un écran désert.
    with base.connexion() as cx:
        vide = cx.execute("SELECT COUNT(*) FROM prix_station").fetchone()[0] == 0
    if vide:
        threading.Thread(target=_collecte_quotidienne, daemon=True).start()

    yield

    if planificateur.running:
        planificateur.shutdown(wait=False)


application = FastAPI(
    title="Suivi du prix des carburants",
    docs_url="/api/docs",
    lifespan=cycle_de_vie,
)
application.mount(
    "/statiques", StaticFiles(directory=DOSSIER_WEB / "statiques"), name="statiques"
)
gabarits = Jinja2Templates(directory=str(DOSSIER_WEB / "templates"))


@application.get("/", response_class=HTMLResponse)
def tableau_de_bord(request: Request):
    """La page unique de l'application."""
    return gabarits.TemplateResponse(
        request, "index.html", {"carburants": config.CARBURANTS}
    )


@application.get("/api/previsions")
def api_previsions(carburant: str = Query("Gazole")):
    """Prévisions pour les trois horizons d'un carburant."""
    if carburant not in config.CARBURANTS:
        raise HTTPException(404, f"Carburant inconnu : {carburant}")
    previsions = []
    for horizon in config.HORIZONS_JOURS:
        try:
            previsions.append(entrainement.prevoir(carburant, horizon))
        except ValueError as erreur:
            previsions.append({"horizon": horizon, "erreur": str(erreur)})
    return {"carburant": carburant, "previsions": previsions}


@application.get("/api/historique")
def api_historique(carburant: str = Query("Gazole"), jours: int = Query(365)):
    """Séries à tracer, toutes exprimées en euros par litre.

    Trois courbes, une seule échelle — jamais deux axes verticaux : avec deux
    échelles indépendantes, on peut étirer n'importe quelle courbe jusqu'à ce
    qu'elle épouse l'autre, et le graphique ne prouve plus rien.

    - « pompe » : le prix réellement affiché ;
    - « matiere_premiere » : le pétrole contenu dans un litre ;
    - « pompe_theorique » : ce que coûterait le litre si les taxes et les
      marges restaient au niveau moyen des trois derniers mois.

    Cette troisième courbe est l'objet du graphique de répercussion. Elle suit
    le baril sans délai, là où le prix réel met quelques jours à s'ajuster :
    l'écart entre les deux, c'est exactement l'inertie.
    """
    if carburant not in config.CARBURANTS:
        raise HTTPException(404, f"Carburant inconnu : {carburant}")

    from carburants.modele import caracteristiques

    tableau = caracteristiques.charger_series(carburant)
    brut_avec_tva = tableau["brent_eur_l"] * config.TAUX_TVA
    # Moyenne glissante de l'écart : taxes et marges dérivent lentement, on
    # les laisse dériver. Ce qui reste est le décalage de court terme.
    ecart = (tableau["prix"] - brut_avec_tva).rolling(
        config.FENETRE_ECART_JOURS, min_periods=20
    ).mean()
    tableau["pompe_theorique"] = brut_avec_tva + ecart

    # On coupe après le calcul : la moyenne glissante a besoin des trois mois
    # qui précèdent la période affichée pour être définie dès le premier jour.
    tableau = tableau.iloc[-jours:] if jours < len(tableau) else tableau

    def arrondir(valeur, decimales=3):
        return None if valeur is None or valeur != valeur else round(float(valeur), decimales)

    points = [
        {
            "date": horodatage.date().isoformat(),
            "pompe": arrondir(ligne["prix"]),
            "matiere_premiere": arrondir(ligne["brent_eur_l"], 4),
            "pompe_theorique": arrondir(ligne["pompe_theorique"]),
            "nb_stations": int(ligne["nb_stations"]) if ligne["nb_stations"] == ligne["nb_stations"] else None,
        }
        for horodatage, ligne in tableau.iterrows()
    ]
    return {"carburant": carburant, "points": points}


@application.get("/api/communes")
def api_communes(q: str = Query(..., min_length=2)):
    """Recherche de commune par nom ou code postal."""
    return {"resultats": stations.chercher_commune(q)}


@application.get("/api/stations")
def api_stations(
    lat: float, lon: float,
    carburant: str = Query("Gazole"),
    rayon: int = Query(15, ge=1, le=100),
):
    """Stations proches, de la moins chère à la plus chère."""
    resultats = stations.stations_autour(lat, lon, carburant, rayon_km=rayon)
    if not resultats:
        return {"resultats": [], "statistiques": None}
    prix = [r["prix"] for r in resultats]
    return {
        "resultats": resultats,
        "statistiques": {
            "moins_cher": min(prix),
            "plus_cher": max(prix),
            "ecart_cts": round((max(prix) - min(prix)) * 100, 1),
            # Un plein de 50 litres : l'écart devient concret.
            "economie_plein_50l": round((max(prix) - min(prix)) * 50, 2),
            "nb": len(resultats),
        },
    }


@application.get("/api/favoris")
def api_favoris(carburant: str = Query("Gazole")):
    """Stations suivies, avec leur prix du jour et leur évolution récente."""
    with base.connexion() as cx:
        favoris = cx.execute(
            """SELECT f.station_id, f.surnom, s.adresse, s.ville, s.code_postal
               FROM favori f JOIN station s ON s.id = f.station_id
               ORDER BY f.ajoute_le""",
        ).fetchall()

    resultats = []
    for favori in favoris:
        historique = stations.historique_station(favori["station_id"], carburant)
        ligne = dict(favori)
        ligne["historique"] = historique
        ligne["prix_actuel"] = historique[-1]["prix"] if historique else None
        # Variation sur les sept derniers relevés disponibles.
        if len(historique) >= 2:
            reference = historique[max(0, len(historique) - 8)]["prix"]
            ligne["variation_cts"] = round((historique[-1]["prix"] - reference) * 100, 1)
        else:
            ligne["variation_cts"] = None
        resultats.append(ligne)
    return {"resultats": resultats}


@application.post("/api/favoris/{station_id}")
def api_ajouter_favori(station_id: str):
    """Ajoute une station au suivi."""
    with base.connexion() as cx:
        existe = cx.execute(
            "SELECT 1 FROM station WHERE id = ?", (station_id,)
        ).fetchone()
        if not existe:
            raise HTTPException(404, "Station inconnue")
        cx.execute(
            """INSERT INTO favori (station_id, surnom, ajoute_le) VALUES (?, NULL, ?)
               ON CONFLICT(station_id) DO NOTHING""",
            (station_id, dt.date.today().isoformat()),
        )
    return {"ok": True}


@application.delete("/api/favoris/{station_id}")
def api_retirer_favori(station_id: str):
    """Retire une station du suivi."""
    with base.connexion() as cx:
        cx.execute("DELETE FROM favori WHERE station_id = ?", (station_id,))
    return {"ok": True}


@application.get("/api/reglages")
def api_reglages():
    """Préférences d'ouverture : commune et rayon proposés d'emblée.

    La commune est résolue en coordonnées côté serveur, pour que la page
    affiche des stations dès son ouverture sans aucune saisie.
    """
    proposees = stations.chercher_commune(config.COMMUNE_PAR_DEFAUT)
    return {
        "commune": proposees[0] if proposees else None,
        "rayon_km": config.RAYON_PAR_DEFAUT_KM,
        "carburants": config.CARBURANTS,
    }


@application.get("/api/etat")
def api_etat():
    """État des données : sert à signaler une collecte en panne.

    Une application qui affiche sereinement des chiffres périmés est pire
    qu'une application en panne, parce que rien ne le signale.
    """
    with base.connexion() as cx:
        derniere_pompe = cx.execute("SELECT MAX(date) FROM prix_national").fetchone()[0]
        derniere_station = cx.execute("SELECT MAX(date) FROM prix_station").fetchone()[0]
        dernier_marche = cx.execute(
            "SELECT MAX(date) FROM marche WHERE indicateur = 'brent_usd'"
        ).fetchone()[0]
        nb_stations = cx.execute("SELECT COUNT(*) FROM station").fetchone()[0]

    aujourdhui = dt.date.today()
    def anciennete(date_texte):
        if not date_texte:
            return None
        return (aujourdhui - dt.date.fromisoformat(date_texte)).days

    return {
        "derniere_moyenne_nationale": derniere_pompe,
        "dernier_releve_stations": derniere_station,
        "derniere_cotation_brent": dernier_marche,
        "nb_stations": nb_stations,
        "retard_jours": anciennete(derniere_station),
        # La FRED publie avec quelques jours de décalage : ce n'est pas une panne.
        "retard_brent_jours": anciennete(dernier_marche),
    }
