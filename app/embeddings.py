"""Embeddings locaux sur CPU : modèle ONNX (BAAI/bge-m3 par défaut), sans PyTorch.

bge-m3 : vecteur du jeton [CLS], sans préfixe. Les modèles e5 (essayés) : moyenne des
états cachés pondérée par le masque, préfixes « query: » / « passage: ». Vecteurs normalisés (L2).
"""

import shutil
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app import config

FICHIERS = ("onnx/model.onnx", "onnx/tokenizer.json")
FICHIERS_FACULTATIFS = ("onnx/model.onnx_data",)  # poids externes des modèles de plus de 2 Go


def telecharger_modele(dossier: Path = config.DOSSIER_MODELE) -> Path:
    """Télécharge les poids ONNX (révision figée) si absents. Utilisé à la construction de l'image."""
    from huggingface_hub import hf_hub_download

    dossier.mkdir(parents=True, exist_ok=True)
    from huggingface_hub.errors import EntryNotFoundError

    for nom in FICHIERS + FICHIERS_FACULTATIFS:
        cible = dossier / Path(nom).name
        if cible.exists():
            continue
        try:
            chemin = hf_hub_download(config.MODELE_HF, nom, revision=config.MODELE_REVISION)
        except EntryNotFoundError:
            if nom in FICHIERS_FACULTATIFS:
                continue
            raise
        shutil.copyfile(chemin, cible)
    return dossier


class Encodeur:
    def __init__(self, dossier: Path = config.DOSSIER_MODELE, taille_lot: int = 16):
        self.tokenizer = Tokenizer.from_file(str(dossier / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(dossier / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.entrees = {e.name for e in self.session.get_inputs()}
        self.taille_lot = taille_lot

    def _encoder(self, textes: list[str]) -> np.ndarray:
        # Lots formés de textes de longueurs voisines : moins de remplissage, donc moins de calcul.
        ordre = sorted(range(len(textes)), key=lambda i: len(textes[i]))
        resultats = []
        for i in range(0, len(ordre), self.taille_lot):
            lot = self.tokenizer.encode_batch([textes[j] for j in ordre[i : i + self.taille_lot]])
            ids = np.array([e.ids for e in lot], dtype=np.int64)
            masque = np.array([e.attention_mask for e in lot], dtype=np.int64)
            flux = {"input_ids": ids, "attention_mask": masque}
            if "token_type_ids" in self.entrees:
                flux["token_type_ids"] = np.zeros_like(ids)
            etats = self.session.run(None, flux)[0]
            if config.POOLING == "cls":
                vecteurs = etats[:, 0]
            else:
                m = masque[..., None].astype(np.float32)
                vecteurs = (etats * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            resultats.append(vecteurs / np.linalg.norm(vecteurs, axis=1, keepdims=True))
        if not resultats:
            return np.zeros((0, config.DIMENSION), dtype=np.float32)
        vecteurs = np.empty((len(textes), resultats[0].shape[1]), dtype=np.float32)
        vecteurs[ordre] = np.vstack(resultats)
        return vecteurs

    def questions(self, textes: list[str]) -> np.ndarray:
        return self._encoder([f"query: {t}" if config.PREFIXES else t for t in textes])

    def passages(self, textes: list[str]) -> np.ndarray:
        return self._encoder([f"passage: {t}" if config.PREFIXES else t for t in textes])


@lru_cache(maxsize=1)
def encodeur() -> Encodeur:
    return Encodeur()


if __name__ == "__main__":
    print(telecharger_modele())
