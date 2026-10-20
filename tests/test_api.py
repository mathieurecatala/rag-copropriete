from fastapi.testclient import TestClient

from app import generation
from app.main import app

client = TestClient(app)


def test_page_web():
    r = client.get("/")
    assert r.status_code == 200
    assert "Textes de la copropriété" in r.text
    assert "pas un conseil juridique" in r.text


def test_question_avant_ingestion(conn):
    r = client.post("/question", json={"question": "Quelle majorité pour désigner le syndic ?"})
    assert r.status_code == 503


def test_ingestion_puis_question(conn):
    r = client.post("/ingestion")
    assert r.status_code == 200
    assert r.json()["passages"] > 0

    sante = client.get("/sante").json()
    assert sante["passages"] == r.json()["passages"]
    assert sante["generation"] is False

    r = client.post("/question", json={"question": "Quelle majorité faut-il pour désigner le syndic ?", "k": 3})
    assert r.status_code == 200
    d = r.json()
    assert d["je_ne_sais_pas"] is False
    assert d["reponse"] is None  # sans clé API : passages seuls
    assert len(d["passages"]) == 3
    for champ in ("article_num", "contenu", "url", "score", "similarite", "texte_titre"):
        assert champ in d["passages"][0]


def test_question_hors_sujet(conn):
    client.post("/ingestion")
    d = client.post("/question", json={"question": "Quelle est la recette de la tarte aux pommes ?"}).json()
    assert d["je_ne_sais_pas"] is True
    assert d["reponse"] is None


def test_question_invalide():
    assert client.post("/question", json={"question": "a"}).status_code == 422
    assert client.post("/question", json={}).status_code == 422


def test_sans_cle_pas_de_generation():
    assert generation.generation_active() is False
    assert generation.rediger("question", []) is None
