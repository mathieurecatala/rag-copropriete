FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DOSSIER_MODELE=/modeles/bge-m3/onnx DOSSIER_RECLASSEUR=/modeles/mmarco/onnx HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app

# Les poids des modèles sont téléchargés avant l'installation des dépendances : changer requirements.txt ne les
# retélécharge pas. Même version de huggingface_hub que requirements.txt.
ARG HF_HUB_VERSION=1.33.0
RUN pip install "huggingface_hub==$HF_HUB_VERSION"

# Poids du modèle d'embeddings dans l'image (≈2,2 Go) : pas de téléchargement au démarrage ni dans les tests.
# Même modèle et même révision que app/config.py.
ARG MODELE_HF=BAAI/bge-m3
ARG MODELE_REVISION=5617a9f61b028005a4858fdac845db406aefb181
RUN hf download "$MODELE_HF" onnx/model.onnx onnx/model.onnx_data onnx/tokenizer.json \
        --revision "$MODELE_REVISION" --local-dir /modeles/bge-m3 \
    && rm -rf /root/.cache/huggingface /modeles/bge-m3/.cache

# Reclasseur cross-encoder (≈450 Mo), même révision que app/config.py.
ARG RECLASSEUR_HF=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
ARG RECLASSEUR_REVISION=1427fd652930e4ba29e8149678df786c240d8825
RUN hf download "$RECLASSEUR_HF" onnx/model.onnx tokenizer.json \
        --revision "$RECLASSEUR_REVISION" --local-dir /modeles/mmarco \
    && mv /modeles/mmarco/tokenizer.json /modeles/mmarco/onnx/ \
    && rm -rf /root/.cache/huggingface /modeles/mmarco/.cache

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY app app
COPY corpus corpus
COPY eval eval
COPY tests tests
COPY pytest.ini ./

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
