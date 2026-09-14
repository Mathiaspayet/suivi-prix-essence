"""Alertes par courriel.

Trois situations méritent un message, et trois seulement. Une alerte qui se
répète tous les jours finit ignorée, ce qui la rend pire qu'inutile :

1. la prévision bascule vers la baisse — inutile de faire le plein tout de suite ;
2. la prévision bascule vers la hausse — mieux vaut ne pas attendre ;
3. une station suivie passe sous le seuil qu'on lui a fixé.

Le basculement compte, pas l'état. Tant que la situation ne change pas, aucun
message n'est renvoyé : c'est le rôle de la table « etat_alerte ».

Configuration par variables d'environnement (voir le fichier .env.exemple) :
SMTP_HOTE, SMTP_PORT, SMTP_UTILISATEUR, SMTP_MOTDEPASSE, ALERTE_DESTINATAIRE,
ALERTE_CARBURANT.
"""
import datetime as dt
import os
import smtplib
from email.message import EmailMessage

from carburants import base
from carburants.modele import entrainement


def _etat_precedent(cle):
    with base.connexion() as cx:
        ligne = cx.execute(
            "SELECT valeur FROM etat_alerte WHERE cle = ?", (cle,)
        ).fetchone()
    return ligne["valeur"] if ligne else None


def _memoriser(cle, valeur):
    with base.connexion() as cx:
        cx.execute(
            """INSERT INTO etat_alerte (cle, valeur, envoye_le) VALUES (?, ?, ?)
               ON CONFLICT(cle) DO UPDATE SET
                   valeur = excluded.valeur, envoye_le = excluded.envoye_le""",
            (cle, valeur, dt.date.today().isoformat()),
        )


def verifier(carburant=None):
    """Dresse la liste des alertes à envoyer aujourd'hui."""
    carburant = carburant or os.environ.get("ALERTE_CARBURANT", "Gazole")
    alertes = []

    # 1 & 2 — changement de recommandation à 7 jours.
    try:
        prevision = entrainement.prevoir(carburant, 7)
    except ValueError:
        prevision = None

    if prevision and prevision["conseil"] != "indecis":
        cle = f"conseil:{carburant}"
        if _etat_precedent(cle) != prevision["conseil"]:
            if prevision["conseil"] == "attendre":
                titre = f"{carburant} : la baisse s'annonce, vous pouvez attendre"
                corps = (
                    f"Le prix moyen du {carburant.lower()} est de "
                    f"{prevision['prix_actuel']:.3f} €/L.\n\n"
                    f"La probabilité de baisse sur les sept prochains jours est de "
                    f"{100 - prevision['probabilite_hausse']:.0f} %, pour un recul "
                    f"attendu d'environ {abs(prevision['variation_probable_cts']):.1f} "
                    f"centimes par litre.\n\n"
                    f"Si votre réservoir le permet, différer le plein de quelques "
                    f"jours a de bonnes chances d'être avantageux."
                )
            else:
                titre = f"{carburant} : hausse attendue, faites le plein"
                corps = (
                    f"Le prix moyen du {carburant.lower()} est de "
                    f"{prevision['prix_actuel']:.3f} €/L.\n\n"
                    f"La probabilité de hausse sur les sept prochains jours est de "
                    f"{prevision['probabilite_hausse']:.0f} %, pour une progression "
                    f"attendue d'environ {prevision['variation_probable_cts']:.1f} "
                    f"centimes par litre.\n\n"
                    f"C'est le moment de faire le plein plutôt que d'attendre."
                )
            corps += (
                f"\n\n—\nMéthode retenue : {prevision['methode']}, dont la justesse "
                f"mesurée est de {prevision['justesse_pct']:.0f} % sur des périodes "
                f"non apprises. Il s'agit d'une tendance, pas d'une certitude."
            )
            alertes.append({"cle": cle, "valeur": prevision["conseil"],
                            "titre": titre, "corps": corps})

    # 3 — une station suivie passe sous son seuil.
    with base.connexion() as cx:
        derniere_date = cx.execute("SELECT MAX(date) FROM prix_station").fetchone()[0]
        favoris = cx.execute(
            """SELECT f.station_id, f.seuil, s.adresse, s.ville, p.prix
               FROM favori f
               JOIN station s ON s.id = f.station_id
               JOIN prix_station p ON p.station_id = f.station_id
               WHERE f.seuil IS NOT NULL AND p.carburant = ? AND p.date = ?""",
            (carburant, derniere_date),
        ).fetchall()

    for favori in favoris:
        cle = f"seuil:{favori['station_id']}:{carburant}"
        sous_le_seuil = favori["prix"] <= favori["seuil"]
        etat = "sous" if sous_le_seuil else "au-dessus"
        # On ne prévient qu'au moment du franchissement, pas tant que le prix
        # reste bas — sans quoi l'alerte deviendrait un bulletin quotidien.
        if sous_le_seuil and _etat_precedent(cle) != "sous":
            alertes.append({
                "cle": cle, "valeur": etat,
                "titre": f"{favori['ville']} : {carburant} à {favori['prix']:.3f} €/L",
                "corps": (
                    f"La station {favori['adresse']} ({favori['ville']}) affiche le "
                    f"{carburant.lower()} à {favori['prix']:.3f} €/L, sous votre seuil "
                    f"de {favori['seuil']:.3f} €/L."
                ),
            })
        elif not sous_le_seuil:
            _memoriser(cle, etat)   # réarme l'alerte pour le prochain passage

    return alertes


def envoyer(alertes, journal=print):
    """Expédie les alertes par SMTP, si la messagerie est configurée."""
    if not alertes:
        journal("  alertes : rien à signaler")
        return 0

    hote = os.environ.get("SMTP_HOTE")
    destinataire = os.environ.get("ALERTE_DESTINATAIRE")
    if not hote or not destinataire:
        journal(f"  alertes : {len(alertes)} à envoyer, mais SMTP non configuré")
        for alerte in alertes:
            journal(f"    · {alerte['titre']}")
        return 0

    port = int(os.environ.get("SMTP_PORT", "587"))
    utilisateur = os.environ.get("SMTP_UTILISATEUR", "")
    motdepasse = os.environ.get("SMTP_MOTDEPASSE", "")

    envoyees = 0
    with smtplib.SMTP(hote, port, timeout=30) as serveur:
        if port == 587:
            serveur.starttls()
        if utilisateur:
            serveur.login(utilisateur, motdepasse)
        for alerte in alertes:
            message = EmailMessage()
            message["Subject"] = alerte["titre"]
            message["From"] = utilisateur or f"carburants@{hote}"
            message["To"] = destinataire
            message.set_content(alerte["corps"])
            serveur.send_message(message)
            _memoriser(alerte["cle"], alerte["valeur"])
            envoyees += 1

    journal(f"  alertes : {envoyees} message(s) envoyé(s) à {destinataire}")
    return envoyees
