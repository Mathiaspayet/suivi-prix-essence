"""Réentraîne tous les modèles et affiche le détail de leur évaluation.

    python scripts/entrainer.py
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from carburants.modele import entrainement

if __name__ == "__main__":
    print("Entraînement et évaluation")
    print("=" * 78)
    print("Chaque modèle est jugé sur des périodes qu'il n'a pas apprises, et")
    print("comparé à deux stratégies triviales. La meilleure méthode l'emporte.")
    print("-" * 78)
    entrainement.entrainer_tout()
