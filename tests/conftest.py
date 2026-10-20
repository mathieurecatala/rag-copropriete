"""Les tests tournent sur une base dédiée (syndic_test) et un petit corpus d'articles officiels."""

import os
from pathlib import Path

CORPUS_TEST = Path(__file__).parent / "corpus_test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://syndic:syndic@localhost:5432/syndic_test"
)
os.environ["DOSSIER_CORPUS"] = str(CORPUS_TEST)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["INGESTION_AU_DEMARRAGE"] = "0"
# Les tests calculent les vecteurs avec le modèle ; le fichier précalculé est testé à part (test_vecteurs.py).
os.environ["FICHIER_VECTEURS"] = ""

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.db import connexion, creer_schema  # noqa: E402
from app.embeddings import encodeur  # noqa: E402

# Les tests réingèrent souvent le même petit corpus : on garde ses vecteurs en mémoire pour la session
# (le modèle réel reste utilisé, une seule fois par texte).
_enc = encodeur()
_passages_sans_memo = _enc.passages
_memo: dict[str, np.ndarray] = {}


def _passages_memo(textes: list[str]) -> np.ndarray:
    manquants = [t for t in dict.fromkeys(textes) if t not in _memo]
    if manquants:
        _memo.update(zip(manquants, _passages_sans_memo(manquants)))
    return np.array([_memo[t] for t in textes])


_enc.passages = _passages_memo


@pytest.fixture
def conn():
    with connexion() as c:
        creer_schema(c)
        c.execute("TRUNCATE passages RESTART IDENTITY")
        yield c
