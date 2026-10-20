"""Reformulation de la question : quelques tournures du langage courant traduites dans le vocabulaire de la loi.

Les vecteurs et le reclasseur ne relient pas « changer de syndic » à « la désignation ou la révocation du ou des
syndics » (article 25 c). On ajoute donc à la question, avant la recherche, les mots de la loi correspondants.

Ce lexique a été écrit à partir des trois seuls échecs du jeu de mise au point (`eval/questions.json`) : il est donc
réglé sur ce jeu et la mesure sur ce jeu est optimiste. Le jeu de contrôle (`eval/controle/`) n'a pas servi à
l'écrire ; c'est lui qui dit si la règle se généralise. Pas d'entrée ajoutée pour faire passer une question du jeu
de contrôle.
"""

import re

from app import config

LEXIQUE: list[tuple[re.Pattern, str]] = [
    # « changer de syndic », « remplacer le syndic » -> article 25 c
    (re.compile(r"\b(chang|remplac)\w*\s+(de|le|du|notre|son)\s+syndic", re.IGNORECASE),
     "désignation ou révocation du syndic"),
    # « fenêtre de toit », « toiture » : travaux d'un copropriétaire sur les parties communes -> article 25 b
    (re.compile(r"\b(toit|toiture|fen[eê]tre de toit)\b", re.IGNORECASE),
     "autorisation d'effectuer à ses frais des travaux affectant les parties communes ou l'aspect extérieur de "
     "l'immeuble"),
    # « ne paie pas ses charges » -> article 19-2 (provisions non versées, mise en demeure)
    (re.compile(r"\bne\s+pa(?:ie|ye)n?t?\s+pas\s+(ses|les|leurs)\s+charges", re.IGNORECASE),
     "défaut du versement d'une provision, mise en demeure restée infructueuse"),
]


def reformuler(question: str) -> str:
    """La question suivie, entre parenthèses, du vocabulaire de la loi correspondant (inchangée si rien ne
    correspond, ou si LEXIQUE=0)."""
    if not config.LEXIQUE:
        return question
    ajouts = [texte for motif, texte in LEXIQUE if motif.search(question)]
    return f"{question} ({' ; '.join(ajouts)})" if ajouts else question
