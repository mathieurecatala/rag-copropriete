"""Lexique de reformulation, questions de majorité et lecture point par point par le reclasseur."""

import re

from app import config
from app.ingestion import ingerer
from app.lexique import reformuler
from app.recherche import question_de_majorite, rechercher, segments
from tests.conftest import CORPUS_TEST


def test_reformuler_ajoute_le_vocabulaire_de_la_loi():
    q = "Quelle majorité faut-il pour changer de syndic ?"
    assert reformuler(q) == f"{q} (désignation ou révocation du syndic)"
    assert "parties communes" in reformuler("Puis-je poser une fenêtre de toit ?")
    assert "mise en demeure" in reformuler("Que faire si un voisin ne paie pas ses charges ?")


def test_reformuler_laisse_les_autres_questions():
    q = "Combien de temps avant l'assemblée faut-il convoquer ?"
    assert reformuler(q) == q


def test_reformuler_desactivable(monkeypatch):
    monkeypatch.setattr(config, "LEXIQUE", False)
    q = "Quelle majorité pour changer de syndic ?"
    assert reformuler(q) == q


def test_question_de_majorite():
    assert question_de_majorite("Quelle majorité faut-il pour modifier le règlement ?")
    assert question_de_majorite("Faut-il l'accord de l'assemblée pour poser une fenêtre de toit ?")
    assert question_de_majorite("Peut-on voter par correspondance ?")
    assert not question_de_majorite("Qui paie l'ascenseur ?")
    assert not question_de_majorite("Que dit le devis ?")


def test_segments_d_une_enumeration():
    chapeau = "Ne sont adoptées qu'à la majorité des voix de tous les copropriétaires les décisions concernant :"
    texte = f"{chapeau}\na) Toute délégation du pouvoir ;\nb) L'autorisation de travaux ;\nc) La désignation du syndic ;"
    morceaux = segments(texte, chapeau)
    assert len(morceaux) == 3
    assert all(m.startswith(chapeau) for m in morceaux)
    assert morceaux[2].endswith("c) La désignation du syndic ;")


def test_segments_d_un_morceau_suivant_reprend_le_chapeau():
    chapeau = "Sont prises à la majorité … les décisions concernant :"
    texte = "f) Les travaux d'économies d'énergie ;\ng) Les modalités d'ouverture des portes ;"
    assert segments(texte, chapeau) == [f"{chapeau}\nf) Les travaux d'économies d'énergie ;",
                                        f"{chapeau}\ng) Les modalités d'ouverture des portes ;"]


def test_segments_sans_enumeration():
    texte = "Le syndicat a qualité pour agir en justice.\nIl peut notamment agir."
    assert segments(texte) == [texte]


def test_seuil_calcule_sur_la_question_d_origine(conn):
    ingerer(conn, CORPUS_TEST)
    q = "Quelle majorité faut-il en assemblée générale pour changer de syndic ?"
    avec = rechercher(conn, q, k=3)
    import app.config as c
    ancien = c.LEXIQUE
    c.LEXIQUE = False
    try:
        sans = rechercher(conn, q, k=3)
    finally:
        c.LEXIQUE = ancien
    assert avec.meilleure_similarite == sans.meilleure_similarite


def test_question_de_majorite_fait_entrer_l_article_25(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "Quelle majorité faut-il en assemblée générale pour changer de syndic ?", k=3)
    assert ("loi-1965", "25") in {(p.texte_id, p.article_num) for p in r.passages}


def _articles_lus_par_le_reclasseur(conn, monkeypatch, majorites: bool) -> set[str]:
    """Articles que le reclasseur a notés, avec un seul candidat issu de la fusion : le petit corpus de test (6
    articles de loi) ferait sinon entrer l'article 25 de toute façon."""
    from app import reclasseur as module

    lus: set[str] = set()
    vrai = module.reclasseur()

    class Espion:
        def scores(self, question, textes):
            lus.update(re.search(r", article (.+?)\. ", t).group(1) for t in textes)
            return vrai.scores(question, textes)

    monkeypatch.setattr("app.recherche.reclasseur", lambda: Espion())
    monkeypatch.setattr(config, "RECLASSEUR_CANDIDATS", 1)
    monkeypatch.setattr(config, "MAJORITES", majorites)
    rechercher(conn, "Quelle majorité faut-il pour voter des travaux ?", k=3)
    return lus


def test_regle_majorites_ajoute_les_articles_24_25_26(conn, monkeypatch):
    ingerer(conn, CORPUS_TEST)
    sans = _articles_lus_par_le_reclasseur(conn, monkeypatch, majorites=False)
    avec = _articles_lus_par_le_reclasseur(conn, monkeypatch, majorites=True)
    assert len(sans) == 1
    assert {"24", "25", "26"} <= avec
