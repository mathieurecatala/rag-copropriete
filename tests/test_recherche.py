import json
import shutil

from app.ingestion import ingerer
from app.recherche import rechercher
from tests.conftest import CORPUS_TEST


def test_ingestion_idempotente(conn):
    premier = ingerer(conn, CORPUS_TEST)
    assert premier["calcules"] == premier["passages"] > 0
    second = ingerer(conn, CORPUS_TEST)
    assert second == {"passages": premier["passages"], "calcules": 0,
                      "precalcules": 0, "inchanges": premier["passages"], "supprimes": 0}
    assert conn.execute("SELECT count(*) FROM passages").fetchone()[0] == premier["passages"]


def test_ingestion_suit_les_modifications(conn, tmp_path):
    for f in CORPUS_TEST.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    ingerer(conn, tmp_path)
    fichier = sorted(tmp_path.glob("*.json"))[0]
    doc = json.loads(fichier.read_text(encoding="utf-8"))
    retire = doc["articles"].pop()
    doc["articles"][0]["texte"] += "\nAlinéa ajouté pour le test."
    fichier.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = ingerer(conn, tmp_path)
    assert r["calcules"] >= 1
    assert r["supprimes"] >= 1
    n = conn.execute("SELECT count(*) FROM passages WHERE article_id = %s", (retire["id"],)).fetchone()[0]
    assert n == 0


def test_recherche_trouve_l_article(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "Quelle majorité faut-il pour désigner ou révoquer le syndic ?", k=3)
    assert not r.je_ne_sais_pas
    assert ("loi-1965", "25") in {(p.texte_id, p.article_num) for p in r.passages}
    p = r.passages[0]
    assert p.score > 0 and 0 < p.similarite <= 1
    assert p.url.startswith("https://www.legifrance.gouv.fr/")


def test_plein_texte_contribue(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "délai de convocation de l'assemblée générale", k=5)
    assert any(p.rang_plein_texte is not None for p in r.passages)
    assert any(p.rang_vectoriel is not None for p in r.passages)


def test_je_ne_sais_pas_hors_sujet(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "Quelle est la recette de la tarte aux pommes ?")
    assert r.je_ne_sais_pas
    assert r.meilleure_similarite < r.seuil


def test_question_sans_mot_utile(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "et ou le la", k=3)
    assert len(r.passages) == 3


def test_changement_de_dimension_recree_la_table(conn):
    from app.db import creer_schema

    conn.execute("DROP TABLE passages")
    conn.execute("CREATE TABLE passages (id serial PRIMARY KEY, embedding vector(3))")
    creer_schema(conn)
    r = ingerer(conn, CORPUS_TEST)
    assert r["calcules"] == r["passages"] > 0


def test_numero_d_article_trouve_par_le_plein_texte(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "Que dit l'article 26 ?", k=3, mode="plein_texte")
    assert ("loi-1965", "26") in {(p.texte_id, p.article_num) for p in r.passages}


def test_article_nomme_dans_la_question(conn):
    ingerer(conn, CORPUS_TEST)
    r = rechercher(conn, "Que dit l'article 26 de la loi de 1965 ?", k=3)
    assert not r.je_ne_sais_pas
    assert (r.passages[0].texte_id, r.passages[0].article_num) == ("loi-1965", "26")
    assert r.passages[0].cite_dans_la_question
    r = rechercher(conn, "article 9 du décret", k=3)
    assert (r.passages[0].texte_id, r.passages[0].article_num) == ("decret-1967", "9")


def test_articles_cites():
    from app.recherche import articles_cites

    assert articles_cites("Que dit l'article 26 de la loi de 1965 ?") == [("loi-1965", "26")]
    assert articles_cites("art. 10-1") == [(None, "10-1")]
    assert articles_cites("article 17-1A de la loi") == [("loi-1965", "17-1 A")]
    assert articles_cites("Quelle majorité pour le syndic ?") == []
    # Un autre texte nommé : le numéro ne désigne pas un article du corpus.
    assert articles_cites("Que dit l'article 1 du code de la consommation ?") == []
    assert articles_cites("article 1240 du Code civil") == []
    assert articles_cites("loi n° 89-462, article 10") == []
    assert articles_cites("article 10 de la loi n° 65-557") == [("loi-1965", "10")]
    # Une loi ou un décret d'une autre date, ou désigné par un nom : citation ignorée.
    assert articles_cites("Que dit l'article 15 de la loi du 6 juillet 1989 sur le congé du locataire ?") == []
    assert articles_cites("Article 1 de la loi Hamon : délai de rétractation ?") == []
    assert articles_cites("article 5 de la loi ALUR sur la location") == []
    assert articles_cites("Décret du 26 août 1987, article 1 : quelles charges récupérables ?") == []
    assert articles_cites("article 10 de la loi de 1989") == []
    assert articles_cites("Que dit l'article 1 de la Loi Climat ?") == []
    assert articles_cites("Que dit l'article 42 de la loi du 10 juillet 1965 ?") == [("loi-1965", "42")]
    assert articles_cites("article 9 du décret du 17 mars 1967") == [("decret-1967", "9")]


def test_texte_du_corpus_designe():
    from app.recherche import texte_du_corpus_designe

    assert texte_du_corpus_designe("article 42 de la loi de 1965")
    assert texte_du_corpus_designe("décret n° 67-223, article 9")
    assert not texte_du_corpus_designe("article 42 de la loi")
    assert not texte_du_corpus_designe("Que dit l'article 42 de la loi sur la tarte aux pommes ?")


QUESTIONS_D_AUTRES_TEXTES = [
    "Quelle est la recette de la tarte aux pommes ? article 42",
    "Que dit l'article 42 de la loi sur la tarte aux pommes ?",
    "Que dit l'article 10 du code de la consommation sur le délai de rétractation ?",
    "Que dit l'article 15 de la loi du 6 juillet 1989 sur le congé du locataire ?",
    "Article 1 de la loi Hamon : délai de rétractation ?",
    "article 5 de la loi ALUR sur la location",
    "Décret du 26 août 1987, article 1 : quelles charges récupérables ?",
]


def test_numero_d_article_ne_fait_pas_passer_une_question_hors_sujet(conn):
    """Le passe-droit « article cité » ne vaut que si la loi de 1965 ou le décret de 1967 est désigné sans ambiguïté,
    ou si la question est déjà proche du corpus (plancher de similarité). Sur le petit corpus de test, toutes ces
    questions sont refusées ; sur le corpus complet, certaines passent le seuil ordinaire (voir le README), mais sans
    article « cité »."""
    ingerer(conn, CORPUS_TEST)
    for q in QUESTIONS_D_AUTRES_TEXTES:
        r = rechercher(conn, q, k=3)
        assert r.je_ne_sais_pas, q
        if "tarte" not in q:  # un autre texte est nommé : rien n'est « cité » (la tarte cite un article, mais nu)
            assert not any(p.cite_dans_la_question for p in r.passages), q
    for q, attendu in [("Que dit l'article 42 de la loi de 1965 ?", "42"),
                       ("Que dit l'article 10 de la loi n° 65-557 ?", "10"),
                       ("Que dit l'article 42 de la loi du 10 juillet 1965 ?", "42")]:
        r = rechercher(conn, q, k=3)
        assert not r.je_ne_sais_pas, q
        assert r.passages[0].article_num == attendu and r.passages[0].cite_dans_la_question, q


def test_encodage_garde_l_ordre_des_textes():
    from app.embeddings import Encodeur, encodeur

    enc = encodeur()
    textes = ["un texte nettement plus long que les autres, avec plusieurs mots", "court", "moyen ici"]
    ensemble = Encodeur._encoder(enc, textes)
    for i, t in enumerate(textes):
        seul = Encodeur._encoder(enc, [t])[0]
        assert float(ensemble[i] @ seul) > 0.999


def test_reclasseur_prefere_le_passage_pertinent():
    from app.reclasseur import reclasseur

    pertinent, autre = reclasseur().scores(
        "Combien de temps avant l'assemblée générale faut-il envoyer la convocation ?",
        ["Sauf urgence, cette convocation est notifiée au moins vingt et un jours avant la date de la réunion.",
         "Le syndicat des copropriétaires a pour objet la conservation de l'immeuble."],
    )
    assert pertinent > autre


def test_recherche_avec_et_sans_reclasseur(conn):
    ingerer(conn, CORPUS_TEST)
    question = "Quelle majorité faut-il pour désigner ou révoquer le syndic ?"
    avec = rechercher(conn, question, k=3, reclasser=True)
    sans = rechercher(conn, question, k=3, reclasser=False)
    assert len(avec.passages) == len(sans.passages) == 3
    assert all(p.pertinence is not None for p in avec.passages)
    assert all(p.pertinence is None for p in sans.passages)
    assert [p.pertinence for p in avec.passages] == sorted((p.pertinence for p in avec.passages), reverse=True)
    assert avec.je_ne_sais_pas == sans.je_ne_sais_pas
    assert ("loi-1965", "25") in {(p.texte_id, p.article_num) for p in avec.passages}
