"""Réglages modifiables depuis la page, sans toucher au fichier Docker.

Trois sources sont consultées dans cet ordre, la première qui répond l'emporte :

1. ce qui a été saisi dans la page et enregistré en base ;
2. la variable d'environnement du conteneur, si elle existe ;
3. la valeur par défaut inscrite ici.

Cet ordre permet de démarrer avec une configuration figée dans le fichier
compose, puis de l'ajuster depuis la page sans redéployer — et sans jamais
perdre la configuration d'origine, qui reste le filet de secours si l'on
efface un réglage.

**Sur le mot de passe de la messagerie.** Il est conservé en clair dans le
fichier SQLite, sur le NAS. Ce n'est pas une négligence mais un constat : pour
s'authentifier auprès d'un serveur SMTP il faut disposer du mot de passe en
clair au moment de l'envoi. Le chiffrer avec une clé rangée à côté ne
protégerait de rien et donnerait le sentiment trompeur d'une sécurité. Il n'est
en revanche jamais renvoyé par l'interface : la page peut l'écrire, jamais le
relire.
"""
import datetime as dt
import os

from carburants import base

# Valeur par défaut de chaque réglage, et variable d'environnement associée.
DEFINITIONS = {
    # --- Messagerie ---
    "smtp_hote":           {"defaut": "",        "env": "SMTP_HOTE"},
    "smtp_port":           {"defaut": "587",     "env": "SMTP_PORT"},
    "smtp_utilisateur":    {"defaut": "",        "env": "SMTP_UTILISATEUR"},
    "smtp_motdepasse":     {"defaut": "",        "env": "SMTP_MOTDEPASSE", "secret": True},
    "alerte_destinataire": {"defaut": "",        "env": "ALERTE_DESTINATAIRE"},
    # --- Alertes ---
    "alerte_carburant":    {"defaut": "Gazole",  "env": "ALERTE_CARBURANT"},
    "alerte_tendance":     {"defaut": "1"},
    "alerte_chute":        {"defaut": "1"},
    "alerte_dementie":     {"defaut": "1"},
    "alerte_favoris":      {"defaut": "1"},
    "facteur_mouvement_brutal":  {"defaut": "4.0"},
    "ecart_prevision_dementie":  {"defaut": "0.03"},
    # --- Affichage ---
    "commune_par_defaut":  {"defaut": "Mimizan", "env": "COMMUNE_PAR_DEFAUT"},
    "rayon_par_defaut_km": {"defaut": "30",      "env": "RAYON_PAR_DEFAUT_KM"},
    # Rayon autour duquel l'historique par station est reconstitué. Au-delà,
    # seuls les relevés accumulés jour après jour existent.
    "rayon_historique_km": {"defaut": "60",      "env": "RAYON_HISTORIQUE_KM"},
}

SECRETS = {c for c, d in DEFINITIONS.items() if d.get("secret")}


def lire(cle):
    """Valeur effective d'un réglage, au format texte."""
    definition = DEFINITIONS.get(cle)
    if definition is None:
        raise KeyError(f"Réglage inconnu : {cle}")

    with base.connexion() as cx:
        ligne = cx.execute(
            "SELECT valeur FROM reglage WHERE cle = ?", (cle,)
        ).fetchone()
    if ligne is not None and ligne["valeur"] != "":
        return ligne["valeur"]

    if definition.get("env"):
        depuis_env = os.environ.get(definition["env"])
        if depuis_env:
            return depuis_env
    return definition["defaut"]


def lire_entier(cle, secours=0):
    try:
        return int(float(lire(cle)))
    except (TypeError, ValueError):
        return secours


def lire_decimal(cle, secours=0.0):
    try:
        return float(str(lire(cle)).replace(",", "."))
    except (TypeError, ValueError):
        return secours


def lire_booleen(cle):
    return str(lire(cle)).strip().lower() in ("1", "true", "oui", "on")


def ecrire(valeurs):
    """Enregistre des réglages. Un réglage vide est effacé, non stocké vide.

    Effacer plutôt qu'enregistrer une chaîne vide rend la main à la variable
    d'environnement ou à la valeur par défaut : c'est ce qui permet de revenir
    en arrière sans avoir à se souvenir de l'ancienne valeur.
    """
    maintenant = dt.datetime.now().isoformat(timespec="seconds")
    a_ecrire, a_effacer = [], []
    for cle, valeur in valeurs.items():
        if cle not in DEFINITIONS:
            continue
        texte = "" if valeur is None else str(valeur).strip()
        (a_effacer if texte == "" else a_ecrire).append(
            cle if texte == "" else (cle, texte, maintenant)
        )

    with base.connexion() as cx:
        if a_ecrire:
            cx.executemany(
                """INSERT INTO reglage (cle, valeur, modifie_le) VALUES (?, ?, ?)
                   ON CONFLICT(cle) DO UPDATE SET
                       valeur = excluded.valeur, modifie_le = excluded.modifie_le""",
                a_ecrire,
            )
        if a_effacer:
            cx.executemany(
                "DELETE FROM reglage WHERE cle = ?", [(c,) for c in a_effacer]
            )
    return len(a_ecrire) + len(a_effacer)


def tous():
    """Tous les réglages pour affichage dans la page.

    Les secrets ne sont jamais renvoyés : on indique seulement s'ils sont
    renseignés, ce qui suffit à l'utilisateur pour savoir où il en est.
    """
    sortie = {}
    for cle in DEFINITIONS:
        if cle in SECRETS:
            sortie[cle] = None
            sortie[f"{cle}_renseigne"] = bool(lire(cle))
        else:
            sortie[cle] = lire(cle)
    return sortie


def messagerie_configuree():
    return bool(lire("smtp_hote")) and bool(lire("alerte_destinataire"))
