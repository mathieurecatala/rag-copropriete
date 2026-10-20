from types import SimpleNamespace

import anthropic

from app import config, generation
from app.recherche import Resultat

PASSAGE = Resultat("loi-1965", "Loi du 10 juillet 1965", "LEGIARTI0000", "25", "Chapitre II", 0,
                   "c) La désignation ou la révocation du ou des syndics ;", "https://www.legifrance.gouv.fr/x",
                   0.03, 0.7, 1, 1)


class FauxClient:
    appels: list = []

    def __init__(self, api_key):
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        FauxClient.appels.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text="D'après l'article 25 de la loi…")])


def test_generation_avec_cle(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "cle-de-test")
    monkeypatch.setattr(anthropic, "Anthropic", FauxClient)
    reponse = generation.rediger("Quelle majorité pour désigner le syndic ?", [PASSAGE])
    assert reponse == "D'après l'article 25 de la loi…"
    appel = FauxClient.appels[-1]
    assert appel["model"] == "claude-haiku-5-5"
    assert "article 25" in appel["messages"][0]["content"]
    assert "désignation ou la révocation" in appel["messages"][0]["content"]
    assert "ne répondent pas" in appel["system"]


def test_generation_refus(monkeypatch):
    class Refus(FauxClient):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "cle-de-test")
    monkeypatch.setattr(anthropic, "Anthropic", Refus)
    assert generation.rediger("question", [PASSAGE]) is None
