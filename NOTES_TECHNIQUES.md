# Notes techniques

Le détail derrière le [README](README.md) : les choix techniques, le branchement du serveur MCP, l'évaluation
complète et les essais qui ont conduit aux réglages.

## Choix techniques et pourquoi

Le corpus vient des données ouvertes de la DILA (base LEGI), car Légifrance bloque les requêtes automatiques. Le
script part de l'archive globale, applique dans l'ordre les archives quotidiennes, garde les articles en vigueur et
enregistre la source, la date de consolidation et la date de téléchargement. Le texte n'est jamais réécrit, il est
seulement converti de HTML en texte brut.

Un passage correspond à un article, coupé entre paragraphes au-delà de 1 500 caractères, parce que l'outil cite des
articles. Chaque passage est indexé avec son en-tête (texte, numéro, plan, phrase d'introduction d'une énumération).

Le modèle d'embeddings est BAAI/bge-m3 en ONNX : gratuit, local, multilingue et sans PyTorch. Comparé aux
multilingual-e5, il est meilleur en vecteurs seuls et c'est le seul qui sépare nettement les questions hors sujet
des questions du domaine, ce qui rend le « je ne sais pas » possible. Ses poids font 2,2 Go, d'où les vecteurs livrés
précalculés. Un test vérifie sur un échantillon de passages qu'ils sont identiques à ceux que calcule le modèle
(même modèle, même révision).

La recherche est hybride. Les vecteurs rapprochent les mots courants du vocabulaire juridique, et le plein texte BM25
rattrape les termes exacts (« fonds de travaux »). La fusion RRF donne un poids de 0,3 au plein texte contre 1 aux
vecteurs, parce que le plein texte seul est nettement moins bon.

Le reclasseur `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingue, Apache 2.0, ONNX) lit la question et chaque
article candidat ensemble et les remet en ordre. Dans une énumération (« a) … b) … c) … »), il note chaque point
séparément, précédé de la phrase d'introduction, et garde le meilleur. Sans cela, un long article comme l'article 25
est noyé. `RECLASSEUR=0` le désactive.

« Changer de syndic » ne ressemble pas à « désignation ou révocation du syndic », ni pour les vecteurs ni pour le
reclasseur. Un lexique de trois correspondances écrites à la main est donc ajouté à la question (`LEXIQUE=0` pour
couper). Ces correspondances viennent des échecs du jeu de mise au point. C'est du réglage, mesuré ensuite sur le
jeu de contrôle.

Quand la question parle de majorité ou de vote, les articles 24, 25 et 26 (les trois règles de majorité) sont ajoutés
aux candidats du reclasseur (`MAJORITES=0` pour couper).

Un article cité dans la question (« que dit l'article 26 ? ») est placé en tête, car les vecteurs ne savent pas
retrouver un numéro. Le détail est dans la section dédiée plus bas.

Le « je ne sais pas » se décide sur la similarité cosinus de la question d'origine. Le score RRF ne dépend que des
rangs, et la question reformulée ne doit pas faire passer une question hors sujet. Le seuil de 0,55 est au milieu
de l'écart observé entre questions du domaine et hors sujet sur le jeu de mise au point.

Claude est facultatif. Sans clé, l'outil reste utile et les articles s'affichent avec leur lien. Avec une clé (voir
`.env.example`), Claude ne reçoit que les passages trouvés et doit citer l'article de chaque affirmation.

## Brancher le serveur MCP

Les deux outils sont annotés en lecture seule (`readOnlyHint`, `idempotentHint`, pas de `openWorldHint`).
`lire_article` renvoie une erreur claire si l'article n'existe pas, ou si le numéro existe dans les deux textes sans
précision. Chaque réponse rappelle que ce n'est pas un conseil juridique. Les tests (`tests/test_mcp.py`) appellent
les deux outils avec le client du SDK, en mémoire et en lançant le serveur comme un vrai processus stdio. Le premier
appel est nettement plus lent que les suivants (chargement des modèles, et du corpus si la base est vide).

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

Pour ne pas laisser l'API tourner, remplacer `exec -T api` par `run --rm -T -e INGESTION_AU_DEMARRAGE=0 api`. La base
doit être démarrée, et le corpus est chargé au premier appel s'il manque. Sur macOS, Claude Desktop ne voit pas
toujours le `PATH` du terminal. Il faut alors mettre le chemin complet de `docker` (`which docker`, par exemple
`/usr/local/bin/docker`).

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

## Évaluation en détail

**Mesures.** hit@3 est la part des questions dont un article attendu est dans les trois premiers résultats, hit@1
la part au premier rang. MRR@10 est la moyenne de 1/rang, avec 0 au-delà du 10e. Les questions hors corpus doivent
être refusées.

**Deux jeux de questions.** Le jeu de mise au point (`eval/questions.json`, 20 questions et 5 hors corpus) a servi à
tous les réglages. Le jeu de contrôle (`eval/controle/questions.json`, 52 questions et 10 hors corpus) a été écrit
après les premiers réglages (modèle, poids de fusion, seuil, reclasseur), mais avant le correctif de l'article 25.
Il a été mesuré avant et après ce correctif. Le correctif a été réglé sur le seul jeu de mise au point, mais les
échecs du contrôle étaient visibles pendant le travail. Ce n'est donc pas une mesure aveugle.

**Avant et après le correctif de l'article 25** (mode hybride + reclasseur, résultats complets dans
`eval/resultats/reference-avant-correctif/` et `eval/resultats/`) :

| Jeu | hit@3 avant | hit@3 après | hit@1 avant → après | MRR@10 avant → après | Hors sujet refusées |
|---|---|---|---|---|---|
| Mise au point (20) | 85 % (17/20) | 95 % (19/20) | 50 % → 60 % | 0,69 → 0,78 | 5/5 |
| Contrôle (52) | 85 % (44/52) | 90 % (47/52) | 69 % → 75 % | 0,78 → 0,83 | 7/10 |

Ce que montre le jeu de contrôle :

- Le gain est plus faible hors du jeu de réglage (5 points de hit@3 contre 10), et il tient à 3 questions sur 52.
  Les deux plus fortes remontées parlent de vote ou de majorité (« climatiseur en façade, et quel vote », rang 7 à 1,
  et « quelle majorité pour des travaux d'économies d'énergie », rang 4 à 1). C'est le cas visé par la règle des
  majorités, qui n'avait aucun effet seule sur le jeu de mise au point. Une question recule (le gardien, rang 2 à 5).
- Avant le correctif, le reclasseur n'aidait pas sur le contrôle (hit@3 88 % sans, 85 % avec). Après, la chaîne
  complète égale les vecteurs seuls en hit@3 (90 %) et les dépasse un peu en hit@1 (75 % contre 73 %) et en MRR
  (0,83 contre 0,82). Sur ces textes, bge-m3 fait déjà l'essentiel du travail.
- Le seuil « je ne sais pas » laisse passer 3 questions hors corpus sur 10 et refuse à tort 1 question du domaine
  sur 52.
- Coût : 3,9 à 4,0 s par question dans le rapport livré (`eval/resultats/rapport.md`, sous WSL2 sur un Intel Core
  i9-14900HX, 32 cœurs logiques), contre 1,3 à 1,5 s avant le correctif sur la même machine. D'autres passages ont
  donné de 2 à 4,5 s, le temps varie avec la charge. C'est le prix du reclasseur point par point.

**Par mode, jeu de mise au point** (20 questions) :

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 60 % | 95 % | 0,78 |
| Hybride (RRF) sans reclasseur | 45 % | 80 % | 0,64 |
| Vecteurs seuls | 55 % | 80 % | 0,68 |
| Plein texte seul | 45 % | 55 % | 0,53 |

**Par mode, jeu de contrôle** (52 questions) :

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 75 % | 90 % | 0,83 |
| Hybride (RRF) sans reclasseur | 64 % | 88 % | 0,76 |
| Vecteurs seuls | 73 % | 90 % | 0,82 |
| Plein texte seul | 35 % | 52 % | 0,46 |

**Questions encore ratées** (liste complète dans `eval/resultats/rapport.md`) : « comment sont élus les membres du
conseil syndical ? » (article 25, absent des 10 premiers), le tribunal compétent (décret, article 61-1), la fenêtre
de toit (article 25 au 6e rang malgré le lexique).

**Refus hors sujet près du seuil.** « Que dit l'article 1 du code de la consommation sur le délai de rétractation ? »
n'est refusée que de peu, sa similarité est juste sous le seuil. Sur le corpus complet, « que dit l'article 15 de la
loi du 6 juillet 1989 sur le congé du locataire ? » et « décret du 26 août 1987, article 1 : quelles charges
récupérables ? » passent le seuil ordinaire et renvoient des articles voisins de la loi de 1965 ou du décret de
1967, sans les présenter comme cités.

**Reproduire.** `./scripts/evaluer.sh` (ou `make evaluation`) démarre la base, charge le corpus et écrit
`eval/resultats/rapport.md` (détail par mode, questions ratées, questions hors corpus non refusées) et un JSON par
jeu. En CI, `--comparer` fait échouer l'étape si un chiffre recule d'une seule question par rapport aux résultats
commités (hit@1, hit@3, MRR, refus hors sujet, refus à tort). Les tableaux ci-dessus sont recopiés de ces fichiers.

## Essais

Mesurés avec `eval/evaluer.py` sur le jeu de mise au point, sauf mention contraire. Ce jeu a servi aux réglages,
ces chiffres sont donc optimistes.

### Modèle d'embeddings (octobre 2026)

| Modèle | hit@3 vecteurs seuls | hit@3 hybride | similarité min. du domaine | similarité max. hors sujet |
|---|---|---|---|---|
| multilingual-e5-small | 55 % | 60-75 % | 0,86 | 0,86 |
| multilingual-e5-base | 60 % | 60 % | 0,84 | 0,85 |
| multilingual-e5-large | 55 % | 70 % | 0,84 | 0,83 |
| **BAAI/bge-m3** | **75 %** | 65-75 % | 0,59 | 0,52 |

Avec les e5, les questions hors sujet ressemblent autant au corpus que les vraies questions, et aucun seuil ne les
sépare. bge-m3 laisse un écart (0,52 contre 0,59), d'où le seuil « je ne sais pas » à 0,55, au milieu.

### Plein texte et fusion

- Plein texte : `ts_rank_cd` en OU, puis IDF seul, puis BM25 calculé dans Postgres à partir du tsvector. BM25 a été
  retenu (45 % contre 40 % en plein texte seul).
- Fusion RRF (k = 60) : à poids égal, l'hybride descendait à 65 %. Avec un poids de 0,3 pour le plein texte, il
  égale les vecteurs seuls. Poids choisi sur ce même jeu.

### Découpage

- Morceaux de 1 500 caractères au plus, coupés entre paragraphes. Les tailles 600, 800, 900 et 2 500 caractères ont
  été essayées et sont moins bonnes.
- Un seul morceau par article dans les résultats, sinon un long article occupe tout le top 3.
- Découpage d'un article par point d'énumération (a), b), c)…) à l'indexation : 80 % sans reclasseur, 85 % avec.
  Le corpus passe de 449 à 737 passages, sans retrouver l'article 25. Non retenu à l'indexation, la lecture point
  par point est faite par le reclasseur.

### Reclasseur

- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (ONNX) sur les 10 premiers articles : hit@3 de 75 à 85 %, MRR@10 de
  0,61 à 0,69, environ 0,6 s de plus par question.
- 20 candidats au lieu de 10 donnent le même hit@3, en plus lent. Tous les morceaux des 20 premiers articles aussi.
- `bge-reranker-v2-m3` (int8) donne le même hit@3, trois fois plus lent. `jina-reranker-v2` a été écarté (licence
  non commerciale).

### Correctif de l'article 25

L'article 25 (majorité absolue) est une longue énumération (points a à o). Son premier morceau, 1 320 caractères,
mélange les points a) à e). Son vecteur est dilué, et même « désigner ou révoquer le syndic » le met au 45e rang en
vecteurs. Le reclasseur ne relie pas « changer de syndic » au point c) et préfère l'article 26 c) (le gardien).

Trois mécanismes, essayés seuls puis combinés sur le jeu de mise au point (hit@3) :

| Variante | hit@3 |
|---|---|
| aucun | 85 % |
| (1) lexique de reformulation seul | 90 % |
| (2) articles de majorité ajoutés aux candidats, seul | 85 % |
| (3) reclasseur point par point, seul | 85 % |
| (1) + (2) | 95 % |
| (1) + (3) | 90 % |
| (1) + (2) + (3) | 95 % (hit@1 60 %, MRR@10 0,78) |

Les trois sont retenus. Le « je ne sais pas » reste calculé sur la question d'origine, pas sur la question
reformulée. La mesure sur le jeu de contrôle, avant et après, est plus haut.

### Article cité dans la question

Un numéro d'article nommé (« que dit l'article 26 ? ») place cet article en tête, car les vecteurs ne retrouvent pas
un numéro. Il ne lève le « je ne sais pas » que si la question désigne sans ambiguïté la loi de 1965 ou le décret de
1967 (année, numéro 65-557 ou 67-223, date complète), ou si sa similarité atteint 0,45. « De la loi » seul ne suffit
pas. Un autre texte nommé annule la citation : code, ordonnance, loi ou décret d'une autre date (« loi du 6 juillet
1989 », « décret de 1987 ») ou d'un autre numéro, ou désigné par un nom (« loi Hamon », « loi ALUR »). Ainsi
« tarte aux pommes, article 42 » et « article 42 de la loi sur la tarte aux pommes » sont refusées (tests dans
`tests/test_recherche.py`). Aucune question des deux jeux ne cite d'article. Le plancher de 0,45 n'a donc été réglé
sur aucun des deux, et les chiffres d'évaluation n'ont pas bougé.
