"""Ingestion idempotente : corpus JSON -> passages -> embeddings -> pgvector.

Seuls les passages nouveaux ou modifiés (empreinte différente) sont recalculés ; les passages
qui ne sont plus dans le corpus sont supprimés. Relancer l'ingestion sans changement ne fait rien.

Les vecteurs du corpus livré sont précalculés dans `corpus/vecteurs/bge-m3.npz` (même modèle, même révision) :
le premier démarrage n'a alors presque rien à calculer. Un passage absent du fichier (corpus modifié) est calculé
normalement. `python -m app.ingestion --precalculer` régénère le fichier.
"""

import logging
import sys
from pathlib import Path

import numpy as np
import psycopg

from app import config
from app.db import connexion, creer_schema
from app.decoupage import Passage, charger_corpus, passages_du_texte
from app.embeddings import Encodeur, encodeur

log = logging.getLogger("rag-copropriete")
TAILLE_LOT_INSERTION = 64


def charger_vecteurs(fichier: str | Path | None = config.FICHIER_VECTEURS) -> dict[str, np.ndarray]:
    """Vecteurs précalculés par empreinte de passage ; vide si le fichier manque ou vient d'un autre modèle."""
    if not fichier or not Path(fichier).exists():
        return {}
    with np.load(fichier) as donnees:
        if str(donnees["signature"]) != config.SIGNATURE_MODELE:
            log.warning("Vecteurs précalculés ignorés : modèle différent (%s)", donnees["signature"])
            return {}
        return dict(zip(donnees["empreintes"].tolist(), donnees["vecteurs"]))


def precalculer(fichier: str | Path, dossier: Path = config.DOSSIER_CORPUS, enc: Encodeur | None = None) -> int:
    passages = list({p.empreinte: p for doc in charger_corpus(dossier) for p in passages_du_texte(doc)}.values())
    vecteurs = (enc or encodeur()).passages([p.a_indexer for p in passages])
    Path(fichier).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        fichier,
        signature=np.array(config.SIGNATURE_MODELE),
        empreintes=np.array([p.empreinte for p in passages]),
        vecteurs=vecteurs.astype(np.float32),
    )
    return len(passages)


def _inserer(conn: psycopg.Connection, lignes: list[tuple[Passage, np.ndarray]]) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO passages (texte_id, texte_titre, article_id, article_num, chemin, morceau,
                                  contenu, url, empreinte, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (article_id, morceau) DO UPDATE SET
                texte_id = EXCLUDED.texte_id, texte_titre = EXCLUDED.texte_titre,
                article_num = EXCLUDED.article_num, chemin = EXCLUDED.chemin,
                contenu = EXCLUDED.contenu, url = EXCLUDED.url,
                empreinte = EXCLUDED.empreinte, embedding = EXCLUDED.embedding
            """,
            [
                (p.texte_id, p.texte_titre, p.article_id, p.article_num, p.chemin, p.morceau,
                 p.contenu, p.url, p.empreinte, v)
                for p, v in lignes
            ],
        )


def ingerer(
    conn: psycopg.Connection,
    dossier: Path = config.DOSSIER_CORPUS,
    enc: Encodeur | None = None,
    fichier_vecteurs: str | Path | None = config.FICHIER_VECTEURS,
) -> dict:
    creer_schema(conn)
    passages = [p for doc in charger_corpus(dossier) for p in passages_du_texte(doc)]
    with conn.cursor() as cur:
        cur.execute("SELECT article_id, morceau, empreinte FROM passages")
        existants = {(a, m): e for a, m, e in cur.fetchall()}

    a_ecrire = [p for p in passages if existants.get((p.article_id, p.morceau)) != p.empreinte]
    precalcules = charger_vecteurs(fichier_vecteurs) if a_ecrire else {}
    repris = [(p, precalcules[p.empreinte]) for p in a_ecrire if p.empreinte in precalcules]
    a_calculer = [p for p in a_ecrire if p.empreinte not in precalcules]
    for i in range(0, len(repris), TAILLE_LOT_INSERTION):
        _inserer(conn, repris[i : i + TAILLE_LOT_INSERTION])
    # Calcul et écriture par lots : la progression est visible dans la base et une ingestion interrompue reprend
    # là où elle s'était arrêtée.
    for i in range(0, len(a_calculer), TAILLE_LOT_INSERTION):
        lot = a_calculer[i : i + TAILLE_LOT_INSERTION]
        _inserer(conn, list(zip(lot, (enc or encodeur()).passages([p.a_indexer for p in lot]))))
        log.info("Ingestion : %d/%d passages calculés", i + len(lot), len(a_calculer))

    cles = {(p.article_id, p.morceau) for p in passages}
    obsoletes = [k for k in existants if k not in cles]
    if obsoletes:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany("DELETE FROM passages WHERE article_id = %s AND morceau = %s", obsoletes)

    return {
        "passages": len(passages),
        "calcules": len(a_calculer),
        "precalcules": len(repris),
        "inchanges": len(passages) - len(a_ecrire),
        "supprimes": len(obsoletes),
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["--precalculer"]:
        print(precalculer(config.FICHIER_VECTEURS), "vecteurs écrits dans", config.FICHIER_VECTEURS)
    else:
        with connexion() as c:
            print(ingerer(c))
