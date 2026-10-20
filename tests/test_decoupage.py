from app.decoupage import charger_corpus, decouper_texte, passages_du_texte
from tests.conftest import CORPUS_TEST


def test_article_court_un_seul_morceau():
    assert decouper_texte("Premier alinéa.\nSecond alinéa.", taille_max=1000) == [
        "Premier alinéa.\nSecond alinéa."
    ]


def test_article_long_coupe_sans_perte():
    paragraphes = [f"Alinéa {i} : " + "mot " * 60 + "fin." for i in range(12)]
    texte = "\n".join(paragraphes)
    morceaux = decouper_texte(texte, taille_max=800)
    assert len(morceaux) > 1
    assert all(len(m) <= 800 for m in morceaux)
    # Le texte officiel n'est jamais modifié : les morceaux recollés redonnent l'article.
    assert "\n".join(morceaux).split() == texte.split()


def test_paragraphe_trop_long_coupe_entre_phrases():
    paragraphe = " ".join(f"Phrase numéro {i} qui dit quelque chose." for i in range(80))
    morceaux = decouper_texte(paragraphe, taille_max=500)
    assert len(morceaux) > 1
    assert all(len(m) <= 500 for m in morceaux)
    assert all(m.endswith(".") for m in morceaux)
    assert " ".join(morceaux).split() == paragraphe.split()


def test_passages_du_corpus_de_test():
    documents = charger_corpus(CORPUS_TEST)
    assert documents
    passages = [p for d in documents for p in passages_du_texte(d)]
    assert len({(p.article_id, p.morceau) for p in passages}) == len(passages)
    for p in passages:
        assert p.url.startswith("https://www.legifrance.gouv.fr/")
        assert f"article {p.article_num}" in p.a_indexer
        assert len(p.empreinte) == 64
