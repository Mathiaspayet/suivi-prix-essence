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

**Ce qui a été retenu.** Une régression logistique, c'est-à-dire le modèle le
plus simple possible. Les arbres de gradient, plus sophistiqués, se sont révélés
systématiquement moins bons : avec 2 800 jours d'historique, ils apprennent le
bruit par cœur. Le modèle retenu égale la règle « la tendance se poursuit » à
7 jours et la dépasse de 2 à 4 points à 30 jours, là où cette règle s'essouffle.

Tous les chiffres annoncés sont mesurés en validation glissante, sur des jours
que le modèle n'avait jamais vus.
"""
import datetime as dt
import pickle

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from carburants import config
from carburants.modele import caracteristiques

# Variations inférieures à un demi-centime : le sens n'a pas de sens, et
# l'utilisateur s'en moque. On les écarte du calcul de justesse.
SEUIL_MOUVEMENT = 0.005

DOSSIER_MODELES = config.DOSSIER_DONNEES / "modeles"


def fabriquer():
    """Le modèle retenu.

    La normalisation préalable est indispensable : sans elle, une variable
    exprimée en dollars pèserait mécaniquement plus lourd qu'une variable
    exprimée en centimes. Le paramètre C=0.1 impose une régularisation ferme,
    qui empêche le modèle de s'attacher à des coïncidences de l'historique.
    """
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.1, max_iter=2000),
    )


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
    justesse = {"modele": [], "momentum": [], "toujours_hausse": []}
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

        modele = fabriquer()
        modele.fit(X_ent, (y_ent > 0).astype(int))
        prediction = modele.predict(X_test)[bouge.values]

        justesse["modele"].append(float((prediction == verite).mean()))
        justesse["momentum"].append(
            float(((X_test["var_pompe_7j"][bouge] > 0).astype(int) == verite).mean())
        )
        justesse["toujours_hausse"].append(float((verite == 1).mean()))
        periodes.append((X_test.index[0].date(), X_test.index[-1].date()))

    if not justesse["modele"]:
        raise ValueError("Historique trop court pour valider.")

    # Amplitude typique d'une variation sur cet horizon : sert à annoncer un
    # ordre de grandeur, et non un chiffre faussement précis.
    amplitudes = np.abs(y[np.abs(y) > SEUIL_MOUVEMENT])
    return {
        "carburant": carburant,
        "horizon": horizon,
        "nb_jours": int(len(X)),
        "justesse": float(np.mean(justesse["modele"])) * 100,
        "justesse_momentum": float(np.mean(justesse["momentum"])) * 100,
        "justesse_toujours_hausse": float(np.mean(justesse["toujours_hausse"])) * 100,
        "amplitude_mediane_cts": float(np.median(amplitudes)) * 100,
        "amplitude_haute_cts": float(np.quantile(amplitudes, 0.75)) * 100,
        "nb_plis": len(periodes),
        "periode_test": f"{periodes[0][0]} → {periodes[-1][1]}",
    }


def choisir_methode(mesures):
    """Retient, pour ce carburant et cet horizon, la méthode qui a gagné.

    Le modèle n'est pas conservé d'office. Sur l'E85 et le GPLc il se fait
    battre de dix à vingt-cinq points par la simple règle de tendance, et la
    raison en est claire : ces carburants ne suivent pas le pétrole. L'E85 est
    de l'éthanol, dont le prix dépend de la betterave et de la canne ; le GPLc
    est du propane, négocié sur un autre marché. Les variables bâties autour du
    baril de Brent n'y apportent aucune information, et le modèle s'en trouve
    égaré plutôt qu'aidé.

    Livrer un modèle sophistiqué là où une règle de trois fait mieux serait un
    mauvais service rendu. On garde donc la meilleure des deux, et on dit
    laquelle.
    """
    if mesures["justesse"] >= mesures["justesse_momentum"]:
        return "modele"
    return "momentum"


def entrainer(carburant, horizon, journal=print):
    """Valide, retient la meilleure méthode, puis enregistre le nécessaire.

    L'ordre compte : on juge d'abord sur des données inconnues, et on ne
    réentraîne sur la totalité qu'ensuite. L'inverse — mesurer la performance
    après avoir tout appris — ne mesurerait que la mémoire du modèle.
    """
    mesures = valider(carburant, horizon)
    mesures["methode"] = choisir_methode(mesures)
    mesures["justesse_retenue"] = (
        mesures["justesse"] if mesures["methode"] == "modele"
        else mesures["justesse_momentum"]
    )

    tableau = caracteristiques.construire(carburant, horizon)
    X, y, _ = caracteristiques.separer(tableau)
    modele = fabriquer()
    modele.fit(X, (y > 0).astype(int))

    DOSSIER_MODELES.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_MODELES / f"{carburant}_{horizon}j.pkl"
    with open(chemin, "wb") as fichier:
        pickle.dump(
            {
                "modele": modele,
                "colonnes": caracteristiques.COLONNES_CARACTERISTIQUES,
                "mesures": mesures,
                "methode": mesures["methode"],
                "entraine_le": dt.date.today().isoformat(),
            },
            fichier,
        )
    journal(
        f"  {carburant:7} {horizon:2}j : {mesures['methode']:8} retenu → "
        f"{mesures['justesse_retenue']:.1f}% de bon sens "
        f"(modèle {mesures['justesse']:.1f} / tendance "
        f"{mesures['justesse_momentum']:.1f} / biais "
        f"{mesures['justesse_toujours_hausse']:.1f})"
    )
    return mesures


def charger(carburant, horizon):
    """Recharge un modèle entraîné, ou None s'il n'existe pas encore."""
    chemin = DOSSIER_MODELES / f"{carburant}_{horizon}j.pkl"
    if not chemin.exists():
        return None
    with open(chemin, "rb") as fichier:
        return pickle.load(fichier)


def entrainer_tout(carburants=None, journal=print):
    """Entraîne un modèle par carburant et par horizon."""
    carburants = carburants or config.CARBURANTS
    resultats = []
    for carburant in carburants:
        for horizon in config.HORIZONS_JOURS:
            try:
                resultats.append(entrainer(carburant, horizon, journal))
            except ValueError as erreur:
                journal(f"  {carburant:7} {horizon:2}j : ignoré ({erreur})")
    return resultats


# --- Production d'une prévision -------------------------------------------

# Au-delà de ce niveau de confiance, on ose une recommandation ; en deçà, on
# assume de n'avoir rien d'utile à dire. Un outil qui tranche toujours finirait
# par conseiller à pile ou face.
SEUIL_RECOMMANDATION = 0.62


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
    tableau = caracteristiques.construire(carburant, horizon)
    X, _, dates = caracteristiques.separer(tableau, pour_entrainement=False)
    if X.empty:
        raise ValueError(f"Pas assez de données récentes pour {carburant}.")

    dernier_jour = X.iloc[[-1]]
    date_calcul = dates[-1].date()

    if paquet["methode"] == "modele":
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

    if probabilite_hausse >= SEUIL_RECOMMANDATION:
        conseil, resume = "faire_le_plein", "Faites le plein maintenant"
    elif probabilite_hausse <= 1 - SEUIL_RECOMMANDATION:
        conseil, resume = "attendre", "Vous pouvez attendre"
    else:
        conseil, resume = "indecis", "Aucune tendance nette"

    return {
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
        "justesse_pct": round(mesures["justesse_retenue"], 1),
        "entraine_le": paquet["entraine_le"],
    }
