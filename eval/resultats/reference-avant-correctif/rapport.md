# Rapport d'évaluation de la recherche

Produit par `python eval/evaluer.py` le 2026-10-12 (Python 3.12.15). Seuil « je ne sais pas » : 0.55 ; reclasseur : actif ; poids du plein texte dans la fusion : 0.3.

Les questions ont été écrites par une IA (Claude) à partir du texte des articles, pas par un juriste. hit@k : part des questions dont un article attendu est dans les k premiers résultats ; MRR@10 : moyenne de 1/rang de l'article attendu (0 s'il n'est pas dans les 10 premiers).

## Jeu de mise au point (sert aux réglages : mesure optimiste)

`eval/questions.json` : 20 questions du domaine, 5 hors corpus. Temps moyen en mode hybride + reclasseur : 1.53 s par question.

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 50% | 85% | 0.69 |
| Hybride (RRF) sans reclasseur | 45% | 75% | 0.61 |
| Vecteurs seuls | 55% | 75% | 0.66 |
| Plein texte seul | 30% | 45% | 0.41 |

« Je ne sais pas » au seuil 0.55 : 100% des questions hors corpus refusées, 0% des questions du domaine refusées à tort.

Questions dont l'article attendu n'est pas dans les trois premiers (mode hybride + reclasseur) :

- Quelle majorité faut-il en assemblée générale pour changer de syndic ? — attendu loi-1965 art. 25, absent des 10 premiers ; trouvé : loi-1965 art. 21, loi-1965 art. 41-11, loi-1965 art. 18-1 A
- Je veux poser une fenêtre de toit dans mon lot, ce qui touche la toiture : faut-il l'accord de l'assemblée ? — attendu loi-1965 art. 25, absent des 10 premiers ; trouvé : loi-1965 art. 25-2-1, decret-1967 art. 10-4, loi-1965 art. 28
- Que peut faire le syndic quand un copropriétaire ne paie pas ses charges ? — attendu loi-1965 art. 19-2, loi-1965 art. 19, rang 5 ; trouvé : loi-1965 art. 41-15, loi-1965 art. 15, loi-1965 art. 33

Questions hors corpus non refusées :

- aucune

## Jeu de contrôle (mis à part, jamais utilisé pour régler)

`eval/controle/questions.json` : 52 questions du domaine, 10 hors corpus. Temps moyen en mode hybride + reclasseur : 1.27 s par question.

| Mode | hit@1 | hit@3 | MRR@10 |
|---|---|---|---|
| Hybride + reclasseur | 69% | 85% | 0.78 |
| Hybride (RRF) sans reclasseur | 64% | 88% | 0.76 |
| Vecteurs seuls | 73% | 90% | 0.82 |
| Plein texte seul | 35% | 52% | 0.46 |

« Je ne sais pas » au seuil 0.55 : 70% des questions hors corpus refusées, 2% des questions du domaine refusées à tort.

Questions dont l'article attendu n'est pas dans les trois premiers (mode hybride + reclasseur) :

- Quelles parties de l'immeuble appartiennent à un seul copropriétaire ? — attendu loi-1965 art. 2, rang 6 ; trouvé : loi-1965 art. 3, loi-1965 art. 4, loi-1965 art. 25-2-1
- Qui paie les frais de relance et d'huissier quand un copropriétaire est en retard de paiement ? — attendu loi-1965 art. 10-1, rang 4 ; trouvé : loi-1965 art. 26-12, loi-1965 art. 26-13, decret-1967 art. 38
- Le syndic peut-il facturer des honoraires en plus de son forfait annuel ? — attendu loi-1965 art. 18-1 A, decret-1967 art. Annexe 2, rang 6 ; trouvé : decret-1967 art. Annexe 1, loi-1965 art. 21, loi-1965 art. 8-2
- Lors de la vente d'un appartement, comment le syndic récupère-t-il les charges impayées du vendeur ? — attendu loi-1965 art. 20, decret-1967 art. 5-1, rang 4 ; trouvé : decret-1967 art. 5, loi-1965 art. 26-13, loi-1965 art. 29-1 A
- Comment sont élus les membres du conseil syndical ? — attendu loi-1965 art. 25, absent des 10 premiers ; trouvé : loi-1965 art. 17-1, loi-1965 art. 21, decret-1967 art. 25
- Un copropriétaire peut-il installer à ses frais un climatiseur sur la façade de l'immeuble, et quel vote faut-il ? — attendu loi-1965 art. 25, rang 7 ; trouvé : loi-1965 art. 25-2-1, loi-1965 art. 24-9, loi-1965 art. 24
- Quelle majorité faut-il pour voter des travaux d'économies d'énergie ? — attendu loi-1965 art. 25, loi-1965 art. 25-1, rang 4 ; trouvé : loi-1965 art. 14-2-1, loi-1965 art. 24-4, loi-1965 art. 24
- Quel tribunal est compétent pour un litige de copropriété ? — attendu decret-1967 art. 61-1, absent des 10 premiers ; trouvé : decret-1967 art. 42-10, decret-1967 art. 49-1, loi-1965 art. 17

Questions hors corpus non refusées :

- Comment résilier mon contrat d'assurance habitation ? (similarité 0.5887)
- Quelles aides existe-t-il pour rénover une maison individuelle ? (similarité 0.5759)
- Quel est le délai de rétractation après un achat en ligne ? (similarité 0.5533)
