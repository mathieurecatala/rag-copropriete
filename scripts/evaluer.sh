#!/usr/bin/env bash
# Rapport d'évaluation reproductible en une commande (Docker requis) :
#   ./scripts/evaluer.sh            (ou : make evaluation)
# Démarre la base, construit l'image si besoin, charge le corpus puis mesure les deux jeux de questions.
# Sorties : eval/resultats/rapport.md, eval/resultats/mise_au_point.json, eval/resultats/controle.json.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --wait db
docker compose run --rm --build -e INGESTION_AU_DEMARRAGE=0 -v "$(pwd)/eval/resultats:/app/eval/resultats" api \
    python eval/evaluer.py --ingerer --sans-readme "$@"
