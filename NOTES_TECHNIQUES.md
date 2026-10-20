# Notes techniques : les essais et leurs chiffres

Les essais qui ont conduit aux choix du README, mesurés avec `eval/evaluer.py` sur le **jeu de mise au point**
(`eval/questions.json`, 20 questions + 5 hors corpus), sauf mention contraire. Ce jeu a servi aux réglages : ces
chiffres sont optimistes. hit@3 = part des questions dont l'article attendu est dans les trois premiers résultats.

## Modèle d'embeddings (octobre 2026)

| Modèle | hit@3 vecteurs seuls | hit@3 hybride | similarité min. du domaine | similarité max. hors sujet |
|---|---|---|---|---|
| multilingual-e5-small | 55 % | 60-75 % | 0,86 | 0,86 |
| multilingual-e5-base | 60 % | 60 % | 0,84 | 0,85 |
| multilingual-e5-large | 55 % | 70 % | 0,84 | 0,83 |
| **BAAI/bge-m3** | **75 %** | 65-75 % | 0,59 | 0,52 |

Avec les e5, les questions hors sujet ressemblent autant au corpus que les vraies questions : aucun seuil ne les
sépare. bge-m3 laisse un écart (0,52 contre 0,59), d'où le seuil « je ne sais pas » à 0,55, au milieu.

## Plein texte et fusion

- Plein texte : `ts_rank_cd` en OU, puis IDF seul, puis BM25 calculé dans Postgres à partir du tsvector. BM25 retenu
  (45 % contre 40 % en plein texte seul).
- Fusion RRF (k = 60) : à poids égal, l'hybride descendait à 65 % ; avec un poids de 0,3 pour le plein texte, il
  égale les vecteurs seuls. Poids choisi sur ce même jeu.

## Découpage

- Morceaux de 1 500 caractères au plus, coupés entre paragraphes ; 600, 800, 900 et 2 500 caractères essayés :
  moins bons.
- Un seul morceau par article dans les résultats, sinon un long article occupe tout le top 3.
- Découpage d'un article par point d'énumération (a), b), c)…) à l'indexation : 80 % sans reclasseur, 85 % avec, et
  le corpus passe de 449 à 737 passages, sans retrouver l'article 25 : non retenu à l'indexation (la lecture point
  par point est faite par le reclasseur, voir plus bas).

## Reclasseur

- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (ONNX) sur les 10 premiers articles : hit@3 75 → 85 %, MRR@10
  0,61 → 0,69, environ 0,6 s de plus par question.
- 20 candidats au lieu de 10 : même hit@3, plus lent. Tous les morceaux des 20 premiers articles : même hit@3.
- `bge-reranker-v2-m3` (int8) : même hit@3, trois fois plus lent. `jina-reranker-v2` écarté (licence non
  commerciale).
- Sur le jeu de contrôle, avant le correctif de l'article 25, le reclasseur n'aidait pas : 88 % sans, 85 % avec.

## Correctif de l'article 25

L'article 25 (majorité absolue) est une longue énumération (points a à o). Son premier morceau, 1 320 caractères,
mélange les points a) à e) : son vecteur est dilué, et même « désigner ou révoquer le syndic » le met au 45e rang en
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
reformulée. Mesure sur le jeu de contrôle, avant puis après : voir la section 6 du README.

## Article cité dans la question

Un numéro d'article nommé (« que dit l'article 26 ? ») place cet article en tête : les vecteurs ne retrouvent pas un
numéro. Il ne lève le « je ne sais pas » que si la question désigne sans ambiguïté la loi de 1965 ou le décret de
1967 (année, numéro 65-557 / 67-223 ou date complète), ou si sa similarité atteint 0,45 ; « de la loi » seul ne
suffit pas. Un autre texte nommé annule la citation : code, ordonnance, loi ou décret d'une autre date (« loi du
6 juillet 1989 », « décret de 1987 ») ou d'un autre numéro, ou désigné par un nom (« loi Hamon »). Aucune question des deux jeux
ne cite d'article : le plancher de 0,45 n'a été réglé sur aucun des deux, et les chiffres d'évaluation n'ont pas
bougé.
