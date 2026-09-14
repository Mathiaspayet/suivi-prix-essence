"""Constitution de l'historique complet, à lancer une seule fois.

Télécharge chaque archive annuelle, en extrait les moyennes nationales
quotidiennes, puis récupère les séries de marché. Le script est rejouable :
une année déjà importée est sautée, et une archive déjà téléchargée est
réutilisée.

    python scripts/initialiser.py
"""
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carburants import base, config
from carburants.sources import historique, marche


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--depuis", type=int, default=config.PREMIERE_ANNEE_DISPONIBLE,
                           help="première année à importer")
    analyseur.add_argument("--refaire", action="store_true",
                           help="réimporter même les années déjà en base")
    options = analyseur.parse_args()

    base.initialiser()
    annee_courante = dt.date.today().year
    deja = base.annees_deja_importees()

    print(f"Historique des prix à la pompe ({options.depuis} → {annee_courante})")
    print("=" * 58)

    for annee in range(options.depuis, annee_courante + 1):
        if annee in deja and not options.refaire:
            print(f"  {annee} : déjà en base ({deja[annee]} lignes), ignorée")
            continue

        depart = time.time()
        print(f"  {annee} : téléchargement…", flush=True)
        try:
            chemin = historique.telecharger_archive(annee)
        except Exception as erreur:
            print(f"  {annee} : téléchargement impossible ({erreur}) — année ignorée")
            continue

        taille = chemin.stat().st_size / 1048576
        print(f"  {annee} : {taille:.1f} Mo, analyse en cours…", flush=True)
        lignes = historique.agreger_annee(annee, journal=lambda m: None)
        base.enregistrer_prix_national(lignes)
        print(f"  {annee} : {len(lignes)} lignes en base "
              f"({time.time() - depart:.0f} s)", flush=True)

    print("-" * 58)
    print("Données de marché (Brent, euro/dollar)…", flush=True)
    marche.rafraichir(depuis=f"{options.depuis - 1}-01-01")

    with base.connexion() as cx:
        resume = cx.execute(
            """SELECT carburant, COUNT(*) AS jours, MIN(date) AS debut, MAX(date) AS fin
               FROM prix_national GROUP BY carburant ORDER BY carburant"""
        ).fetchall()
    print("=" * 58)
    print("Récapitulatif :")
    for ligne in resume:
        print(f"  {ligne['carburant']:7} : {ligne['jours']:5} jours  "
              f"du {ligne['debut']} au {ligne['fin']}")


if __name__ == "__main__":
    main()
