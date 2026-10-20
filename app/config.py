"""Réglages lus dans l'environnement (valeurs de dev par défaut, aucune clé obligatoire)."""

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://syndic:syndic@localhost:5432/syndic")
DOSSIER_CORPUS = Path(os.environ.get("DOSSIER_CORPUS", RACINE / "corpus" / "donnees"))
DOSSIER_MODELE = Path(os.environ.get("DOSSIER_MODELE", RACINE / "modeles" / "bge-m3"))

# Modèle d'embeddings local : BAAI/bge-m3 (export ONNX du dépôt Hugging Face), choisi après comparaison avec
# multilingual-e5 small, base et large sur eval/questions.json. Révision figée pour que deux
# constructions de l'image donnent les mêmes vecteurs.
MODELE_HF = os.environ.get("MODELE_HF", "BAAI/bge-m3")
MODELE_REVISION = os.environ.get("MODELE_REVISION", "5617a9f61b028005a4858fdac845db406aefb181")
DIMENSION = int(os.environ.get("DIMENSION", "1024"))
# Famille bge : vecteur [CLS], sans préfixe. Famille e5 : moyenne des états cachés, préfixes « query: » / « passage: ».
POOLING = os.environ.get("POOLING", "cls")
PREFIXES = os.environ.get("PREFIXES", "0") == "1"

# Vecteurs précalculés du corpus (versionnés) : l'ingestion les reprend au lieu de recalculer bge-m3, à condition
# que le modèle, la révision et le découpage soient les mêmes (empreinte de chaque passage). Vide = désactivé.
FICHIER_VECTEURS = os.environ.get("FICHIER_VECTEURS", str(RACINE / "corpus" / "vecteurs" / "bge-m3.npz"))
SIGNATURE_MODELE = f"{MODELE_HF}@{MODELE_REVISION}|{POOLING}|prefixes={int(PREFIXES)}|{DIMENSION}"

# Découpage : un article plus long que ce nombre de caractères est coupé en morceaux.
TAILLE_MAX_MORCEAU = int(os.environ.get("TAILLE_MAX_MORCEAU", "1500"))

# « Je ne sais pas » : si la meilleure similarité cosinus entre la question et un passage est sous ce seuil.
# Valeur calibrée sur eval/questions.json (questions du domaine et questions hors sujet).
SEUIL_SIMILARITE = float(os.environ.get("SEUIL_SIMILARITE", "0.55"))
# Une question qui cite un numéro d'article sans nommer la loi ni le décret n'échappe au « je ne sais pas » que si sa
# similarité dépasse ce plancher. Aucune question d'évaluation ne cite d'article : valeur choisie à la main, sans
# réglage, nettement sous le seuil ; une question sans rapport avec la copropriété (« tarte aux pommes ») est dessous.
PLANCHER_ARTICLE_CITE = float(os.environ.get("PLANCHER_ARTICLE_CITE", "0.45"))

# Poids de la liste plein texte dans la fusion RRF (la liste vectorielle pèse 1). 0,3 : choisi sur l'évaluation,
# où le plein texte seul est nettement moins bon que les vecteurs ; il sert surtout aux termes exacts.
POIDS_PLEIN_TEXTE = float(os.environ.get("POIDS_PLEIN_TEXTE", "0.3"))

# Reclasseur cross-encoder sur les premiers articles trouvés (app/reclasseur.py). RECLASSEUR=0 le désactive.
RECLASSEUR = os.environ.get("RECLASSEUR", "1") == "1"
DOSSIER_RECLASSEUR = Path(os.environ.get("DOSSIER_RECLASSEUR", RACINE / "modeles" / "mmarco"))
RECLASSEUR_HF = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RECLASSEUR_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
RECLASSEUR_CANDIDATS = int(os.environ.get("RECLASSEUR_CANDIDATS", "10"))
# Le reclasseur lit chaque point d'une énumération (« a) », « 1° ») séparément, précédé de la phrase d'introduction
# de l'article, et garde le meilleur : un long article à points (article 25) n'est plus jugé sur un texte dilué.
RECLASSEUR_PAR_POINT = os.environ.get("RECLASSEUR_PAR_POINT", "1") == "1"
# Questions de majorité ou de vote : les articles qui fixent les majorités (loi de 1965) entrent parmi les candidats
# du reclasseur. MAJORITES=0 désactive cette règle.
MAJORITES = os.environ.get("MAJORITES", "1") == "1"
ARTICLES_MAJORITES = ("24", "25", "26")
# Reformulation de la question par un petit lexique (app/lexique.py). LEXIQUE=0 la désactive.
LEXIQUE = os.environ.get("LEXIQUE", "1") == "1"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or None
MODELE_CLAUDE = os.environ.get("MODELE_CLAUDE", "claude-haiku-5-5")

INGESTION_AU_DEMARRAGE = os.environ.get("INGESTION_AU_DEMARRAGE", "0") == "1"
