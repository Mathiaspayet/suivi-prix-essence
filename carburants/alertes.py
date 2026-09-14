"""Alertes par courriel.

Cinq situations méritent un message, et cinq seulement. Une alerte qui se
répète tous les jours finit ignorée, ce qui la rend pire qu'inutile :

1. la prévision bascule vers la baisse — inutile de faire le plein tout de suite ;
2. la prévision bascule vers la hausse — mieux vaut ne pas attendre ;
3. le prix chute brutalement — une occasion qui ne durera pas ;
4. une prévision est démentie par les faits — le marché a fait l'inverse ;
5. une station suivie passe sous le seuil qu'on lui a fixé.

Deux principes gouvernent le module.

**Le basculement compte, pas l'état.** Tant que la situation ne change pas,
aucun message n'est renvoyé : c'est le rôle de la table « etat_alerte ».

**Un jour, un courriel.** Tout ce qui se déclenche le même jour part dans un
seul message à plusieurs rubriques. Trois courriels d'affilée, c'est trois
courriels ignorés.

Configuration par variables d'environnement (voir le fichier .env.exemple) :
SMTP_HOTE, SMTP_PORT, SMTP_UTILISATEUR, SMTP_MOTDEPASSE, ALERTE_DESTINATAIRE,
ALERTE_CARBURANT.
"""
import datetime as dt
import os
import smtplib
from email.message import EmailMessage

from carburants import base, config, reglages
from carburants.modele import entrainement


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


def _date(texte_iso):
    """Écrit une date en français plutôt qu'en notation informatique."""
    try:
        jour = dt.date.fromisoformat(texte_iso)
    except (TypeError, ValueError):
        return texte_iso
    return f"{jour.day} {MOIS[jour.month - 1]}"


def _nombre(valeur, decimales=3):
    """Écrit un nombre à la française : virgule décimale, pas de point.

    Les messageries n'appliquent aucune mise en forme : si le courriel doit
    être lisible, c'est au texte de l'être.
    """
    return f"{valeur:.{decimales}f}".replace(".", ",")


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


def _mouvement_brutal(carburant):
    """Repère une chute de prix nettement plus forte que d'ordinaire.

    Le seuil n'est pas fixé en centimes mais rapporté à l'agitation habituelle
    du carburant : une variation de trois centimes est banale sur le gazole et
    considérable sur l'E85. On le calcule sur l'année écoulée, si bien qu'il
    s'ajuste seul quand le marché devient plus nerveux.
    """
    import numpy as np
    import pandas as pd

    with base.connexion() as cx:
        serie = pd.read_sql_query(
            """SELECT date, prix_moyen FROM prix_national
               WHERE carburant = ? ORDER BY date""",
            cx, params=(carburant,), parse_dates=["date"],
        ).set_index("date")["prix_moyen"]

    if len(serie) < 400:
        return None
    variations = serie.diff(3)
    ordinaire = float(variations.tail(365).abs().median())
    if not ordinaire or np.isnan(ordinaire):
        return None
    seuil = ordinaire * reglages.lire_decimal(
        "facteur_mouvement_brutal", config.FACTEUR_MOUVEMENT_BRUTAL)
    derniere = float(variations.iloc[-1])

    # Seules les baisses sont signalées ici : une hausse brutale l'est déjà par
    # le basculement de recommandation, qui invite à faire le plein.
    if derniere >= -seuil:
        return None

    cle = f"chute:{carburant}"
    marque = f"{serie.index[-1].date()}"
    if _etat_precedent(cle) == marque:
        return None

    return {
        "cle": cle, "valeur": marque,
        "titre": f"{carburant} : chute de {_nombre(abs(derniere)*100, 1)} centimes en trois jours",
        "corps": (
            f"Le prix moyen du {carburant.lower()} est passé de "
            f"{_nombre(float(serie.iloc[-4]))} à {_nombre(float(serie.iloc[-1]))} €/L en trois "
            f"jours, soit {_nombre(abs(derniere)*100, 1)} centimes.\n\n"
            f"C'est environ {abs(derniere)/ordinaire:.0f} fois le mouvement habituel "
            f"sur trois jours ({_nombre(ordinaire*100, 1)} centime). Une baisse de cette "
            f"ampleur se reprend souvent en partie : si votre réservoir le permet, "
            f"c'est le moment d'en profiter."
        ),
    }


def _prevision_dementie(carburant):
    """Signale qu'une prévision vient d'être contredite par les faits.

    Utile à deux titres : parce qu'un mouvement inverse à celui annoncé est en
    soi une information, et parce qu'un outil qui reconnaît ses erreurs mérite
    davantage de confiance qu'un outil qui n'en parle jamais.
    """
    with base.connexion() as cx:
        ligne = cx.execute(
            """SELECT date_calcul, date_cible, sens, prix_actuel, prix_reel
               FROM prevision
               WHERE carburant = ? AND horizon_jours = 7
                 AND prix_reel IS NOT NULL AND sens_correct = 0
               ORDER BY date_cible DESC LIMIT 1""",
            (carburant,),
        ).fetchone()

    if ligne is None:
        return None
    variation = ligne["prix_reel"] - ligne["prix_actuel"]
    if abs(variation) < reglages.lire_decimal(
            "ecart_prevision_dementie", config.ECART_PREVISION_DEMENTIE):
        return None

    cle = f"dementie:{carburant}"
    # Les prévisions de jours voisins couvrent des fenêtres qui se recouvrent :
    # un marché parti à contresens les dément toutes, l'une après l'autre. On
    # n'en signale qu'une, puis l'on se tait le temps que l'épisode se termine.
    precedent = _etat_precedent(cle)
    if precedent:
        try:
            ecoules = (dt.date.fromisoformat(ligne["date_cible"])
                       - dt.date.fromisoformat(precedent)).days
        except ValueError:
            ecoules = config.JOURS_SILENCE_APRES_DEMENTI
        if ecoules < config.JOURS_SILENCE_APRES_DEMENTI:
            return None

    annonce = "une hausse" if ligne["sens"] == "hausse" else "une baisse"
    survenu = "monté" if variation > 0 else "descendu"
    return {
        "cle": cle, "valeur": ligne["date_cible"],
        "titre": f"{carburant} : la prévision du {_date(ligne['date_calcul'])} était fausse",
        "corps": (
            f"Le {_date(ligne['date_calcul'])}, l'outil annonçait {annonce} pour le "
            f"{_date(ligne['date_cible'])}. Le prix est en réalité {survenu} de "
            f"{_nombre(ligne['prix_actuel'])} à {_nombre(ligne['prix_reel'])} €/L, soit "
            f"{_nombre(abs(variation)*100, 1)} centimes dans l'autre sens.\n\n"
            f"Un mouvement contraire à la tendance signale souvent un fait nouveau "
            f"sur le marché. Le palmarès de la page tient le compte de ces erreurs."
        ),
    }


def verifier(carburant=None):
    """Dresse la liste des alertes à envoyer aujourd'hui."""
    carburant = carburant or reglages.lire("alerte_carburant")
    alertes = []

    # Chaque règle se coupe séparément depuis la page de configuration : mieux
    # vaut en désactiver une que se résigner à ignorer tous les courriels.
    detecteurs = []
    if reglages.lire_booleen("alerte_chute"):
        detecteurs.append(_mouvement_brutal)
    if reglages.lire_booleen("alerte_dementie"):
        detecteurs.append(_prevision_dementie)

    for detecteur in detecteurs:
        try:
            trouvaille = detecteur(carburant)
        except Exception:
            # Un détecteur en panne ne doit pas empêcher les autres de parler.
            trouvaille = None
        if trouvaille:
            alertes.append(trouvaille)

    # 1 & 2 — changement de recommandation à 7 jours.
    prevision = None
    if not reglages.lire_booleen("alerte_tendance"):
        prevision = None
    else:
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
                    f"{_nombre(prevision['prix_actuel'])} €/L.\n\n"
                    f"La probabilité de baisse sur les sept prochains jours est de "
                    f"{100 - prevision['probabilite_hausse']:.0f} %, pour un recul "
                    f"attendu d'environ {_nombre(abs(prevision['variation_probable_cts']), 1)} "
                    f"centimes par litre.\n\n"
                    f"Si votre réservoir le permet, différer le plein de quelques "
                    f"jours a de bonnes chances d'être avantageux."
                )
            else:
                titre = f"{carburant} : hausse attendue, faites le plein"
                corps = (
                    f"Le prix moyen du {carburant.lower()} est de "
                    f"{_nombre(prevision['prix_actuel'])} €/L.\n\n"
                    f"La probabilité de hausse sur les sept prochains jours est de "
                    f"{prevision['probabilite_hausse']:.0f} %, pour une progression "
                    f"attendue d'environ {_nombre(prevision['variation_probable_cts'], 1)} "
                    f"centime{'s' if abs(prevision['variation_probable_cts']) >= 2 else ''} par litre.\n\n"
                    f"C'est le moment de faire le plein plutôt que d'attendre."
                )
            # Pas de pied de page ici : « _composer » en ajoute un au message
            # entier, et deux séparateurs de suite feraient négligé.
            corps += (
                f"\n\nMéthode retenue : {prevision['methode']}, dont la justesse "
                f"mesurée est de {prevision['justesse_pct']:.0f} % sur des périodes "
                f"non apprises."
            )
            alertes.append({"cle": cle, "valeur": prevision["conseil"],
                            "titre": titre, "corps": corps})

    # 3 — une station suivie passe sous son seuil.
    if not reglages.lire_booleen("alerte_favoris"):
        return alertes

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
                    f"{carburant.lower()} à {_nombre(favori['prix'])} €/L, sous votre seuil "
                    f"de {_nombre(favori['seuil'])} €/L."
                ),
            })
        elif not sous_le_seuil:
            _memoriser(cle, etat)   # réarme l'alerte pour le prochain passage

    return alertes


def _composer(alertes):
    """Assemble les alertes du jour en un seul message, texte et HTML."""
    if len(alertes) == 1:
        sujet = alertes[0]["titre"]
    else:
        sujet = f"{len(alertes)} signalements sur les carburants"

    texte = []
    for alerte in alertes:
        texte.append(alerte["titre"].upper())
        texte.append("-" * len(alerte["titre"]))
        texte.append(alerte["corps"])
        texte.append("")
    texte.append("—")
    texte.append("Envoyé par votre suivi des prix des carburants.")
    texte.append("Ces signalements indiquent une tendance, jamais une certitude.")

    # Une version HTML sobre, lisible sur téléphone. Les styles sont écrits à
    # même les balises : les messageries suppriment les feuilles de style.
    blocs = "".join(
        f'<div style="margin:0 0 26px">'
        f'<h2 style="font:600 17px system-ui,sans-serif;margin:0 0 8px;color:#0b0b0b">'
        f'{a["titre"]}</h2>'
        f'<p style="font:15px/1.55 system-ui,sans-serif;margin:0;color:#52514e;'
        f'white-space:pre-line">{a["corps"]}</p></div>'
        for a in alertes
    )
    html = (
        f'<div style="max-width:560px;margin:0 auto;padding:24px 18px">{blocs}'
        f'<p style="font:12px/1.5 system-ui,sans-serif;color:#898781;'
        f'border-top:1px solid #e1e0d9;padding-top:14px;margin:0">'
        f'Envoyé par votre suivi des prix des carburants. Ces signalements '
        f'indiquent une tendance, jamais une certitude.</p></div>'
    )
    return sujet, "\n".join(texte), html


def envoyer(alertes, journal=print):
    """Expédie les alertes du jour en un unique courriel, si la messagerie
    est configurée.

    Regrouper est délibéré : trois messages d'affilée sont trois messages
    ignorés, tandis qu'un message à trois rubriques se lit en entier.
    """
    if not alertes:
        journal("  alertes : rien à signaler")
        return 0

    hote = reglages.lire("smtp_hote")
    destinataire = reglages.lire("alerte_destinataire")
    if not hote or not destinataire:
        journal(f"  alertes : {len(alertes)} à signaler, mais SMTP non configuré")
        for alerte in alertes:
            journal(f"    · {alerte['titre']}")
        return 0

    port = reglages.lire_entier("smtp_port", 587)
    utilisateur = reglages.lire("smtp_utilisateur")
    motdepasse = reglages.lire("smtp_motdepasse")
    sujet, texte, html = _composer(alertes)

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = utilisateur or f"carburants@{hote}"
    message["To"] = destinataire
    message.set_content(texte)
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(hote, port, timeout=30) as serveur:
        if port == 587:
            serveur.starttls()
        if utilisateur:
            serveur.login(utilisateur, motdepasse)
        serveur.send_message(message)

    # La mémoire n'est mise à jour qu'après un envoi réussi : si la messagerie
    # est en panne, l'alerte sera retentée demain plutôt que perdue.
    for alerte in alertes:
        _memoriser(alerte["cle"], alerte["valeur"])

    journal(f"  alertes : {len(alertes)} signalement(s) envoyé(s) à {destinataire}")
    return len(alertes)


def envoyer_essai():
    """Expédie un message de vérification, et rapporte l'échec en clair.

    Une configuration de messagerie échoue presque toujours en silence : mot
    de passe ordinaire refusé là où Google exige un mot de passe d'application,
    port fermé, hôte mal orthographié. Ce bouton transforme un mystère en
    message d'erreur lisible.
    """
    if not reglages.messagerie_configuree():
        return False, "Renseignez au moins le serveur SMTP et le destinataire."

    hote = reglages.lire("smtp_hote")
    port = reglages.lire_entier("smtp_port", 587)
    utilisateur = reglages.lire("smtp_utilisateur")
    motdepasse = reglages.lire("smtp_motdepasse")
    destinataire = reglages.lire("alerte_destinataire")

    message = EmailMessage()
    message["Subject"] = "Essai — suivi du prix des carburants"
    message["From"] = utilisateur or f"carburants@{hote}"
    message["To"] = destinataire
    message.set_content(
        "Ce message confirme que votre messagerie est correctement réglée.\n\n"
        "Les alertes vous parviendront de la même manière : un seul courriel "
        "par jour au plus, uniquement quand la situation change.\n\n"
        "—\nSuivi du prix des carburants"
    )

    try:
        with smtplib.SMTP(hote, port, timeout=20) as serveur:
            if port == 587:
                serveur.starttls()
            if utilisateur:
                serveur.login(utilisateur, motdepasse)
            serveur.send_message(message)
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Le serveur a refusé les identifiants. Avec Gmail, il faut un mot "
            "de passe d'application créé dans les réglages de sécurité du "
            "compte Google : le mot de passe habituel est toujours rejeté."
        )
    except smtplib.SMTPException as erreur:
        return False, f"Le serveur de messagerie a répondu : {erreur}"
    except OSError as erreur:
        return False, (
            f"Impossible de joindre {hote} sur le port {port} ({erreur}). "
            "Vérifiez le nom du serveur et le port."
        )
    return True, f"Message d'essai envoyé à {destinataire}."
