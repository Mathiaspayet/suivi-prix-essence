"""Tâche quotidienne : collecter, réentraîner, alerter.

Exécutée automatiquement par l'application (voir carburants/web/app.py), ou à la
main :

    python scripts/mettre_a_jour.py
"""
import datetime as dt
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carburants import alertes, base, config
from carburants.sources import historique, marche, stations


def mettre_a_jour(journal=print):
    """Enchaîne les étapes du jour, sans qu'un échec n'interrompe les suivantes.

    Si la FRED est indisponible un matin, ce n'est pas une raison pour renoncer
    à relever le prix des stations. Chaque étape est donc isolée.
    """
    journal(f"Mise à jour du {dt.date.today().isoformat()}")
    base.initialiser()
    incidents = []

    for intitule, action in [
        ("prix des stations", lambda: stations.rafraichir(journal)),
        ("données de marché", lambda: marche.rafraichir(depuis="2018-01-01", journal=journal)),
    ]:
        try:
            action()
        except Exception as erreur:
            incidents.append(intitule)
            journal(f"  {intitule} : échec ({erreur})")
            traceback.print_exc()

    # Les moyennes nationales viennent des archives annuelles. Au tout premier
    # démarrage il faut les reprendre toutes depuis 2019, faute de quoi le
    # modèle n'aurait pas de quoi apprendre ; ensuite, seule l'archive de
    # l'année en cours change et mérite d'être retéléchargée.
    try:
        annee_courante = dt.date.today().year
        deja = base.annees_deja_importees()
        annees_manquantes = [
            a for a in range(config.PREMIERE_ANNEE_DISPONIBLE, annee_courante)
            if a not in deja
        ]
        if annees_manquantes:
            journal(
                f"  historique : première collecte, {len(annees_manquantes)} "
                f"années à reprendre (comptez cinq à dix minutes)"
            )
        for annee in annees_manquantes:
            historique.telecharger_archive(annee)
            base.enregistrer_prix_national(
                historique.agreger_annee(annee, journal=lambda m: None)
            )
            journal(f"  historique : {annee} importée")

        historique.telecharger_archive(annee_courante, forcer=True)
        lignes = historique.agreger_annee(annee_courante, journal=lambda m: None)
        base.enregistrer_prix_national(lignes)
        journal(f"  moyennes nationales : {len(lignes)} lignes recalculées")
    except Exception as erreur:
        incidents.append("moyennes nationales")
        journal(f"  moyennes nationales : échec ({erreur})")

    # Le réentraînement quotidien garde le modèle au contact du marché récent.
    try:
        from carburants.modele import entrainement
        entrainement.entrainer_tout(journal=journal)
    except Exception as erreur:
        incidents.append("entraînement")
        journal(f"  entraînement : échec ({erreur})")

    try:
        alertes.envoyer(alertes.verifier(), journal)
    except Exception as erreur:
        incidents.append("alertes")
        journal(f"  alertes : échec ({erreur})")

    if incidents:
        journal(f"Terminé avec des incidents : {', '.join(incidents)}")
    else:
        journal("Terminé sans incident.")
    return incidents


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    mettre_a_jour()
