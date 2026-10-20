# RAG + serveur MCP sur le droit de la copropriété

## 1. Ce que c'est

Démonstration technique de recherche documentaire (RAG) et de serveur MCP, sur un corpus juridique réel et public,
avec une évaluation chiffrée.

L'outil retrouve, dans la loi du 10 juillet 1965 et le décret du 17 mars 1967 (versions consolidées), les articles
qui répondent à une question de copropriété (charges, assemblée générale, majorités, syndic, conseil syndical,
travaux), les cite avec leur lien Légifrance, et dit « je ne sais pas » quand ces textes ne semblent pas répondre.
On l'utilise par une page web, une API HTTP, ou depuis un assistant (Claude Desktop, Claude Code) grâce au serveur
MCP.

> **Ce n'est pas un conseil juridique.** La consultation juridique est une activité réglementée (loi n° 71-1130 du
> 31 décembre 1971, articles 54 et suivants). L'outil cite des textes officiels tels quels ; il ne certifie rien,
> peut se tromper d'article, et ne connaît ni la jurisprudence ni le règlement de copropriété d'un immeuble.
> Vérifiez toujours l'article cité.

## 2. Démarrage

```bash
git clone https://github.com/mathieurecatala/rag-copropriete.git && cd rag-copropriete
docker compose up -d --build      # Postgres 16 + pgvector et API FastAPI ; l'ingestion du corpus démarre seule
xdg-open http://localhost:8000    # (open sur Mac) : la page de questions
```

Aucune clé n'est nécessaire. La construction de l'image télécharge le modèle d'embeddings (≈2,2 Go) et le
reclasseur ; au premier démarrage, l'ingestion des 449 passages prend quelques secondes, car leurs vecteurs sont
livrés précalculés (`corpus/vecteurs/bge-m3.npz`, même modèle, même révision ; un test vérifie, sur un
échantillon de passages, qu'ils sont identiques à ceux que calcule le modèle). `GET /sante` dit où en est
l'ingestion. L'API n'écoute que sur 127.0.0.1 : `POST /ingestion` n'a pas d'authentification.

Commandes utiles (Docker requis ; `make` est un raccourci facultatif) :

```bash
make tests          # ou : docker compose run --rm api pytest   (base syndic_test, petit corpus)
make evaluation     # ou : ./scripts/evaluer.sh   → eval/resultats/rapport.md (voir section 6)
make mcp            # serveur MCP sur stdio, pour un essai à la main
python corpus/telecharger.py   # retélécharger le corpus officiel (≈3 Go)
```

API : `POST /question {"question": "...", "k": 5}` renvoie `je_ne_sais_pas`, les passages (texte, article, plan,
lien Légifrance, scores) et, si une clé Anthropic est configurée dans `.env` (voir `.env.example`), une réponse
rédigée par Claude ; `POST /ingestion` ; `GET /sante`.

## 3. Serveur MCP

Le serveur MCP (`app/serveur_mcp.py`, SDK Python officiel `mcp` 2.3.0, transport stdio, version 0.1.0) expose la
même recherche à un assistant. Deux outils, tous deux annotés en lecture seule (`readOnlyHint`, `idempotentHint`,
pas de `openWorldHint`) :

- **`rechercher_articles(question, k=5)`** (k de 1 à 10) : les articles les plus pertinents, chacun avec sa
  référence (`loi-1965 art. 25`), un extrait, le plan du texte, le lien Légifrance, la similarité cosinus et le score
  du reclasseur. Si la question semble hors de ces textes, refus explicite : `je_ne_sais_pas: true`, aucun article,
  et un message qui demande de ne pas répondre à partir d'eux.
- **`lire_article(reference)`** : le texte officiel complet d'un article, lu dans le corpus versionné, avec sa date
  d'entrée en vigueur, la date de consolidation et la licence. Accepte `loi-1965 art. 25`, `décret 1967 article
  9 bis`, `article 17-1 A de la loi`… ; erreur claire si l'article n'existe pas ou si le numéro existe dans les deux
  textes sans précision.

Chaque réponse rappelle que ce n'est pas un conseil juridique. Les tests (`tests/test_mcp.py`) appellent les deux
outils avec le client du SDK, en mémoire et en lançant le serveur comme un vrai processus stdio. Le premier appel
est nettement plus lent que les suivants (chargement des modèles, et du corpus si la base est vide).

**Claude Desktop** (`claude_desktop_config.json`), la pile étant démarrée par `docker compose up -d` :

```json
{
  "mcpServers": {
    "copropriete": {
      "command": "docker",
      "args": ["compose", "-f", "/chemin/vers/rag-copropriete/docker-compose.yml",
               "exec", "-T", "api", "python", "-m", "app.serveur_mcp"]
    }
  }
}
```

**Claude Code** :

```bash
claude mcp add copropriete -- docker compose -f /chemin/vers/rag-copropriete/docker-compose.yml \
  exec -T api python -m app.serveur_mcp
```

Sans laisser l'API tourner, remplacer `exec -T api` par `run --rm -T -e INGESTION_AU_DEMARRAGE=0 api` (la base doit
être démarrée ; le corpus est chargé au premier appel s'il manque). Sur macOS, Claude Desktop ne voit pas toujours le
`PATH` du terminal : mettre le chemin complet de `docker` (`which docker`, par exemple `/usr/local/bin/docker`).
Sous Windows avec Docker dans WSL :

```json
{
  "mcpServers": {
    "copropriete": {
      "command": "wsl",
      "args": ["-d", "Ubuntu", "--", "docker", "compose", "-f", "/chemin/vers/rag-copropriete/docker-compose.yml",
               "exec", "-T", "api", "python", "-m", "app.serveur_mcp"]
    }
  }
}
```

Les formes `exec` et `run` ont été essayées à la main avec un client en ligne de commande, depuis WSL (poignée de
main MCP, liste des outils, `rechercher_articles`, `lire_article`), pas dans Claude Desktop lui-même.

Autre serveur MCP du même auteur, branché sur Jira : https://github.com/mathieurecatala/mcp-jira-qa

## 4. Architecture

```
  DILA, base LEGI (données ouvertes, Licence Ouverte 2.0)
              │  corpus/telecharger.py   (une fois ; le résultat est versionné)
              ▼
  corpus/donnees/*.json   un article en vigueur par entrée : texte officiel, plan, lien Légifrance
              │  app/ingestion.py   (au démarrage ; idempotente)
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

## 5. Choix techniques et pourquoi

- **Corpus tiré des données ouvertes de la DILA (base LEGI), pas de Légifrance directement** : Légifrance bloque les
  requêtes automatiques. Le script part de l'archive globale, applique dans l'ordre les archives quotidiennes, garde
  les articles en vigueur et enregistre la source, la date de consolidation et la date de téléchargement. Le texte
  n'est jamais réécrit, seulement converti de HTML en texte brut.
- **Un passage = un article** (coupé entre paragraphes au-delà de 1 500 caractères), parce qu'on cite un article ;
  chaque passage est indexé avec son en-tête (texte, numéro, plan, phrase d'introduction d'une énumération).
  Des morceaux plus courts (600, 800, 900 caractères) ont été essayés : moins bons (chiffres dans
  `NOTES_TECHNIQUES.md`, comme pour les autres essais ci-dessous).
- **BAAI/bge-m3 en ONNX** : gratuit, local, multilingue, sans PyTorch. Comparé à multilingual-e5 small, base et
  large : meilleur en vecteurs seuls et **le seul qui sépare nettement les questions hors sujet** des questions du
  domaine, ce qui rend le « je ne sais pas » possible. Le prix : 2,2 Go de poids, d'où les vecteurs livrés
  précalculés.
- **Recherche hybride** : les vecteurs rapprochent les mots courants du vocabulaire juridique ; le plein texte BM25
  rattrape les termes exacts (« fonds de travaux »). Fusion RRF, le plein texte pesant 0,3 contre 1 pour les
  vecteurs, parce que le plein texte seul est nettement moins bon (section 6).
- **Reclasseur** (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, multilingue, Apache 2.0, ONNX) : il lit la question
  et chaque article candidat ensemble et les remet en ordre. Dans une énumération (« a) … b) … c) … »), il note
  chaque point séparément, précédé de la phrase d'introduction, et garde le meilleur : sinon un long article comme
  l'article 25 est noyé. `RECLASSEUR=0` le désactive.
- **Lexique de reformulation** : « changer de syndic » ne ressemble pas à « désignation ou révocation du syndic »,
  ni pour les vecteurs ni pour le reclasseur. Trois correspondances écrites à la main sont ajoutées à la question
  (`LEXIQUE=0` pour couper). Elles ont été tirées des échecs du jeu de mise au point : c'est du réglage, mesuré
  ensuite sur le jeu de contrôle (section 6).
- **Questions de majorité** : quand la question parle de majorité ou de vote, les articles 24, 25 et 26 (les trois
  règles de majorité) sont ajoutés aux candidats du reclasseur (`MAJORITES=0` pour couper).
- **Article cité dans la question** (« que dit l'article 26 ? ») : placé en tête, les vecteurs ne sachant pas
  retrouver un numéro. Il ne lève le « je ne sais pas » que si la question désigne sans ambiguïté la loi de 1965 ou
  le décret de 1967 (« loi de 1965 », « 10 juillet 1965 », « n° 65-557 », « décret de 1967 »…), ou si elle est déjà
  assez proche du corpus (similarité ≥ 0,45, valeur choisie à la main : aucune question d'évaluation ne cite
  d'article) ; « de la loi » seul ne suffit pas. Un autre texte nommé annule la citation : code, ordonnance, loi ou
  décret d'une autre date ou d'un autre numéro (« loi du 6 juillet 1989 », « décret du 26 août 1987 »), ou désigné
  par un nom (« loi Hamon », « loi ALUR »). Ainsi « tarte aux pommes, article 42 » et « article 42 de la loi sur la
  tarte aux pommes » sont refusées (tests dans `tests/test_recherche.py`).
- **« Je ne sais pas » sur la similarité cosinus de la question d'origine**, pas sur le score RRF (qui ne dépend que
  des rangs) ni sur la question reformulée (le lexique ne doit pas faire passer une question hors sujet).
  Seuil 0,55, au milieu de l'écart observé entre questions du domaine et hors sujet sur le jeu de mise au point.
- **Claude facultatif** : sans clé, l'outil reste utile (les articles s'affichent avec leur lien) ; avec clé, Claude
  ne reçoit que les passages trouvés et doit citer l'article de chaque affirmation.

## 6. Évaluation

**Comment on mesure.** Chaque question a son ou ses articles attendus. hit@3 = part des questions dont un article
attendu est dans les trois premiers résultats ; hit@1 = au premier rang ; MRR@10 = moyenne de 1/rang (0 au-delà du
10e). Les questions hors corpus doivent être refusées (« je ne sais pas »).

**Deux jeux de questions.** Le jeu de mise au point (`eval/questions.json`, 20 questions + 5 hors corpus) a servi à
tous les réglages : ses chiffres sont optimistes. Le jeu de contrôle (`eval/controle/questions.json`, 52 questions +
10 hors corpus) a été écrit après les premiers réglages (modèle, poids de fusion, seuil, reclasseur) mais **avant le
correctif de l'article 25**, puis mesuré deux fois : avant et après ce correctif. Le correctif a été réglé sur le seul
jeu de mise au point ; le contrôle n'a jamais servi à choisir un réglage, mais ses échecs étaient visibles pendant le
travail : ce n'est pas une mesure aveugle. **Les questions ont été écrites par une IA à partir du texte, pas par un
juriste.**

**Avant / après la correction du défaut de l'article 25** (mode hybride + reclasseur ; résultats complets :
`eval/resultats/reference-avant-correctif/` et `eval/resultats/`) :

| Jeu | hit@3 avant | hit@3 après | hit@1 avant → après | MRR@10 avant → après | hors sujet refusées |
|---|---|---|---|---|---|
| Mise au point (20) | 85 % (17/20) | 95 % (19/20) | 50 % → 60 % | 0,69 → 0,78 | 5/5 |
| Contrôle (52) | 85 % (44/52) | 90 % (47/52) | 69 % → 75 % | 0,78 → 0,83 | 7/10 |

Ce que montre le jeu de contrôle :

- Le gain est plus faible hors du jeu de réglage (+5 points de hit@3 contre +10), comme attendu, et il tient à
  3 questions sur 52. Les deux plus fortes remontées (climatiseur en façade « et quel vote », rang
  7 → 1 ; « quelle majorité pour des travaux d'économies d'énergie », rang 4 → 1) parlent de vote ou de majorité,
  le cas visé par la règle « majorités », qui n'avait pourtant aucun effet seule sur le jeu de mise au point. Une
  question recule (le gardien, rang 2 → 5).
- **Avant la correction, le reclasseur n'aidait pas sur le contrôle** (hit@3 88 % sans, 85 % avec). Après, la
  chaîne complète (90 %) ne fait qu'égaler les vecteurs seuls en hit@3 (90 %) et les dépasse à peine en hit@1
  (75 % contre 73 %) et en MRR (0,83 contre 0,82). Sur ces textes, bge-m3 seul fait déjà l'essentiel du travail.
- Le seuil « je ne sais pas » laisse passer 3 questions hors corpus sur 10 (assurance habitation, aides à la
  rénovation, rétractation après un achat en ligne : vocabulaire proche du logement) et refuse à tort 1 question du
  domaine sur 52.
- Coût : 3,9 à 4,0 s par question dans le rapport livré (`eval/resultats/rapport.md`, mesuré sous WSL2 sur un
  Intel Core i9-14900HX, 32 cœurs logiques), contre 1,3 à 1,5 s avant le correctif sur la même machine
  (`reference-avant-correctif/rapport.md`). D'autres passages sur cette machine ont donné de 2 à 4,5 s : le temps
  varie avec la charge. C'est le prix du reclasseur point par point, qui lit chaque point des longues énumérations.

Reproduire : `./scripts/evaluer.sh` (ou `make evaluation`), qui démarre la base, charge le corpus et écrit
`eval/resultats/rapport.md` (détail par mode, questions ratées, questions hors corpus non refusées) et un JSON par
jeu. `python eval/evaluer.py` (dans le conteneur, sans `--sans-readme`) met aussi à jour le résumé ci-dessous.
En CI, `--comparer` fait échouer l'étape si un chiffre recule d'une seule question par rapport aux résultats
commités (hit@1, hit@3, MRR, refus hors sujet, refus à tort).

<!-- EVAL:DEBUT -->
Mesuré par `eval/evaluer.py` (rapport complet : `eval/resultats/rapport.md`). Deux jeux de questions, chacune avec l'article attendu, plus des questions hors corpus. **Les questions ont été écrites par une IA à partir du texte, pas par un juriste.**

- Jeu de mise au point (sert aux réglages : mesure optimiste) : hit@3 19/20 = 95%, hit@1 60%, MRR@10 0.78 ; hors sujet refusées 100% (5 questions), refus à tort 0%.
- Jeu de contrôle (mis à part, jamais utilisé pour régler) : hit@3 47/52 = 90%, hit@1 75%, MRR@10 0.83 ; hors sujet refusées 70% (10 questions), refus à tort 2%.

**Jeu de mise au point (sert aux réglages : mesure optimiste)** (`eval/questions.json`, 20 questions) :

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 60% | 95% | 0.78 |
| Hybride (RRF) sans reclasseur | 45% | 80% | 0.64 |
| Vecteurs seuls | 55% | 80% | 0.68 |
| Plein texte seul | 45% | 55% | 0.53 |

**Jeu de contrôle (mis à part, jamais utilisé pour régler)** (`eval/controle/questions.json`, 52 questions) :

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 75% | 90% | 0.83 |
| Hybride (RRF) sans reclasseur | 64% | 88% | 0.76 |
| Vecteurs seuls | 73% | 90% | 0.82 |
| Plein texte seul | 35% | 52% | 0.46 |
<!-- EVAL:FIN -->

## 7. Limites et ce qui n'est pas fait

- **Corpus limité** à la loi de 1965 et au décret de 1967 (avec ses annexes, dont le contrat type de syndic) : pas de
  Code civil, pas de jurisprudence, pas de réponses ministérielles, pas le règlement de l'immeuble. Version
  consolidée à la date indiquée dans `corpus/donnees/*.json` ; une réforme postérieure demande de relancer
  `corpus/telecharger.py`, `python -m app.ingestion --precalculer` puis l'ingestion.
- **Questions encore ratées** (rapport complet dans `eval/resultats/rapport.md`) : « comment sont élus les membres
  du conseil syndical ? » (article 25, absent des 10 premiers), le tribunal compétent (décret art. 61-1), la fenêtre
  de toit (article 25 au 6e rang malgré le lexique)…
- **Le lexique a été écrit à partir des échecs du jeu de mise au point** : trois entrées seulement, qui ne couvrent
  pas les autres façons de dire les choses.
- **Génération par un modèle de langage non testée en réel** : la réponse rédigée par Claude n'a été essayée
  qu'avec un client simulé (aucune clé pendant la construction). Pas de génération locale (Ollama) : non faite.
- Le serveur MCP ne fonctionne qu'en stdio (pas de transport HTTP) et n'a pas d'authentification : il est prévu pour
  un usage local.
- Le refus hors sujet reste fragile près du vocabulaire du logement : « que dit l'article 1 du code de la
  consommation sur le délai de rétractation ? » n'est refusée que de justesse (similarité juste sous le seuil). Une
  question qui cite un autre texte n'a plus d'article « cité », mais elle reste jugée par le seuil ordinaire : sur le
  corpus complet, « que dit l'article 15 de la loi du 6 juillet 1989 sur le congé du locataire ? » et « décret du
  26 août 1987, article 1 : quelles charges récupérables ? » passent le seuil et renvoient des articles voisins de la
  loi de 1965 ou du décret de 1967, sans les présenter comme cités.
- Les questions ne viennent pas de vraies demandes : elles ne disent rien de la façon dont de vrais copropriétaires
  formulent les leurs.

## 8. Licence

Code : MIT (`LICENSE`).

Textes du corpus : base LEGI de la DILA (« LEGI - Codes, lois et règlements consolidés », producteur : Premier
ministre), publiée sous **Licence Ouverte / Open Licence 2.0** (Etalab), vérifié le 12/10/2026 sur
https://www.data.gouv.fr/fr/datasets/legi-codes-lois-et-reglements-consolides/ ; fichiers sur
https://echanges.dila.gouv.fr/OPENDATA/LEGI/. Réutilisation libre, y compris commerciale, sous réserve de
mentionner la source et la date de mise à jour (données de chaque texte dans `corpus/donnees/*.json`).

## 9. Méthode

Mathieu Recatala, octobre 2026. Développement assisté par IA (Claude Code), validé par tests automatisés, intégration
continue (GitHub Actions) et agents relecteurs.
