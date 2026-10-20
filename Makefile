# Raccourcis (Docker requis). Chaque cible tient en une commande ; les commandes brutes sont dans le README.
.PHONY: demarrer tests evaluation mcp arreter

demarrer:
	docker compose up -d --build

tests:
	docker compose up -d --wait db
	docker compose run --rm --no-deps -e INGESTION_AU_DEMARRAGE=0 api pytest

# Rapport d'évaluation reproductible : eval/resultats/rapport.md (+ un JSON par jeu de questions).
evaluation:
	./scripts/evaluer.sh

# Serveur MCP sur stdio (pour un essai à la main ; Claude Desktop / Claude Code le lancent eux-mêmes).
mcp:
	docker compose up -d --wait db
	docker compose run --rm -T -e INGESTION_AU_DEMARRAGE=0 api python -m app.serveur_mcp

arreter:
	docker compose down
