"""Réponse rédigée par l'API Claude, seulement si ANTHROPIC_API_KEY est présente au lancement.

Claude ne reçoit que les passages trouvés ; il doit citer les articles et dire quand les passages
ne répondent pas. Sans clé, ou en cas d'erreur, l'API renvoie les passages seuls.
"""

import logging

from app import config
from app.recherche import Resultat

log = logging.getLogger(__name__)

CONSIGNE = """Tu aides un syndic de copropriété à répondre à une question à partir des textes officiels \
fournis (loi du 10 juillet 1965, décret du 17 mars 1967). Règles :
- Réponds en français, en quelques phrases claires, uniquement à partir des passages fournis.
- Cite chaque affirmation avec son article, par exemple « d'après l'article 25 de la loi du 10 juillet 1965 ».
- Si les passages ne permettent pas de répondre, dis-le simplement : « Les textes fournis ne répondent pas \
à cette question. » N'utilise pas d'autre connaissance.
- Tu cites des textes, tu ne donnes pas de conseil juridique ; ne termine pas par un avertissement, \
l'interface l'affiche déjà."""


def generation_active() -> bool:
    return config.ANTHROPIC_API_KEY is not None


def _contexte(passages: list[Resultat]) -> str:
    blocs = []
    for n, p in enumerate(passages, 1):
        blocs.append(f"[{n}] {p.texte_titre}, article {p.article_num} ({p.chemin})\n{p.contenu}")
    return "\n\n".join(blocs)


def rediger(question: str, passages: list[Resultat]) -> str | None:
    if not generation_active() or not passages:
        return None
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model=config.MODELE_CLAUDE,
            max_tokens=2000,
            system=CONSIGNE,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": f"Passages :\n\n{_contexte(passages)}\n\nQuestion : {question}",
                }
            ],
        )
    except anthropic.APIError as erreur:
        log.warning("Génération indisponible : %s", erreur)
        return None
    if message.stop_reason == "refusal":
        return None
    texte = "".join(b.text for b in message.content if b.type == "text").strip()
    return texte or None
