"""Découpage du corpus : un passage par article, ou plusieurs morceaux si l'article est long.

Le texte officiel n'est jamais modifié : les morceaux sont des tranches consécutives de l'article,
coupées entre deux paragraphes (ou entre deux phrases si un paragraphe dépasse la taille maximale).
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app import config


@dataclass
class Passage:
    texte_id: str
    texte_titre: str
    article_id: str
    article_num: str
    chemin: str
    morceau: int
    contenu: str
    url: str
    chapeau: str = ""

    @property
    def entete(self) -> str:
        """Ce qui situe le passage : texte, article, plan, et la phrase d'introduction de l'article pour un
        morceau qui ne la contient pas (« Ne sont adoptées qu'à la majorité… : » devant les points f à j)."""
        entete = f"{self.texte_titre}, article {self.article_num}. {self.chemin}".strip()
        return f"{entete}\n{self.chapeau} […]" if self.chapeau else entete

    @property
    def a_indexer(self) -> str:
        return f"{self.entete}\n{self.contenu}"

    @property
    def empreinte(self) -> str:
        return hashlib.sha256(f"{self.a_indexer}\n{self.url}".encode()).hexdigest()


def _tranches(paragraphe: str, taille_max: int) -> list[str]:
    if len(paragraphe) <= taille_max:
        return [paragraphe]
    phrases = re.split(r"(?<=[.;:])\s+", paragraphe)
    tranches, courante = [], ""
    for phrase in phrases:
        if courante and len(courante) + 1 + len(phrase) > taille_max:
            tranches.append(courante)
            courante = phrase
        else:
            courante = f"{courante} {phrase}".strip()
    if courante:
        tranches.append(courante)
    return tranches


def decouper_texte(texte: str, taille_max: int = config.TAILLE_MAX_MORCEAU) -> list[str]:
    paragraphes = [p.strip() for p in texte.split("\n") if p.strip()]
    morceaux, courant = [], ""
    for paragraphe in paragraphes:
        for tranche in _tranches(paragraphe, taille_max):
            if courant and len(courant) + 1 + len(tranche) > taille_max:
                morceaux.append(courant)
                courant = tranche
            else:
                courant = f"{courant}\n{tranche}" if courant else tranche
    if courant:
        morceaux.append(courant)
    return morceaux


TAILLE_MAX_CHAPEAU = 300


def chapeau(texte: str) -> str:
    """Premier alinéa de l'article s'il est court et annonce une énumération (finit par « : »)."""
    premier = texte.strip().split("\n", 1)[0].strip()
    return premier if len(premier) <= TAILLE_MAX_CHAPEAU and premier.endswith(":") else ""


def passages_du_texte(document: dict, taille_max: int = config.TAILLE_MAX_MORCEAU) -> list[Passage]:
    passages = []
    for article in document["articles"]:
        intro = chapeau(article["texte"])
        for i, contenu in enumerate(decouper_texte(article["texte"], taille_max)):
            passages.append(
                Passage(
                    texte_id=document["id"],
                    texte_titre=document["titre_court"],
                    article_id=article["id"],
                    article_num=article["num"],
                    chemin=article.get("chemin", ""),
                    morceau=i,
                    contenu=contenu,
                    url=article["url"],
                    chapeau="" if contenu.startswith(intro) else intro,
                )
            )
    return passages


def charger_corpus(dossier: Path = config.DOSSIER_CORPUS) -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(dossier.glob("*.json"))]
