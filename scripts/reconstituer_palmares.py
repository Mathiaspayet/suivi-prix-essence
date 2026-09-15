"""Reconstitue le palmarès du modèle sur les mois écoulés.

Sans cela, le bilan resterait vide plusieurs semaines après l'installation :
une prévision à trente jours ne peut être jugée qu'un mois plus tard.

**La règle absolue est de ne jamais employer une donnée postérieure à la date
simulée.** Le modèle est donc réentraîné au début de chaque mois sur le seul
passé disponible à ce moment-là, puis rend ses prévisions pour les jours du
mois. C'est exactement ce qu'il aurait fait s'il avait tourné à l'époque — en
un peu moins bien même, puisqu'en service réel il se réajuste chaque jour et
non chaque mois.

    python scripts/reconstituer_palmares.py --mois 18
"""
import argparse
import datetime as dt
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import numpy as np

from carburants import base, config
from carburants.modele import caracteristiques, entrainement


def debuts_de_mois(depuis, jusqu_a):
    """Liste les premiers jours de mois entre deux dates."""
    jalons, courant = [], dt.date(depuis.year, depuis.month, 1)
    while courant < jusqu_a:
        jalons.append(courant)
        courant = dt.date(courant.year + courant.month // 12,
                          courant.month % 12 + 1, 1)
    return jalons


def reconstituer(carburant, horizon, nb_mois, journal=print):
    paquet = entrainement.charger(carburant, horizon)
    if paquet is None:
        journal(f"  {carburant} {horizon}j : aucun modèle, ignoré")
        return []
    methode = paquet["methode"]
    mesures = paquet["mesures"]

    tableau = caracteristiques.construire(carburant, horizon)
    X, y, dates = caracteristiques.separer(tableau)
    if len(X) < 500:
        return []

    fin = dates[-1].date()
    depart = fin - dt.timedelta(days=30 * nb_mois)
    amplitude = mesures["amplitude_mediane_cts"] / 100
    lignes = []

    for jalon in debuts_de_mois(depart, fin):
        borne = np.datetime64(jalon.isoformat())
        # Tout ce qui précède le jalon, et uniquement cela. La cible portant
        # sur « horizon » jours plus tard, on retire aussi cette marge :
        # sans quoi les derniers exemples d'entraînement renseigneraient déjà
        # sur les jours à prévoir.
        avant = dates < (borne - np.timedelta64(horizon, "D"))
        apres = (dates >= borne) & (dates < borne + np.timedelta64(31, "D"))
        if avant.sum() < 400 or apres.sum() == 0:
            continue

        if methode == "momentum":
            justesse = mesures["justesse_momentum"] / 100
            monte = X.loc[apres, "var_pompe_7j"].to_numpy() > 0
            probabilites = np.where(monte, justesse, 1 - justesse)
        else:
            modele = entrainement.fabriquer(methode)
            modele.fit(X[avant], (y[avant] > 0).astype(int))
            probabilites = modele.predict_proba(X[apres])[:, 1]

        # Le correcteur de confiance s'applique ici comme il s'appliquera en
        # service : sans cela le palmarès mesurerait une confiance que
        # l'utilisateur ne verra jamais.
        probabilites = entrainement._appliquer_calibrateur(
            paquet.get("calibrateur"), probabilites
        )

        prix = tableau["prix"]
        for date, probabilite in zip(dates[apres], probabilites):
            jour = date.date()
            prix_actuel = float(prix.loc[date])
            sens = 1 if probabilite >= 0.5 else -1
            lignes.append((
                jour.isoformat(), carburant, horizon,
                (jour + dt.timedelta(days=horizon)).isoformat(),
                round(prix_actuel, 3), round(prix_actuel + sens * amplitude, 3),
                round(float(probabilite) * 100, 1),
                "hausse" if sens > 0 else "baisse", methode, "reconstituee",
            ))
    return lignes


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--mois", type=int, default=18,
                           help="nombre de mois à reconstituer")
    options = analyseur.parse_args()

    base.initialiser()
    print(f"Reconstitution du palmarès sur {options.mois} mois")
    print("=" * 70)
    total = 0
    for carburant in config.CARBURANTS:
        for horizon in config.HORIZONS_JOURS:
            lignes = reconstituer(carburant, horizon, options.mois)
            if lignes:
                base.enregistrer_previsions(lignes)
                total += len(lignes)
            print(f"  {carburant:7} {horizon:2}j : {len(lignes):5} prévisions", flush=True)

    print("-" * 70)
    base.evaluer_previsions(print)
    bilan = base.palmares()
    print("=" * 70)
    print(f"  {total} prévisions reconstituées")
    print(f"  {bilan['nb_jugees']} jugées → {bilan['taux_reussite']} % de bon sens")


if __name__ == "__main__":
    main()
