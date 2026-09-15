"""Ce qui manque en base, et qu'une collecte reconstituerait.

Ce module existe à cause d'une erreur commise deux fois. À chaque mise à jour
apportant un nouveau besoin de données — les modèles d'abord, les enseignes
ensuite — l'application démarrait sans rien reconstruire et affichait des cases
vides jusqu'à la collecte du lendemain. La première fois, le correctif n'a visé
que les modèles ; la seconde, le même scénario s'est reproduit avec les
enseignes.

D'où ce point unique. **Toute fonctionnalité qui introduit un nouveau besoin de
données ajoute son contrôle ici**, et le démarrage la prend en charge sans
autre intervention.
"""
import datetime as dt

from carburants import base, config


def _compter(cx, requete, *parametres):
    return cx.execute(requete, parametres).fetchone()[0]


def manques():
    """Liste ce qui manque, en clair. Liste vide = tout est en place."""
    from carburants.modele import entrainement

    trouvailles = []
    with base.connexion() as cx:
        nb_stations = _compter(cx, "SELECT COUNT(*) FROM station")
        nb_prix = _compter(cx, "SELECT COUNT(*) FROM prix_station")
        nb_national = _compter(cx, "SELECT COUNT(*) FROM prix_national")
        nb_marche = _compter(cx, "SELECT COUNT(*) FROM marche")
        sans_enseigne = _compter(
            cx, "SELECT COUNT(*) FROM station WHERE enseigne IS NULL"
        )
        nb_enseignes = _compter(cx, "SELECT COUNT(*) FROM prix_enseigne")
        derniere = cx.execute("SELECT MAX(date) FROM prix_station").fetchone()[0]

    if nb_stations == 0:
        trouvailles.append("le référentiel des stations est vide")
    if nb_prix == 0:
        trouvailles.append("aucun prix de station n'a été relevé")
    if nb_national == 0:
        trouvailles.append("les moyennes nationales sont absentes")
    if nb_marche == 0:
        trouvailles.append("les cotations de marché sont absentes")

    # Une poignée de stations sans enseigne est normale : le référentiel en
    # couvre 98 %. Au-delà du quart, c'est qu'il n'a jamais été téléchargé.
    if nb_stations and sans_enseigne > nb_stations * 0.25:
        trouvailles.append("les enseignes ne sont pas renseignées")
    if nb_enseignes == 0:
        trouvailles.append("l'historique par enseigne est absent")

    manquants = entrainement.modeles_manquants()
    if manquants:
        trouvailles.append(f"{len(manquants)} modèles de prévision à reconstruire")

    # Données périmées : le conteneur a pu rester éteint plusieurs jours.
    if derniere:
        retard = (dt.date.today() - dt.date.fromisoformat(derniere)).days
        if retard > 2:
            trouvailles.append(f"les prix datent de {retard} jours")

    return trouvailles


def etat_donnees():
    """Résumé de fraîcheur, pour l'affichage et pour le bouton de mise à jour."""
    with base.connexion() as cx:
        ligne = cx.execute(
            """SELECT (SELECT MAX(date) FROM prix_station)   AS prix,
                      (SELECT MAX(date) FROM prix_national)  AS national,
                      (SELECT MAX(date) FROM marche WHERE indicateur='brent_usd')
                                                             AS brent,
                      (SELECT COUNT(*) FROM station)         AS nb_stations,
                      (SELECT COUNT(*) FROM station WHERE enseigne IS NOT NULL)
                                                             AS nb_enseignes,
                      (SELECT MAX(modifie_le) FROM reglage)  AS reglages"""
        ).fetchone()

    def anciennete(texte):
        if not texte:
            return None
        try:
            return (dt.date.today() - dt.date.fromisoformat(texte[:10])).days
        except ValueError:
            return None

    return {
        "derniere_collecte": ligne["prix"],
        "retard_jours": anciennete(ligne["prix"]),
        "derniere_moyenne_nationale": ligne["national"],
        "derniere_cotation_brent": ligne["brent"],
        "retard_brent_jours": anciennete(ligne["brent"]),
        "nb_stations": ligne["nb_stations"],
        "nb_enseignes": ligne["nb_enseignes"],
        "manques": manques(),
    }
