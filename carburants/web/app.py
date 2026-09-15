"""Application web : tableau de bord, comparateur de stations, prévisions.

FastAPI sert à la fois la page et les données qu'elle consomme. Le tout tient
dans un seul processus, sans base de données à administrer : c'est ce qui rend
l'installation sur un NAS triviale.
"""
import datetime as dt
import os
import secrets
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from carburants import base, config, reglages
from carburants.modele import entrainement
from carburants.sources import enseignes, stations

DOSSIER_WEB = config.RACINE / "carburants" / "web"

# Heure de la collecte quotidienne. Le fichier officiel est alimenté en continu
# par les stations ; en fin de matinée, les relevés de la nuit y figurent.
HEURE_COLLECTE = int(os.environ.get("HEURE_COLLECTE", "11"))

# Mot de passe protégeant la page de configuration. Facultatif : sur un réseau
# domestique, l'application est souvent laissée ouverte. Il devient en revanche
# indispensable dès qu'elle est publiée au-delà du réseau local, puisque cette
# page règle des identifiants de messagerie.
MOT_DE_PASSE_ADMIN = os.environ.get("MOT_DE_PASSE_ADMIN", "")

# --- Collecte automatique -------------------------------------------------

planificateur = BackgroundScheduler(timezone=os.environ.get("FUSEAU", "Europe/Paris"))


# Renseigné pendant une collecte pour que la page puisse dire « patientez »
# plutôt que de laisser croire à une panne.
etat_collecte = {"en_cours": False, "motif": None, "depuis": None}


def _collecte_quotidienne():
    """Lancée chaque jour par le planificateur intégré.

    Intégrer la tâche à l'application évite d'avoir à configurer une tâche
    planifiée sur le NAS : un seul conteneur suffit, et il se suffit à lui-même.
    """
    from scripts.mettre_a_jour import mettre_a_jour

    etat_collecte["en_cours"] = True
    etat_collecte["depuis"] = dt.datetime.now().isoformat(timespec="seconds")
    try:
        mettre_a_jour()
    finally:
        etat_collecte["en_cours"] = False
        etat_collecte["motif"] = None


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

    # Tout ce qui manque en base est reconstitué sans attendre l'heure dite.
    # Le contrôle est délibérément générique : une mise à jour de l'image peut
    # apporter un besoin de données que la base, pourtant bien remplie, n'a
    # jamais satisfait. S'en tenir au critère « base vide » a laissé
    # l'application muette deux fois — une fois sur les modèles de prévision,
    # une fois sur les enseignes. Les contrôles sont rassemblés dans
    # carburants/diagnostic.py, où toute nouveauté ajoute le sien.
    from carburants import diagnostic

    trouvailles = diagnostic.manques()
    if trouvailles:
        etat_collecte["en_cours"] = True
        etat_collecte["motif"] = " ; ".join(trouvailles)
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


@application.get("/api/stations/historique")
def api_historique_stations(
    ids: str = Query(...), carburant: str = Query("Gazole"), jours: int = Query(365)
):
    """Courbes de prix de quelques stations désignées.

    L'historique n'existe que pour les stations du voisinage et celles qui
    sont suivies : le conserver pour les 9 800 stations représenterait quatre
    cents mégaoctets pour un usage qui n'existe pas. Les autres n'ont que les
    relevés accumulés depuis l'installation.
    """
    if carburant not in config.CARBURANTS:
        raise HTTPException(404, f"Carburant inconnu : {carburant}")

    identifiants = [i.strip() for i in ids.split(",") if i.strip()][:6]
    if not identifiants:
        return {"series": []}

    trous = ",".join("?" * len(identifiants))
    with base.connexion() as cx:
        lignes = cx.execute(
            f"""SELECT p.station_id, p.date, p.prix, s.enseigne, s.ville, s.adresse
                FROM prix_station p JOIN station s ON s.id = p.station_id
                WHERE p.carburant = ? AND p.station_id IN ({trous})
                  AND p.date >= date('now', ?)
                ORDER BY p.date""",
            [carburant] + identifiants + [f"-{jours} day"],
        ).fetchall()

    par_station = {}
    for ligne in lignes:
        entree = par_station.setdefault(ligne["station_id"], {
            "id": ligne["station_id"],
            "enseigne": ligne["enseigne"],
            "ville": ligne["ville"],
            "adresse": ligne["adresse"],
            "points": [],
        })
        entree["points"].append({"date": ligne["date"], "prix": round(ligne["prix"], 3)})

    # On respecte l'ordre demandé : c'est celui de la liste à l'écran.
    series = [par_station[i] for i in identifiants if i in par_station]
    return {"carburant": carburant, "series": series}


@application.get("/api/favoris")
def api_favoris(carburant: str = Query("Gazole")):
    """Stations suivies, avec leur prix du jour et leur évolution récente."""
    with base.connexion() as cx:
        favoris = cx.execute(
            """SELECT f.station_id, f.surnom, s.adresse, s.ville, s.code_postal,
                      s.enseigne
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
    proposees = stations.chercher_commune(reglages.lire("commune_par_defaut"))
    return {
        "commune": proposees[0] if proposees else None,
        "rayon_km": reglages.lire_entier("rayon_par_defaut_km", 30),
        "carburants": config.CARBURANTS,
    }


# --- Configuration ---------------------------------------------------------

def _verifier_acces(mot_de_passe):
    """Contrôle l'accès à la configuration, si un mot de passe a été défini.

    La comparaison passe par « compare_digest », qui met toujours le même temps
    à répondre quelle que soit la longueur du préfixe correct. Une comparaison
    ordinaire s'interrompt au premier caractère faux, et ce minuscule écart de
    durée suffit à retrouver un mot de passe caractère par caractère.
    """
    if not MOT_DE_PASSE_ADMIN:
        return
    if not mot_de_passe or not secrets.compare_digest(
        str(mot_de_passe), MOT_DE_PASSE_ADMIN
    ):
        raise HTTPException(401, "Mot de passe incorrect.")


@application.get("/api/configuration")
def api_configuration(x_mot_de_passe: str = Header(None)):
    """Réglages actuels. Le mot de passe de messagerie n'est jamais renvoyé."""
    _verifier_acces(x_mot_de_passe)
    valeurs = reglages.tous()
    valeurs["protegee"] = bool(MOT_DE_PASSE_ADMIN)
    valeurs["carburants"] = config.CARBURANTS
    valeurs["messagerie_configuree"] = reglages.messagerie_configuree()
    return valeurs


@application.post("/api/configuration")
def api_enregistrer_configuration(
    valeurs: dict = Body(...), x_mot_de_passe: str = Header(None)
):
    """Enregistre les réglages saisis dans la page.

    Un champ laissé vide est effacé plutôt qu'enregistré vide : la variable
    d'environnement du conteneur reprend alors la main, ce qui permet de
    revenir en arrière sans se souvenir de l'ancienne valeur.
    """
    _verifier_acces(x_mot_de_passe)
    valeurs.pop("protegee", None)
    # Un mot de passe non retouché arrive à None : on ne l'écrase pas.
    if valeurs.get("smtp_motdepasse") is None:
        valeurs.pop("smtp_motdepasse", None)
    modifies = reglages.ecrire(valeurs)
    return {"ok": True, "modifies": modifies,
            "messagerie_configuree": reglages.messagerie_configuree()}


@application.post("/api/configuration/essai")
def api_essai_messagerie(x_mot_de_passe: str = Header(None)):
    """Envoie un message de vérification et rapporte l'échec en clair."""
    _verifier_acces(x_mot_de_passe)
    from carburants import alertes

    reussi, message = alertes.envoyer_essai()
    return {"ok": reussi, "message": message}


@application.get("/api/enseignes")
def api_enseignes(carburant: str = Query("Gazole")):
    """Comparatif des enseignes : prix, marge et réactivité."""
    if carburant not in config.CARBURANTS:
        raise HTTPException(404, f"Carburant inconnu : {carburant}")
    tableau = enseignes.comparatif(carburant)
    return {
        "carburant": carburant,
        "enseignes": tableau,
        "ecart_total_cts": round(
            tableau[-1]["prix_median"] * 100 - tableau[0]["prix_median"] * 100, 1
        ) if len(tableau) > 1 else 0,
    }


@application.get("/api/enseignes/historique")
def api_enseignes_historique(
    carburant: str = Query("Gazole"), jours: int = Query(365)
):
    """Séries quotidiennes par enseigne."""
    if carburant not in config.CARBURANTS:
        raise HTTPException(404, f"Carburant inconnu : {carburant}")
    return {"carburant": carburant, "series": enseignes.historique(carburant, jours)}


@application.get("/api/palmares")
def api_palmares(carburant: str = Query(None)):
    """Bilan des prévisions rendues, confrontées à ce qui s'est produit.

    C'est le chiffre qui compte : non pas ce que le modèle promet, mais ce
    qu'il a effectivement obtenu sur des échéances déjà passées.
    """
    return base.palmares(carburant)


@application.post("/api/collecte")
def api_lancer_collecte(x_mot_de_passe: str = Header(None)):
    """Déclenche une collecte immédiate, à la demande.

    Utile pour ne pas attendre l'heure dite : après une mise à jour de
    l'image, ou simplement pour rafraîchir les prix avant de prendre la route.
    """
    _verifier_acces(x_mot_de_passe)
    if etat_collecte["en_cours"]:
        return {"ok": False, "message": "Une collecte est déjà en cours."}
    etat_collecte["en_cours"] = True
    etat_collecte["motif"] = "mise à jour demandée"
    threading.Thread(target=_collecte_quotidienne, daemon=True).start()
    return {"ok": True, "message": "Mise à jour lancée. Comptez une à deux minutes."}


@application.get("/api/etat")
def api_etat():
    """État et fraîcheur des données.

    Une application qui affiche sereinement des chiffres périmés est pire
    qu'une application en panne, parce que rien ne le signale.
    """
    from carburants import diagnostic

    etat = diagnostic.etat_donnees()
    etat["collecte_en_cours"] = etat_collecte["en_cours"]
    etat["motif_collecte"] = etat_collecte["motif"]
    etat["debut_collecte"] = etat_collecte["depuis"]
    etat["heure_collecte"] = HEURE_COLLECTE
    etat["modeles_manquants"] = len(
        __import__("carburants.modele.entrainement", fromlist=["x"]).modeles_manquants()
    )
    etat["modeles_attendus"] = len(config.CARBURANTS) * len(config.HORIZONS_JOURS)
    return etat
