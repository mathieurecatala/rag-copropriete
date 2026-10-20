"""Serveur MCP (Model Context Protocol, transport stdio) : la recherche dans les textes de la copropriété, exposée
à un assistant comme Claude Desktop ou Claude Code.

Deux outils :
- `rechercher_articles(question, k)` : la même recherche que l'API (hybride + reclasseur), qui renvoie les articles
  trouvés avec un extrait, la référence à passer à `lire_article`, le lien Légifrance et les scores ; ou un refus
  explicite (« je ne sais pas ») quand la question semble hors du corpus ;
- `lire_article(reference)` : le texte officiel complet d'un article (« loi-1965 art. 25 », « décret 1967 article
  9 bis »…), lu dans le corpus versionné (pas besoin de la base).

Lancement : `python -m app.serveur_mcp` (dans le conteneur : `docker compose exec -T api python -m app.serveur_mcp`).
Les journaux vont sur la sortie d'erreur : la sortie standard est réservée au protocole.
"""

import logging
import re
import unicodedata
from functools import lru_cache
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from app import config
from app.db import connexion, nombre_passages
from app.decoupage import charger_corpus
from app.ingestion import ingerer
from app.recherche import rechercher

log = logging.getLogger("rag-copropriete.mcp")

AVERTISSEMENT = ("Textes officiels cités tels quels (loi du 10 juillet 1965, décret du 17 mars 1967, version "
                 "consolidée) : ce n'est pas un conseil juridique. Vérifiez l'article cité.")
TAILLE_EXTRAIT = 700

VERSION = "0.1.0"

# Les deux outils ne modifient rien chez l'utilisateur (la première recherche charge le corpus dans la base locale, une
# seule fois) et ne sortent pas du corpus versionné.
LECTURE_SEULE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

serveur = MCPServer(
    "copropriete-textes",
    version=VERSION,
    instructions=(
        "Recherche dans le droit français de la copropriété : loi n° 65-557 du 10 juillet 1965 et décret n° 67-223 "
        "du 17 mars 1967, versions consolidées (données ouvertes DILA). Utilise `rechercher_articles` pour trouver "
        "les articles qui répondent à une question, puis `lire_article` pour lire un article en entier avant de le "
        "citer. Si `je_ne_sais_pas` vaut true, dis que ces textes ne semblent pas répondre au lieu d'inventer. "
        "Cite toujours l'article et son lien. Ce n'est pas un conseil juridique."
    ),
)


def _reference(texte_id: str, article_num: str) -> str:
    return f"{texte_id} art. {article_num}"


def _extrait(contenu: str) -> str:
    return contenu if len(contenu) <= TAILLE_EXTRAIT else contenu[:TAILLE_EXTRAIT].rsplit(" ", 1)[0] + " […]"


@serveur.tool(annotations=LECTURE_SEULE)
def rechercher_articles(
    question: Annotated[str, Field(min_length=3, max_length=1000,
                                   description="Question en français, par exemple « quelle majorité faut-il "
                                               "pour modifier le règlement de copropriété ? »")],
    k: Annotated[int, Field(ge=1, le=10, description="Nombre d'articles à renvoyer")] = 5,
) -> dict[str, Any]:
    """Cherche dans la loi de 1965 et le décret de 1967 les articles qui répondent à une question de copropriété.

    Renvoie les k articles les plus pertinents (référence, extrait, lien Légifrance, scores), ou un refus explicite
    (`je_ne_sais_pas: true`, aucun article) si la question semble hors de ces textes. `similarite` est la similarité
    cosinus avec la question ; `pertinence` est le score du reclasseur (plus haut = plus pertinent).
    """
    with connexion() as conn:
        if nombre_passages(conn) == 0:
            # Premier lancement : le corpus est chargé en quelques secondes (vecteurs précalculés).
            log.info("Base vide : ingestion du corpus")
            ingerer(conn)
        r = rechercher(conn, question, k=k)
    if r.je_ne_sais_pas:
        return {
            "je_ne_sais_pas": True,
            "message": ("Ces textes ne semblent pas répondre à cette question (meilleure similarité "
                        f"{r.meilleure_similarite} sous le seuil {r.seuil}). Ne pas répondre à partir d'eux."),
            "meilleure_similarite": r.meilleure_similarite,
            "seuil": r.seuil,
            "articles": [],
            "avertissement": AVERTISSEMENT,
        }
    return {
        "je_ne_sais_pas": False,
        "meilleure_similarite": r.meilleure_similarite,
        "seuil": r.seuil,
        "articles": [
            {
                "reference": _reference(p.texte_id, p.article_num),
                "texte": p.texte_titre,
                "article": p.article_num,
                "plan": p.chemin,
                "extrait": _extrait(p.contenu),
                "lien_legifrance": p.url,
                "score_fusion": p.score,
                "similarite": p.similarite,
                "pertinence": p.pertinence,
                "cite_dans_la_question": p.cite_dans_la_question,
            }
            for p in r.passages
        ],
        "avertissement": AVERTISSEMENT,
    }


@lru_cache(maxsize=1)
def _corpus() -> dict[str, dict]:
    return {doc["id"]: doc for doc in charger_corpus(config.DOSSIER_CORPUS)}


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


SUFFIXE = r"(?:\s?(?:aa|a|bis|b)\b)?"
MOTIF_APRES_ARTICLE = re.compile(r"\bart(?:icles?|\.)?\s*(\d+(?:-\d+)*" + SUFFIXE + ")")
MOTIF_NUMERO = re.compile(r"(?:^|[^\w-])(\d+(?:-\d+)*" + SUFFIXE + r")\s*$")


def analyser_reference(ref: str) -> tuple[str | None, str]:
    """« loi-1965 art. 25 » -> ("loi-1965", "25") ; « décret 1967, article 9 bis » -> ("decret-1967", "9 bis") ;
    « 17-1A » -> (None, "17-1 A") ; « annexe 2 du décret » -> ("decret-1967", "Annexe 2")."""
    simple = _sans_accents(ref).lower().strip().rstrip(".")
    texte = "decret-1967" if re.search(r"decret|1967", simple) else "loi-1965" if re.search(r"\bloi\b|1965", simple) \
        else None
    annexe = re.search(r"annexe\s*(\d+)", simple)
    if annexe:
        return texte, f"Annexe {annexe.group(1)}"
    # Le numéro qui suit « art. » ou « article » ; à défaut, on retire le nom du texte et les années et on prend le
    # numéro écrit à la fin (« loi-1965 25 », « 17-1A »).
    trouve = MOTIF_APRES_ARTICLE.search(simple)
    if not trouve:
        reste = re.sub(r"(loi|decret)(-|\s+)?(n°\s*)?(65-557|67-223)?|\b(19)?(65|67)\b|du \d+ \w+ \d{4}", " ", simple)
        trouve = MOTIF_NUMERO.search(reste.replace(",", " ").strip())
    if not trouve:
        raise ToolError(f"Référence illisible : « {ref} ». Exemple : « loi-1965 art. 25 » ou "
                        "« decret-1967 art. 9 bis ».")
    num = re.sub(r"(\d)\s?(aa|a|b)$", lambda m: f"{m.group(1)} {m.group(2).upper()}", trouve.group(1).strip())
    num = re.sub(r"(\d)\s?bis$", r"\1 bis", num)
    return texte, num


@serveur.tool(annotations=LECTURE_SEULE)
def lire_article(
    reference: Annotated[str, Field(min_length=1, max_length=100,
                                    description="Référence d'un article, par exemple « loi-1965 art. 25 » (forme "
                                                "renvoyée par rechercher_articles) ou « décret 1967 article 9 bis »")],
) -> dict[str, Any]:
    """Renvoie le texte officiel complet d'un article de la loi du 10 juillet 1965 ou du décret du 17 mars 1967,
    avec son plan, son lien Légifrance et la date de consolidation du corpus."""
    texte_id, num = analyser_reference(reference)
    corpus = _corpus()
    candidats = [(tid, a) for tid, doc in corpus.items() if texte_id in (None, tid)
                 for a in doc["articles"] if a["num"] == num]
    if not candidats:
        raise ToolError(f"Article introuvable : {reference!r} (lu comme {texte_id or 'loi ou décret'}, "
                        f"article {num}). Vérifiez la référence ou utilisez rechercher_articles.")
    if len(candidats) > 1:
        refs = " ; ".join(_reference(tid, a["num"]) for tid, a in candidats)
        raise ToolError(f"Référence ambiguë : l'article {num} existe dans plusieurs textes ({refs}). "
                        "Précisez loi-1965 ou decret-1967.")
    tid, article = candidats[0]
    doc = corpus[tid]
    return {
        "reference": _reference(tid, article["num"]),
        "texte": doc["titre_court"],
        "titre_complet": doc["titre"],
        "article": article["num"],
        "plan": article.get("chemin", ""),
        "texte_officiel": article["texte"],
        "lien_legifrance": article["url"],
        "en_vigueur_depuis": article.get("date_debut"),
        "date_consolidation": doc["date_consolidation"],
        "source": doc["source_donnees"],
        "licence": doc["licence"],
        "avertissement": AVERTISSEMENT,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    serveur.run()


if __name__ == "__main__":
    main()
