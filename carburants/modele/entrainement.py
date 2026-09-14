"""Entraînement du modèle de prévision et mesure honnête de sa valeur.

Ce module est le résultat de plusieurs essais, dont les échecs ont été
instructifs et méritent d'être consignés ici.

**Premier essai : prévoir le prix exact.** Échec net. Un modèle demandant
« combien vaudra le gazole dans 15 jours ? » fait moins bien que la réponse
paresseuse « la même chose qu'aujourd'hui » — de 12 à 44 % moins bien selon les
cas. Les prix des carburants sont proches d'une marche aléatoire : leur niveau
futur n'est tout simplement pas prévisible, et aucun raffinement d'algorithme
n'y change quoi que ce soit.

**Second essai : prévoir le sens.** C'est là que se trouve le signal, parce que
c'est aussi la seule chose dont on ait besoin pour décider de faire le plein ou
d'attendre. Les stations répercutent leurs hausses par paliers sur plusieurs
jours : une tendance entamée a de bonnes chances de se poursuivre.

**Ce qui a été retenu.** Une forêt aléatoire fortement bridée. Trois familles
ont concouru, et l'ordre d'arrivée mérite une explication, car il est
contre-intuitif :

- les *arbres de gradient* sont les plus mauvais. Ils construisent leurs arbres
  les uns après les autres, chacun s'attachant à corriger les erreurs du
  précédent — ce qui revient, sur une série aussi bruitée, à apprendre le bruit
  par cœur ;
- la *régression logistique* fait honorablement, parce que sa simplicité même
  l'empêche de s'égarer ;
- la *forêt aléatoire* l'emporte nettement. Elle cultive cinq cents arbres
  indépendants, chacun sur un échantillon et des variables tirés au hasard,
  puis moyenne leurs avis. Les erreurs individuelles se compensent au lieu de
  s'accumuler.

La leçon n'est pas « les arbres sont mauvais » — une première version de ce
fichier l'affirmait, sur la foi du seul essai de gradient — mais que la manière
dont les arbres sont assemblés compte davantage que le fait d'en employer.

Tous les chiffres annoncés sont mesurés en validation glissante, sur des jours
que le modèle n'avait jamais vus.
"""
import datetime as dt
import pickle

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from carburants import config
from carburants.modele import caracteristiques

# Variations inférieures à un demi-centime : le sens n'a pas de sens, et
# l'utilisateur s'en moque. On les écarte du calcul de justesse.
SEUIL_MOUVEMENT = 0.005

DOSSIER_MODELES = config.DOSSIER_DONNEES / "modeles"


def fabriquer_candidats():
    """Les modèles mis en concurrence, reconstruits à neuf à chaque appel.

    Tous deux sont délibérément bridés. Avec 2 800 jours d'historique et un
    signal faible, la contrainte protège mieux qu'elle ne limite : un modèle
    libre de ses mouvements apprend le bruit des années passées et le
    restitue fidèlement sur des données qu'il n'a jamais vues, ce qui ne sert
    à rien.

    - « foret » : cinq cents arbres de profondeur 4 au plus, chacun exigeant
      soixante exemples par feuille. Aucun n'est bon isolément ; c'est leur
      moyenne qui l'est.
    - « logistique » : la normalisation évite qu'une variable en dollars pèse
      mécaniquement plus lourd qu'une variable en centimes, et C=0.1 impose
      une régularisation ferme.
    """
    return {
        "foret": RandomForestClassifier(
            n_estimators=500, max_depth=4, min_samples_leaf=60,
            random_state=0, n_jobs=-1,
        ),
        "logistique": make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.1, max_iter=2000),
        ),
    }


def fabriquer(nom="foret"):
    """Un candidat précis, par son nom."""
    return fabriquer_candidats()[nom]


def valider(carburant, horizon, nb_plis=6):
    """Mesure la justesse du modèle sur des jours qu'il n'a jamais vus.

    Renvoie aussi la justesse de deux stratégies triviales, sans lesquelles le
    chiffre du modèle ne voudrait rien dire :

    - « toujours hausse » : la tendance de fond du marché. Sur 2019-2026 les
      carburants ont beaucoup augmenté, si bien que cette réponse constante
      atteint déjà 53 à 61 % de réussite.
    - « la tendance se poursuit » : le sens des sept derniers jours prolongé.
      C'est l'adversaire sérieux, et il est redoutable à court terme.
    """
    tableau = caracteristiques.construire(carburant, horizon)
    X, y, _ = caracteristiques.separer(tableau)
    if len(X) < 400:
        raise ValueError(f"{carburant}/{horizon}j : {len(X)} jours, insuffisant.")

    n = len(X)
    taille_pli = n // (nb_plis + 1)
    noms = list(fabriquer_candidats())
    justesse = {nom: [] for nom in noms}
    justesse.update({"momentum": [], "toujours_hausse": []})
    periodes = []

    for pli in range(nb_plis):
        fin_entrainement = taille_pli * (pli + 1)
        # Quarantaine : la cible des derniers jours d'entraînement porte sur
        # des dates de la période de test. Sans ce décalage, le modèle
        # disposerait d'informations qu'il n'aura jamais en usage réel.
        debut_test = fin_entrainement + horizon
        fin_test = min(debut_test + taille_pli, n)
        if fin_test - debut_test < 20:
            continue

        X_ent, y_ent = X.iloc[:fin_entrainement], y.iloc[:fin_entrainement]
        X_test, y_test = X.iloc[debut_test:fin_test], y.iloc[debut_test:fin_test]

        bouge = np.abs(y_test) > SEUIL_MOUVEMENT
        if bouge.sum() < 10:
            continue
        verite = (y_test[bouge] > 0).astype(int)

        for nom, modele in fabriquer_candidats().items():
            modele.fit(X_ent, (y_ent > 0).astype(int))
            prediction = modele.predict(X_test)[bouge.values]
            justesse[nom].append(float((prediction == verite).mean()))

        justesse["momentum"].append(
            float(((X_test["var_pompe_7j"][bouge] > 0).astype(int) == verite).mean())
        )
        justesse["toujours_hausse"].append(float((verite == 1).mean()))
        periodes.append((X_test.index[0].date(), X_test.index[-1].date()))

    if not justesse[noms[0]]:
        raise ValueError("Historique trop court pour valider.")

    # Amplitude typique d'une variation sur cet horizon : sert à annoncer un
    # ordre de grandeur, et non un chiffre faussement précis.
    amplitudes = np.abs(y[np.abs(y) > SEUIL_MOUVEMENT])
    resume = {
        "carburant": carburant,
        "horizon": horizon,
        "nb_jours": int(len(X)),
        "justesse_momentum": float(np.mean(justesse["momentum"])) * 100,
        "justesse_toujours_hausse": float(np.mean(justesse["toujours_hausse"])) * 100,
        "amplitude_mediane_cts": float(np.median(amplitudes)) * 100,
        "amplitude_haute_cts": float(np.quantile(amplitudes, 0.75)) * 100,
        "nb_plis": len(periodes),
        "periode_test": f"{periodes[0][0]} → {periodes[-1][1]}",
    }
    # Une entrée par candidat : « justesse_foret », « justesse_logistique »…
    for nom in noms:
        resume[f"justesse_{nom}"] = float(np.mean(justesse[nom])) * 100
    return resume


def choisir_methode(mesures):
    """Retient, pour ce carburant et cet horizon, la méthode qui a gagné.

    Aucun modèle n'est conservé d'office. Sur l'E85 et le GPLc, tous se font
    battre de dix à vingt-cinq points par la simple règle de tendance, et la
    raison en est claire : ces carburants ne suivent pas le pétrole. L'E85 est
    de l'éthanol, dont le prix dépend de la betterave et de la canne ; le GPLc
    est du propane, négocié sur un autre marché. Les variables bâties autour du
    baril et des carburants de gros n'y apportent aucune information, et les
    modèles s'en trouvent égarés plutôt qu'aidés.

    Livrer un modèle sophistiqué là où une règle de trois fait mieux serait un
    mauvais service rendu. On garde donc le meilleur des trois, et on dit
    lequel.
    """
    concurrents = {nom: mesures[f"justesse_{nom}"] for nom in fabriquer_candidats()}
    concurrents["momentum"] = mesures["justesse_momentum"]
    return max(concurrents, key=concurrents.get)


def _validation_perimee(paquet):
    """Dit s'il est temps de refaire concourir les méthodes."""
    if paquet is None or "valide_le" not in paquet:
        return True
    age = (dt.date.today() - dt.date.fromisoformat(paquet["valide_le"])).days
    return age >= config.JOURS_ENTRE_VALIDATIONS


def entrainer(carburant, horizon, revalider=None, journal=print):
    """Réajuste le modèle aux données du jour, en revalidant si nécessaire.

    Deux opérations de coût très différent sont distinguées ici.

    La **validation** fait concourir les méthodes sur des périodes inconnues
    pour désigner la meilleure. Elle demande douze entraînements par carburant
    et par horizon, soit près de neuf dixièmes du temps total. Son verdict ne
    change pas d'un jour à l'autre.

    Le **réajustement** réentraîne la méthode déjà retenue sur l'historique
    complet, à jour du dernier relevé. Un seul entraînement, et c'est ce qui
    permet au modèle de rester au contact du marché.

    D'où la règle : réajustement à chaque collecte, validation une fois par
    mois. L'ordre est toujours respecté — on juge sur des données inconnues
    avant de réentraîner sur la totalité, faute de quoi on ne mesurerait que
    la mémoire du modèle.
    """
    precedent = charger(carburant, horizon)
    if revalider is None:
        revalider = _validation_perimee(precedent)

    if revalider:
        mesures = valider(carburant, horizon)
        methode = choisir_methode(mesures)
        valide_le = dt.date.today().isoformat()
    else:
        mesures = dict(precedent["mesures"])
        methode = precedent["methode"]
        valide_le = precedent["valide_le"]
    mesures["methode"] = methode
    mesures["justesse_retenue"] = (
        mesures["justesse_momentum"] if methode == "momentum"
        else mesures[f"justesse_{methode}"]
    )

    modele = None
    if methode != "momentum":
        tableau = caracteristiques.construire(carburant, horizon)
        X, y, _ = caracteristiques.separer(tableau)
        modele = fabriquer(methode)
        modele.fit(X, (y > 0).astype(int))
        # L'entraînement profite des cœurs disponibles, mais la prévision ne
        # porte que sur une seule ligne : répartir cinq cents arbres entre
        # plusieurs fils coûte alors quatre fois plus cher que de les parcourir
        # l'un après l'autre (143 ms contre 38). On fige donc le mode
        # séquentiel avant d'enregistrer.
        if hasattr(modele, "n_jobs"):
            modele.n_jobs = 1

    DOSSIER_MODELES.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_MODELES / f"{carburant}_{horizon}j.pkl"
    with open(chemin, "wb") as fichier:
        pickle.dump(
            {
                "modele": modele,
                "colonnes": caracteristiques.COLONNES_CARACTERISTIQUES,
                "mesures": mesures,
                "methode": methode,
                "entraine_le": dt.date.today().isoformat(),
                "valide_le": valide_le,
            },
            fichier,
        )

    if revalider:
        detail = " / ".join(
            f"{nom} {mesures[f'justesse_{nom}']:.1f}" for nom in fabriquer_candidats()
        )
        journal(
            f"  {carburant:7} {horizon:2}j : {methode:10} retenu → "
            f"{mesures['justesse_retenue']:.1f}% de bon sens "
            f"({detail} / tendance {mesures['justesse_momentum']:.1f} "
            f"/ biais {mesures['justesse_toujours_hausse']:.1f})"
        )
    else:
        journal(
            f"  {carburant:7} {horizon:2}j : {methode} réajusté "
            f"({mesures['justesse_retenue']:.1f}%, validé le {valide_le})"
        )
    return mesures


def charger(carburant, horizon):
    """Recharge un modèle entraîné, ou None s'il est absent ou périmé.

    Un modèle enregistré par une version antérieure du programme peut attendre
    d'autres variables que celles qu'on lui présente aujourd'hui — c'est arrivé
    lors de l'ajout des cotations de gros, qui a fait passer le jeu de seize à
    vingt colonnes. Lui soumettre les nouvelles le ferait échouer au moment de
    prédire, c'est-à-dire devant l'utilisateur.

    On compare donc la liste enregistrée avec celle attendue, et un modèle
    devenu incompatible est traité comme absent : il sera simplement réentraîné.
    """
    chemin = DOSSIER_MODELES / f"{carburant}_{horizon}j.pkl"
    if not chemin.exists():
        return None
    try:
        with open(chemin, "rb") as fichier:
            paquet = pickle.load(fichier)
    except Exception:
        # Fichier tronqué par un arrêt brutal, ou écrit par une version de
        # scikit-learn incompatible : on repart de zéro plutôt que d'échouer.
        return None

    if paquet.get("colonnes") != caracteristiques.COLONNES_CARACTERISTIQUES:
        return None
    return paquet


def modeles_manquants(carburants=None):
    """Liste les couples (carburant, horizon) sans modèle exploitable.

    Sert au démarrage : une mise à jour de l'image peut avoir rendu les modèles
    du volume incompatibles, et il faut alors les reconstruire sans attendre la
    collecte du lendemain.
    """
    manquants = []
    for carburant in (carburants or config.CARBURANTS):
        for horizon in config.HORIZONS_JOURS:
            if charger(carburant, horizon) is None:
                manquants.append((carburant, horizon))
    return manquants


def entrainer_tout(carburants=None, revalider=None, journal=print):
    """Traite chaque carburant et chaque horizon.

    « revalider » vaut None par défaut, ce qui laisse chaque modèle décider
    selon l'ancienneté de sa dernière validation. True force le concours
    complet, False s'en tient au réajustement.
    """
    carburants = carburants or config.CARBURANTS
    resultats = []
    for carburant in carburants:
        for horizon in config.HORIZONS_JOURS:
            try:
                resultats.append(entrainer(carburant, horizon, revalider, journal))
            except ValueError as erreur:
                journal(f"  {carburant:7} {horizon:2}j : ignoré ({erreur})")
    return resultats


# --- Production d'une prévision -------------------------------------------

# Au-delà de ce niveau de confiance, on ose une recommandation ; en deçà, on
# assume de n'avoir rien d'utile à dire. Un outil qui tranche toujours finirait
# par conseiller à pile ou face.
SEUIL_RECOMMANDATION = 0.62

# En dessous de cette justesse, l'outil se tait. Annoncer une tendance dont on
# sait qu'elle se vérifie six fois sur dix rendrait un service douteux : autant
# dire clairement qu'on ne sait pas.
FIABILITE_MINIMALE = 60.0

# Nombre de prévisions jugées à partir duquel on se fie au palmarès réel
# plutôt qu'aux chiffres de la validation. En dessous, l'échantillon est trop
# maigre pour conclure quoi que ce soit.
MINIMUM_POUR_PALMARES = 100


# Les prévisions ne changent qu'une fois par jour, à la collecte. Les
# recalculer à chaque affichage ferait relire toute la base et réinterroger
# cinq cents arbres pour un résultat identique — coûteux sur le petit
# processeur d'un NAS. La clé inclut la date des données : dès que la collecte
# apporte un jour de plus, le cache se périme de lui-même.
_cache_previsions = {}


def _date_des_donnees():
    """Jour le plus récent présent en base, qui sert de clé de fraîcheur.

    Une seule requête, sans lecture de l'historique : c'est ce qui permet de
    répondre depuis le cache sans avoir rien recalculé.
    """
    from carburants import base

    with base.connexion() as cx:
        return cx.execute("SELECT MAX(date) FROM prix_national").fetchone()[0]


def prevoir(carburant, horizon):
    """Produit la prévision du jour pour un carburant et un horizon.

    Renvoie une probabilité de hausse, une amplitude probable et une
    recommandation en clair — accompagnées de la justesse mesurée, pour que
    l'utilisateur sache quel crédit accorder à la réponse.
    """
    paquet = charger(carburant, horizon)
    if paquet is None:
        raise ValueError(f"Aucun modèle entraîné pour {carburant}/{horizon}j.")

    mesures = paquet["mesures"]

    # Contrôle du cache avant toute lecture : c'est tout l'intérêt.
    fraicheur = (_date_des_donnees(), paquet["entraine_le"])
    cle = (carburant, horizon, fraicheur)
    if cle in _cache_previsions:
        return _cache_previsions[cle]

    tableau = caracteristiques.construire(carburant, horizon)
    X, _, dates = caracteristiques.separer(tableau, pour_entrainement=False)
    if X.empty:
        raise ValueError(f"Pas assez de données récentes pour {carburant}.")

    dernier_jour = X.iloc[[-1]]
    date_calcul = dates[-1].date()

    if paquet["methode"] != "momentum" and paquet["modele"] is not None:
        probabilite_hausse = float(paquet["modele"].predict_proba(dernier_jour)[0, 1])
    else:
        # La règle de tendance ne rend qu'un verdict binaire. On le convertit en
        # probabilité à l'aide de sa justesse mesurée : si elle voit juste 74 %
        # du temps et annonce une hausse, la probabilité de hausse vaut 0,74.
        justesse = mesures["justesse_momentum"] / 100
        monte = float(dernier_jour["var_pompe_7j"].iloc[0]) > 0
        probabilite_hausse = justesse if monte else 1 - justesse

    prix_actuel = float(tableau["prix"].loc[dates[-1]])
    amplitude = mesures["amplitude_mediane_cts"] / 100
    sens = 1 if probabilite_hausse >= 0.5 else -1

    # La justesse annoncée à l'utilisateur est celle du palmarès dès qu'il est
    # assez fourni, et non la moyenne de la validation. Les deux diffèrent : la
    # seconde moyenne six périodes couvrant plusieurs années, dont d'anciennes
    # bien plus faciles à prévoir que la période en cours. Ce qui intéresse
    # celui qui consulte la page, c'est si l'outil voit juste en ce moment.
    from carburants import base

    bilan = base.palmares(carburant, horizon)
    if bilan["nb_jugees"] >= MINIMUM_POUR_PALMARES:
        justesse, source = bilan["taux_reussite"], "palmarès"
    else:
        justesse, source = mesures["justesse_retenue"], "validation"

    if justesse is not None and justesse < FIABILITE_MINIMALE:
        # Trop peu fiable pour se prononcer, quelle que soit la probabilité
        # calculée : mieux vaut l'avouer que de laisser croire à une prévision.
        conseil, resume = "peu_fiable", "Trop imprévisible à cette échéance"
    elif probabilite_hausse >= SEUIL_RECOMMANDATION:
        conseil, resume = "faire_le_plein", "Faites le plein maintenant"
    elif probabilite_hausse <= 1 - SEUIL_RECOMMANDATION:
        conseil, resume = "attendre", "Vous pouvez attendre"
    else:
        conseil, resume = "indecis", "Aucune tendance nette"

    prevision = {
        "carburant": carburant,
        "horizon": horizon,
        "date_calcul": date_calcul.isoformat(),
        "date_cible": (date_calcul + dt.timedelta(days=horizon)).isoformat(),
        "prix_actuel": round(prix_actuel, 3),
        "probabilite_hausse": round(probabilite_hausse * 100, 1),
        "sens": "hausse" if sens > 0 else "baisse",
        "variation_probable_cts": round(sens * amplitude * 100, 1),
        "prix_prevu": round(prix_actuel + sens * amplitude, 3),
        "conseil": conseil,
        "resume": resume,
        "methode": paquet["methode"],
        "justesse_pct": round(justesse, 1) if justesse is not None else None,
        "justesse_source": source,
        "justesse_validation_pct": round(mesures["justesse_retenue"], 1),
        "nb_previsions_jugees": bilan["nb_jugees"],
        "entraine_le": paquet["entraine_le"],
    }
    # On écarte les entrées devenues obsolètes — celles calculées sur des
    # données ou un modèle antérieurs — sans toucher aux autres carburants et
    # horizons du jour, qui restent parfaitement valables.
    for ancienne in [k for k in _cache_previsions if k[2] != fraicheur]:
        del _cache_previsions[ancienne]
    _cache_previsions[cle] = prevision
    return prevision
