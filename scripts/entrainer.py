"""Réentraîne tous les modèles et affiche le détail de leur évaluation.

    python scripts/entrainer.py
"""
import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from carburants.modele import entrainement

if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--valider", action="store_true",
        help="refaire concourir toutes les méthodes (long : plusieurs minutes)",
    )
    analyseur.add_argument(
        "--reajuster", action="store_true",
        help="se contenter de réajuster les méthodes déjà retenues (rapide)",
    )
    options = analyseur.parse_args()
    revalider = True if options.valider else (False if options.reajuster else None)

    print("Entraînement et évaluation")
    print("=" * 78)
    if revalider is not False:
        print("Chaque modèle est jugé sur des périodes qu'il n'a pas apprises, et")
        print("comparé à deux stratégies triviales. La meilleure méthode l'emporte.")
    print("-" * 78)
    entrainement.entrainer_tout(revalider=revalider)
