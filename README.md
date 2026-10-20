# RAG + serveur MCP sur le droit de la copropriété

[![CI](https://github.com/mathieurecatala/rag-copropriete/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mathieurecatala/rag-copropriete/actions/workflows/ci.yml)

Démonstration technique de recherche documentaire (RAG) et de serveur MCP, sur un corpus juridique réel et public,
avec une évaluation chiffrée.

L'outil retrouve, dans la loi du 10 juillet 1965 et le décret du 17 mars 1967 (versions consolidées), les articles
qui répondent à une question de copropriété (charges, assemblée générale, majorités, syndic, conseil syndical,
travaux). Il les cite avec leur lien Légifrance et dit « je ne sais pas » quand ces textes ne semblent pas répondre.
On l'utilise par une page web, une API HTTP, ou depuis un assistant (Claude Desktop, Claude Code) grâce au serveur
MCP.

> **Ce n'est pas un conseil juridique.** La consultation juridique est une activité réglementée (loi n° 71-1130 du
> 31 décembre 1971, articles 54 et suivants). L'outil cite des textes officiels tels quels. Il ne certifie rien,
> peut se tromper d'article, et ne connaît ni la jurisprudence ni le règlement de copropriété d'un immeuble.

## Démarrage

```bash
git clone https://github.com/mathieurecatala/rag-copropriete.git && cd rag-copropriete
docker compose up -d --build      # Postgres 16 + pgvector et API FastAPI, l'ingestion du corpus démarre seule
xdg-open http://localhost:8000    # (open sur Mac) : la page de questions
```

Aucune clé n'est nécessaire. La construction de l'image télécharge le modèle d'embeddings (environ 2,2 Go) et le
reclasseur. L'ingestion des 449 passages prend ensuite quelques secondes, car leurs vecteurs sont livrés
précalculés (`corpus/vecteurs/bge-m3.npz`). `GET /sante` dit où en est l'ingestion. L'API n'écoute que sur
127.0.0.1, car `POST /ingestion` n'a pas d'authentification.

Commandes utiles (Docker requis, `make` est un raccourci facultatif) :

```bash
make tests          # ou : docker compose run --rm api pytest
make evaluation     # ou : ./scripts/evaluer.sh   → eval/resultats/rapport.md
make mcp            # serveur MCP sur stdio, pour un essai à la main
python corpus/telecharger.py   # retélécharger le corpus officiel (environ 3 Go)
```

API : `POST /question {"question": "...", "k": 5}` renvoie `je_ne_sais_pas`, les passages (texte, article, plan,
lien Légifrance, scores) et, si une clé Anthropic est configurée dans `.env`, une réponse rédigée par Claude.

## Serveur MCP

Le serveur (`app/serveur_mcp.py`, SDK Python officiel `mcp` 2.3.0, transport stdio) expose la même recherche à un
assistant, avec deux outils en lecture seule.

- **`rechercher_articles(question, k=5)`** renvoie les articles les plus pertinents avec leur référence
  (`loi-1965 art. 25`), un extrait, le lien Légifrance et les scores. Si la question sort de ces textes, il refuse
  explicitement (`je_ne_sais_pas: true`, aucun article).
- **`lire_article(reference)`** renvoie le texte officiel complet d'un article, avec sa date d'entrée en vigueur et la
  date de consolidation. Il accepte `loi-1965 art. 25`, `décret 1967 article 9 bis` ou `article 17-1 A de la loi`.

Dans Claude Code, la pile étant démarrée par `docker compose up -d` :

```bash
claude mcp add copropriete -- docker compose -f /chemin/vers/rag-copropriete/docker-compose.yml \
  exec -T api python -m app.serveur_mcp
```

La configuration de Claude Desktop, la variante sans laisser l'API tourner et le cas de Docker dans WSL sont décrits
dans [NOTES_TECHNIQUES.md](NOTES_TECHNIQUES.md#brancher-le-serveur-mcp). Autre serveur MCP du même auteur, branché
sur Jira : [mcp-jira-qa](https://github.com/mathieurecatala/mcp-jira-qa).

## Architecture

```
  DILA, base LEGI (données ouvertes, Licence Ouverte 2.0)
              │  corpus/telecharger.py   (une fois, le résultat est versionné)
              ▼
  corpus/donnees/*.json   un article en vigueur par entrée : texte officiel, plan, lien Légifrance
              │  app/ingestion.py   (au démarrage, idempotente)
              │    un passage par article (coupé à 1 500 caractères s'il est long)
              │    embeddings BAAI/bge-m3 (ONNX, processeur), repris de corpus/vecteurs/bge-m3.npz
              ▼
  ┌─────────────── Postgres 16 + pgvector ────────────────┐
  │ passages : vector(1024) [HNSW], tsvector 'french' [GIN] │
  └─────────────────────────────────────────────────────────┘
              ▲
              │  app/recherche.py
              │    1. reformulation : mots courants → vocabulaire de la loi (app/lexique.py, 3 entrées)
              │    2. plein texte BM25 (calculé dans Postgres) + similarité cosinus → fusion RRF pondérée
              │    3. reclasseur cross-encoder (mmarco, ONNX), point par point dans les énumérations
              │    4. article nommé dans la question (« article 26 ») placé en tête
              │    5. « je ne sais pas » si la meilleure similarité de la question d'origine < 0,55
       ┌──────┴───────────────────────┐
  API FastAPI + page web        serveur MCP (stdio)
  POST /question                rechercher_articles, lire_article
```

Le pourquoi de chaque choix (modèle, découpage, fusion, reclasseur, seuil) et les essais chiffrés qui l'ont décidé
sont dans [NOTES_TECHNIQUES.md](NOTES_TECHNIQUES.md).

## Résultats

Chaque question a son ou ses articles attendus. hit@3 est la part des questions dont un article attendu sort dans
les trois premiers résultats. Les questions ont été écrites par une IA à partir du texte, sans relecture par un juriste. Le jeu
de mise au point a servi aux réglages, ses chiffres sont donc optimistes. Le jeu de contrôle a été mis à part et
n'a servi à choisir aucun réglage.

| Jeu (mode hybride + reclasseur) | hit@3 | hit@1 | MRR@10 | Hors sujet refusées |
|---|---|---|---|---|
| Mise au point (20 questions) | 95 % (19/20) | 60 % | 0,78 | 5 sur 5 |
| Contrôle (52 questions) | 90 % (47/52) | 75 % | 0,83 | 7 sur 10 |

La CI rejoue cette évaluation à chaque push et échoue si un chiffre recule d'une seule question. Comparaison des
modes, mesures avant et après correctifs et temps de réponse : [NOTES_TECHNIQUES.md](NOTES_TECHNIQUES.md#évaluation-en-détail).

La même mécanique s'applique à un corpus réglementaire interne (procédures, conformité) : citations obligatoires
et refus quand la réponse n'est pas dans les textes.

## Limites

- Le corpus se limite à la loi de 1965 et au décret de 1967, avec ses annexes. Il ne contient ni Code civil, ni
  jurisprudence, ni règlement d'immeuble. Une réforme demande de relancer `corpus/telecharger.py`,
  `python -m app.ingestion --precalculer` puis l'ingestion.
- Les questions de test ne viennent pas de vraies demandes de copropriétaires.
- Le refus hors sujet reste fragile près du vocabulaire du logement. 3 questions hors corpus sur 10 passent encore
  (assurance habitation, aides à la rénovation, rétractation après un achat en ligne). Une question qui cite un
  autre texte, comme la loi du 6 juillet 1989, peut aussi passer le seuil et renvoyer des articles voisins, sans les
  présenter comme cités.
- La réponse rédigée par Claude n'a été testée qu'avec un client simulé.
- Le serveur MCP ne fonctionne qu'en stdio, sans authentification. Il est prévu pour un usage local.

## Licence

Code sous licence MIT (`LICENSE`). Textes du corpus issus de la base LEGI de la DILA, publiée sous Licence Ouverte /
Open Licence 2.0 (Etalab), vérifié le 12/10/2026 sur
https://www.data.gouv.fr/fr/datasets/legi-codes-lois-et-reglements-consolides/ (fichiers sur
https://echanges.dila.gouv.fr/OPENDATA/LEGI/). La réutilisation est libre, y compris commerciale, en mentionnant la
source et la date de mise à jour, données dans chaque `corpus/donnees/*.json`.

## Auteur

Mathieu Recatala, octobre 2026. Python, FastAPI, Postgres et pgvector, SDK MCP, GitHub Actions, développé avec
Claude Code.
