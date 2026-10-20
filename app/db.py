"""Connexion Postgres et schéma (pgvector + plein texte français)."""

import psycopg
from pgvector.psycopg import register_vector

from app import config

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS passages (
    id          serial PRIMARY KEY,
    texte_id    text NOT NULL,
    texte_titre text NOT NULL,
    article_id  text NOT NULL,
    article_num text NOT NULL,
    chemin      text NOT NULL DEFAULT '',
    morceau     integer NOT NULL,
    contenu     text NOT NULL,
    url         text NOT NULL,
    empreinte   text NOT NULL,
    embedding   vector({config.DIMENSION}) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (
        to_tsvector('french', texte_titre || ' article ' || article_num || ' ' || chemin || ' ' || contenu)
    ) STORED,
    UNIQUE (article_id, morceau)
);
CREATE INDEX IF NOT EXISTS passages_tsv ON passages USING gin (tsv);
CREATE INDEX IF NOT EXISTS passages_embedding ON passages USING hnsw (embedding vector_cosine_ops);
"""


def connexion(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or config.DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def creer_schema(conn: psycopg.Connection) -> None:
    """Crée la table ; si elle existe avec une autre dimension (changement de modèle), la recrée vide."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT format_type(atttypid, atttypmod) FROM pg_attribute
            WHERE attrelid = to_regclass('passages') AND attname = 'embedding'
            """
        )
        ligne = cur.fetchone()
        if ligne and ligne[0] != f"vector({config.DIMENSION})":
            cur.execute("DROP TABLE passages")
        cur.execute(SCHEMA)


def nombre_passages(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('passages') IS NOT NULL")
        if not cur.fetchone()[0]:
            return 0
        cur.execute("SELECT count(*) FROM passages")
        return cur.fetchone()[0]
