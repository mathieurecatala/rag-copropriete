"""Vecteurs précalculés du corpus livré (corpus/vecteurs/bge-m3.npz) : à jour et identiques à ceux du modèle."""

import numpy as np

from app import config
from app.decoupage import charger_corpus, passages_du_texte
from app.embeddings import encodeur
from app.ingestion import charger_vecteurs, ingerer
from tests.conftest import CORPUS_TEST

FICHIER = config.RACINE / "corpus" / "vecteurs" / "bge-m3.npz"
CORPUS = config.RACINE / "corpus" / "donnees"


def _passages(dossier):
    return [p for doc in charger_corpus(dossier) for p in passages_du_texte(doc)]


def test_fichier_couvre_tout_le_corpus():
    # Échoue si le corpus ou le découpage change sans régénérer le fichier (python -m app.ingestion --precalculer).
    vecteurs = charger_vecteurs(FICHIER)
    manquants = [p.article_id for p in _passages(CORPUS) if p.empreinte not in vecteurs]
    assert not manquants


def test_vecteurs_identiques_au_modele():
    vecteurs = charger_vecteurs(FICHIER)
    communs = [p for p in _passages(CORPUS_TEST) if p.empreinte in vecteurs]
    assert len(communs) >= 5
    calcules = encodeur().passages([p.a_indexer for p in communs])
    stockes = np.array([vecteurs[p.empreinte] for p in communs])
    assert np.min(np.sum(calcules * stockes, axis=1)) > 0.999


def test_autre_modele_ignore(tmp_path):
    fichier = tmp_path / "v.npz"
    np.savez(fichier, signature=np.array("autre-modele"), empreintes=np.array(["x"]), vecteurs=np.zeros((1, 3)))
    assert charger_vecteurs(fichier) == {}
    assert charger_vecteurs(tmp_path / "absent.npz") == {}


def test_ingestion_reprend_les_vecteurs(conn):
    r = ingerer(conn, CORPUS_TEST, fichier_vecteurs=FICHIER)
    assert r["precalcules"] >= 5
    assert r["precalcules"] + r["calcules"] == r["passages"]
