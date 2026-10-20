"""API FastAPI : page web, question, ingestion."""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config
from app.db import connexion, nombre_passages
from app.generation import generation_active, rediger
from app.ingestion import ingerer
from app.recherche import rechercher

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag-copropriete")

PAGE = Path(__file__).parent / "static" / "index.html"
etat = {"ingestion": "inactive", "detail": None}
verrou = threading.Lock()


def lancer_ingestion() -> dict:
    if not verrou.acquire(blocking=False):
        raise HTTPException(409, "Une ingestion est déjà en cours.")
    etat["ingestion"] = "en cours"
    try:
        with connexion() as conn:
            resultat = ingerer(conn)
        etat.update(ingestion="terminée", detail=resultat)
        log.info("Ingestion : %s", resultat)
        return resultat
    except Exception as erreur:
        etat.update(ingestion="échec", detail=str(erreur))
        raise
    finally:
        verrou.release()


def _ingestion_de_fond() -> None:
    try:
        lancer_ingestion()
    except Exception:
        log.exception("Ingestion au démarrage en échec")


@asynccontextmanager
async def cycle(_: FastAPI):
    if config.INGESTION_AU_DEMARRAGE:
        threading.Thread(target=_ingestion_de_fond, daemon=True).start()
    yield


app = FastAPI(title="Textes de la copropriété", lifespan=cycle)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)


@app.get("/", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(PAGE)


@app.get("/sante")
def sante() -> dict:
    with connexion() as conn:
        n = nombre_passages(conn)
    return {
        "passages": n,
        "ingestion": etat["ingestion"],
        "detail": etat["detail"],
        "generation": generation_active(),
        "modele_generation": config.MODELE_CLAUDE if generation_active() else None,
    }


@app.post("/ingestion")
def ingestion() -> dict:
    return lancer_ingestion()


@app.post("/question")
def question(q: Question) -> dict:
    with connexion() as conn:
        if nombre_passages(conn) == 0:
            raise HTTPException(503, "Le corpus n'est pas encore chargé (POST /ingestion).")
        r = rechercher(conn, q.question, k=q.k)
    reponse = None if r.je_ne_sais_pas else rediger(q.question, r.passages)
    return {
        "question": r.question,
        "je_ne_sais_pas": r.je_ne_sais_pas,
        "meilleure_similarite": r.meilleure_similarite,
        "seuil": r.seuil,
        "reponse": reponse,
        "generation": generation_active(),
        "passages": [p.dict() for p in r.passages],
    }
