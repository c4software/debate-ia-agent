#!/bin/bash
set -e

echo "==> Création de l'environnement virtuel..."
python3 -m venv venv

echo "==> Activation de l'environnement..."
source venv/bin/activate

echo "==> Installation des dépendances..."
pip install --upgrade pip
pip install -e ".[dev]"

echo ""
echo "==> Installation terminée!"
echo ""
echo "Pour activer l'environnement:"
echo "  source venv/bin/activate"
echo ""
echo "Pour lancer le débat:"
echo "  python -m src.main agents-meeting.yaml"
