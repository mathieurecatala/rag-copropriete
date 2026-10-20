"""Les jeux d'évaluation sont cohérents avec le corpus, et les mesures sont bien calculées."""

import json
from pathlib import Path

import pytest

from eval.evaluer import JEUX, mesures, rang_attendu, reculs

RACINE = Path(__file__).resolve().parent.parent


def _corpus_complet() -> dict[str, set[str]]:
    return {f.stem: {a["num"] for a in json.loads(f.read_text(encoding="utf-8"))["articles"]}
            for f in (RACINE / "corpus" / "donnees").glob("*.json")}


@pytest.mark.parametrize("cle", list(JEUX))
def test_articles_attendus_existent(cle):
    jeu = json.loads((RACINE / JEUX[cle][0]).read_text(encoding="utf-8"))
    corpus = _corpus_complet()
    assert jeu["questions"] and jeu["hors_sujet"]
    for q in jeu["questions"]:
        assert q["attendu"], q["question"]
        for a in q["attendu"]:
            assert a["article"] in corpus[a["texte"]], (q["question"], a)


def test_jeux_sans_question_commune():
    textes = [{q["question"] for q in json.loads((RACINE / chemin).read_text(encoding="utf-8"))["questions"]}
              for chemin, _ in JEUX.values()]
    assert not textes[0] & textes[1]


def test_jeu_de_controle_assez_grand():
    jeu = json.loads((RACINE / JEUX["controle"][0]).read_text(encoding="utf-8"))
    assert len(jeu["questions"]) >= 30
    assert "pas par un juriste" in jeu["note"]


def test_mesures():
    assert mesures([1, 2, None, 5]) == {"hit@1": 0.25, "hit@3": 0.5, "mrr@10": round((1 + 0.5 + 0.2) / 4, 3)}


def test_rang_attendu():
    class P:
        def __init__(self, t, n):
            self.texte_id, self.article_num = t, n

    resultats = [P("loi-1965", "24"), P("decret-1967", "9"), P("loi-1965", "25")]
    assert rang_attendu(resultats, [{"texte": "loi-1965", "article": "25"}]) == 3
    assert rang_attendu(resultats, [{"texte": "loi-1965", "article": "9"}]) is None


def _resultat(hit3: float, refus: float = 0.7, tort: float = 0.0) -> dict:
    return {"modes": {"hybride": {"hit@1": 0.5, "hit@3": hit3, "mrr@10": 0.6}},
            "refus_hors_sujet": refus, "refus_a_tort": tort}


def test_reculs():
    assert reculs(_resultat(0.9), _resultat(0.9)) == []
    assert reculs(_resultat(0.9), _resultat(0.95)) == []
    assert reculs(_resultat(0.9), _resultat(0.88)) == ["hit@3 0.9 -> 0.88"]
    assert reculs(_resultat(0.9), _resultat(0.9, refus=0.6)) == ["hors sujet refusées 0.7 -> 0.6"]
    assert reculs(_resultat(0.9), _resultat(0.9, tort=0.02)) == ["refus à tort 0.0 -> 0.02"]
