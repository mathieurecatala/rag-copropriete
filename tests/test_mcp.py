"""Serveur MCP : les deux outils, appelés par le client du SDK officiel, en mémoire puis par stdio."""

import os
import sys

import anyio
import pytest
from mcp import Client, StdioServerParameters

from app.ingestion import ingerer
from app.serveur_mcp import VERSION, analyser_reference, serveur
from tests.conftest import CORPUS_TEST

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _appeler(cible, outil: str, arguments: dict):
    async with Client(cible) as client:
        return await client.call_tool(outil, arguments)


def appeler(outil: str, arguments: dict):
    return anyio.run(_appeler, serveur, outil, arguments)


def test_liste_des_outils():
    async def lister():
        async with Client(serveur) as client:
            return (await client.list_tools()).tools

    outils = {t.name: t for t in anyio.run(lister)}
    assert set(outils) == {"rechercher_articles", "lire_article"}
    proprietes = outils["rechercher_articles"].input_schema["properties"]
    assert proprietes["k"]["maximum"] == 10 and proprietes["k"]["default"] == 5
    assert outils["lire_article"].input_schema["required"] == ["reference"]
    for outil in outils.values():
        assert outil.annotations.read_only_hint is True and outil.annotations.open_world_hint is False


def test_rechercher_articles(conn):
    ingerer(conn, CORPUS_TEST)
    r = appeler("rechercher_articles", {"question": "Quelle majorité faut-il pour désigner le syndic ?", "k": 3})
    assert not r.is_error
    resultat = r.structured_content
    assert resultat["je_ne_sais_pas"] is False
    assert len(resultat["articles"]) == 3
    premier = resultat["articles"][0]
    assert premier["lien_legifrance"].startswith("https://www.legifrance.gouv.fr/")
    assert premier["reference"].endswith(f" art. {premier['article']}")
    assert "loi-1965 art. 25" in {a["reference"] for a in resultat["articles"]}
    assert "pas un conseil juridique" in resultat["avertissement"]


def test_rechercher_articles_refuse_hors_sujet(conn):
    ingerer(conn, CORPUS_TEST)
    r = appeler("rechercher_articles", {"question": "Quelle est la recette de la tarte aux pommes ?"})
    assert not r.is_error
    assert r.structured_content["je_ne_sais_pas"] is True
    assert r.structured_content["articles"] == []
    assert "ne semblent pas répondre" in r.structured_content["message"]


def test_rechercher_articles_ingere_si_base_vide(conn):
    r = appeler("rechercher_articles", {"question": "Quelle majorité pour modifier le règlement de copropriété ?"})
    assert not r.is_error and r.structured_content["articles"]


def test_rechercher_articles_valide_k():
    r = appeler("rechercher_articles", {"question": "syndic", "k": 50})
    assert r.is_error


def test_lire_article():
    r = appeler("lire_article", {"reference": "loi-1965 art. 25"})
    assert not r.is_error
    a = r.structured_content
    assert a["reference"] == "loi-1965 art. 25"
    assert a["texte_officiel"].startswith("Ne sont adoptées qu'à la majorité des voix de tous les copropriétaires")
    assert a["lien_legifrance"].startswith("https://www.legifrance.gouv.fr/")
    assert "Licence Ouverte" in a["licence"]


def test_lire_article_reference_ambigue_ou_absente(monkeypatch):
    import app.serveur_mcp as module

    # Le petit corpus de test n'a aucun numéro commun aux deux textes : on en simule un (article 10 aussi au décret).
    vrai = module._corpus()
    loi10 = next(a for a in vrai["loi-1965"]["articles"] if a["num"] == "10")
    double = {**vrai, "decret-1967": {**vrai["decret-1967"], "articles": vrai["decret-1967"]["articles"] + [loi10]}}
    monkeypatch.setattr(module, "_corpus", lambda: double)
    ambigu = appeler("lire_article", {"reference": "article 10"})
    assert ambigu.is_error and "ambiguë" in ambigu.content[0].text
    absent = appeler("lire_article", {"reference": "loi-1965 art. 999"})
    assert absent.is_error and "introuvable" in absent.content[0].text


@pytest.mark.parametrize("reference, attendu", [
    ("loi-1965 art. 25", ("loi-1965", "25")),
    ("Loi du 10 juillet 1965, article 25-1", ("loi-1965", "25-1")),
    ("décret 1967 article 9 bis", ("decret-1967", "9 bis")),
    ("decret-1967 art. 9 bis", ("decret-1967", "9 bis")),
    ("article 17-1A de la loi", ("loi-1965", "17-1 A")),
    ("loi-1965 art. 17-1 AA", ("loi-1965", "17-1 AA")),
    ("art. 10-1", (None, "10-1")),
    ("annexe 2 du décret", ("decret-1967", "Annexe 2")),
    ("décret n° 67-223 du 17 mars 1967, art. 55", ("decret-1967", "55")),
])
def test_analyser_reference(reference, attendu):
    assert analyser_reference(reference) == attendu


def test_par_stdio():
    """Le serveur lancé comme un vrai processus (`python -m app.serveur_mcp`), comme le ferait Claude Desktop."""
    parametres = StdioServerParameters(command=sys.executable, args=["-m", "app.serveur_mcp"], cwd=RACINE,
                                       env=dict(os.environ))

    async def scenario():
        async with Client(parametres) as client:
            noms = {t.name for t in (await client.list_tools()).tools}
            version = client.server_info.version
            article = await client.call_tool("lire_article", {"reference": "décret 1967 article 9"})
            return noms, version, article

    noms, version, article = anyio.run(scenario)
    assert noms == {"rechercher_articles", "lire_article"}
    assert version == VERSION
    assert not article.is_error
    assert article.structured_content["reference"] == "decret-1967 art. 9"
