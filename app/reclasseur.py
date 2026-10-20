"""Reclasseur (cross-encoder) : relit la question avec chacun des premiers passages et les remet en ordre.

Modèle local gratuit : cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 (multilingue, Apache 2.0, export ONNX du dépôt
Hugging Face, 450 Mo). La recherche hybride trouve les candidats ; le reclasseur ne réordonne que les
RECLASSEUR_CANDIDATS premiers articles (un passage chacun), ce qui coûte environ une seconde par question sur le
processeur. Il ne change pas le « je ne sais pas », qui reste fondé sur la similarité cosinus.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app import config


class Reclasseur:
    def __init__(self, dossier: Path = config.DOSSIER_RECLASSEUR, taille_lot: int = 8):
        self.tokenizer = Tokenizer.from_file(str(dossier / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        pad = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_padding(pad_id=1 if pad is None else pad, pad_token="<pad>")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(dossier / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.entrees = {e.name for e in self.session.get_inputs()}
        self.taille_lot = taille_lot

    def scores(self, question: str, textes: list[str]) -> list[float]:
        """Pertinence de chaque texte pour la question (logit : plus c'est haut, plus c'est pertinent)."""
        resultats: list[float] = []
        for i in range(0, len(textes), self.taille_lot):
            lot = self.tokenizer.encode_batch([(question, t) for t in textes[i : i + self.taille_lot]])
            flux = {
                "input_ids": np.array([e.ids for e in lot], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in lot], dtype=np.int64),
            }
            if "token_type_ids" in self.entrees:
                flux["token_type_ids"] = np.array([e.type_ids for e in lot], dtype=np.int64)
            resultats.extend(float(x) for x in self.session.run(None, flux)[0][:, 0])
        return resultats


@lru_cache(maxsize=1)
def reclasseur() -> Reclasseur:
    return Reclasseur()
