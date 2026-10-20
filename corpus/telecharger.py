"""Télécharge les versions consolidées des textes du corpus depuis les données ouvertes de la DILA (base LEGI).

Légifrance refuse les requêtes automatiques (protection anti-robots) ; la DILA publie la même base,
sous Licence Ouverte Etalab 2.0, sur https://echanges.dila.gouv.fr/OPENDATA/LEGI/ :
- une archive globale (« Freemium_legi_global_<date>.tar.gz », environ 1,1 Go) ;
- une archive incrémentale par jour depuis (fichiers modifiés + liste des suppressions).

Le script part de l'archive globale la plus récente, applique dans l'ordre toutes les incrémentales
publiées après elle, n'en garde que les fichiers des textes du corpus, puis écrit un JSON par texte
dans corpus/donnees/ : un article en vigueur par entrée (numéro, plan, texte officiel, lien Légifrance),
avec l'URL de la source, la date de consolidation et la date de téléchargement.

Le texte des articles est celui de la DILA, converti de HTML en texte brut ; il n'est ni résumé ni réécrit.

Usage : python corpus/telecharger.py [--cache corpus/cache] [--sortie corpus/donnees]
Les archives téléchargées restent dans le cache : relancer le script ne télécharge que les nouvelles.
"""

import argparse
import datetime as dt
import html
import json
import re
import shutil
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DILA = "https://echanges.dila.gouv.fr/OPENDATA/LEGI/"
LICENCE = "Licence Ouverte / Open Licence version 2.0 (Etalab)"

TEXTES = [
    {
        "id": "loi-1965",
        "cid": "JORFTEXT000000880200",
        "titre_court": "Loi du 10 juillet 1965",
    },
    {
        "id": "decret-1967",
        "cid": "JORFTEXT000000305770",
        "titre_court": "Décret du 17 mars 1967",
    },
]

# Articles dont l'état indique qu'ils ne font pas partie du droit applicable, quelles que soient les dates.
ETATS_EXCLUS = {"ANNULE", "DISJOINT", "PERIME", "TRANSFERE", "ABROGE", "MODIFIE_MORT_NE"}
FIN_INDEFINIE = "2999-01-01"


def lister_archives() -> list[str]:
    with urllib.request.urlopen(DILA, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    return sorted(set(re.findall(r'href="((?:Freemium_legi_global|LEGI)_[0-9-]+\.tar\.gz)"', page)))


def date_archive(nom: str) -> str:
    """« LEGI_20261007-211514.tar.gz » -> « 20261007-211514 »."""
    return re.search(r"(\d{8}-\d{6})", nom).group(1)


def telecharger(nom: str, cache: Path) -> Path:
    cible = cache / nom
    if cible.exists():
        return cible
    partiel = cible.with_suffix(".partiel")
    print(f"  téléchargement {nom}", flush=True)
    with urllib.request.urlopen(DILA + nom, timeout=300) as r, partiel.open("wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    partiel.rename(cible)
    return cible


def extraire(archive: Path, cids: set[str], dossier: Path) -> tuple[int, list[str]]:
    """Copie les fichiers des textes voulus (chemin à partir du CID) ; renvoie aussi les suppressions."""
    copies, suppressions = 0, []
    motif = re.compile(r"/(" + "|".join(sorted(cids)) + r")/(.+\.xml)$")
    with tarfile.open(archive, "r|gz") as tar:
        for membre in tar:
            if membre.name.endswith("liste_suppression_legi.dat"):
                suppressions += tar.extractfile(membre).read().decode("utf-8").split()
                continue
            m = motif.search(membre.name)
            if not m or not membre.isfile():
                continue
            cible = dossier / m.group(1) / m.group(2)
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(tar.extractfile(membre).read())
            copies += 1
    return copies, suppressions


def appliquer_suppressions(suppressions: list[str], cids: set[str], dossier: Path) -> int:
    n = 0
    for ligne in suppressions:
        for cid in cids:
            if f"/{cid}/" in ligne:
                chemin = dossier / cid / (ligne.split(f"/{cid}/", 1)[1] + ".xml")
                if chemin.exists():
                    chemin.unlink()
                    n += 1
    return n


def texte_brut(element: ET.Element | None) -> str:
    """HTML de la DILA -> texte : un paragraphe par ligne, cellules de tableau séparées par « | »."""
    if element is None:
        return ""
    brut = ET.tostring(element, encoding="unicode", method="xml")
    brut = re.sub(r"^<CONTENU[^>]*>|</CONTENU>$", "", brut.strip())
    brut = re.sub(r"<br\s*/?>", "\n", brut, flags=re.I)
    brut = re.sub(r"</(p|div|tr|li|h\d)>", "\n", brut, flags=re.I)
    brut = re.sub(r"</t[dh]>", " | ", brut, flags=re.I)
    brut = re.sub(r"<[^>]+>", "", brut)
    brut = html.unescape(brut).replace("\xa0", " ")
    lignes = [re.sub(r"[ \t]+", " ", ligne).strip(" |") for ligne in brut.split("\n")]
    return "\n".join(ligne for ligne in lignes if ligne.strip())


def cle_numero(num: str) -> list:
    """Tri naturel des numéros d'article : 1, 1-1, 2, 10, 18-1 A, Annexe..."""
    annexe = num.lower().startswith("annexe")
    return [annexe] + [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.findall(r"\d+|[^\d\s-]+", num)]


def lire_article(fichier: Path) -> dict | None:
    racine = ET.parse(fichier).getroot()
    meta = racine.find("META/META_SPEC/META_ARTICLE")
    num = (meta.findtext("NUM") or "").strip()
    titres = []
    tm = racine.find("CONTEXTE/TEXTE/TM")
    while tm is not None:
        titre = tm.find("TITRE_TM")
        if titre is not None and titre.text:
            titres.append(" ".join(titre.text.split()))
        tm = tm.find("TM")
    return {
        "id": racine.findtext("META/META_COMMUN/ID"),
        "num": num,
        "etat": meta.findtext("ETAT") or "",
        "date_debut": meta.findtext("DATE_DEBUT") or "",
        "date_fin": meta.findtext("DATE_FIN") or FIN_INDEFINIE,
        "chemin": " > ".join(titres),
        "texte": texte_brut(racine.find("BLOC_TEXTUEL/CONTENU")),
    }


def titre_officiel(dossier_texte: Path) -> str:
    versions = sorted((dossier_texte / "texte" / "version").glob("*.xml"))
    for v in versions:
        titre = ET.parse(v).getroot().findtext("META/META_SPEC/META_TEXTE_VERSION/TITREFULL")
        if titre:
            return " ".join(titre.split())
    return ""


def construire(texte: dict, dossier: Path, consolidation: str, source: str, aujourd_hui: str) -> dict:
    dossier_texte = dossier / texte["cid"]
    articles = {}
    for fichier in (dossier_texte / "article").rglob("LEGIARTI*.xml"):
        a = lire_article(fichier)
        if not a["num"] or not a["texte"] or a["etat"] in ETATS_EXCLUS:
            continue
        if not (a["date_debut"] <= aujourd_hui < a["date_fin"]):
            continue
        precedent = articles.get(a["num"])
        if precedent is None or a["date_debut"] > precedent["date_debut"]:
            articles[a["num"]] = a
    return {
        "id": texte["id"],
        "cid": texte["cid"],
        "titre": titre_officiel(dossier_texte),
        "titre_court": texte["titre_court"],
        "url_source": f"https://www.legifrance.gouv.fr/loda/id/{texte['cid']}/",
        "source_donnees": source,
        "licence": LICENCE,
        "date_consolidation": consolidation,
        "date_telechargement": dt.date.today().isoformat(),
        "articles": [
            {
                "id": a["id"],
                "num": a["num"],
                "chemin": a["chemin"],
                "etat": a["etat"],
                "date_debut": a["date_debut"],
                "url": f"https://www.legifrance.gouv.fr/loda/article_lc/{a['id']}",
                "texte": a["texte"],
            }
            for a in sorted(articles.values(), key=lambda a: cle_numero(a["num"]))
        ],
    }


def main() -> None:
    racine = Path(__file__).resolve().parent
    parseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parseur.add_argument("--cache", type=Path, default=racine / "cache")
    parseur.add_argument("--sortie", type=Path, default=racine / "donnees")
    parseur.add_argument("--global", dest="archive_globale", help="nom d'une archive globale précise")
    args = parseur.parse_args()

    args.cache.mkdir(parents=True, exist_ok=True)
    args.sortie.mkdir(parents=True, exist_ok=True)
    cids = {t["cid"] for t in TEXTES}
    extraits = args.cache / "textes"
    if extraits.exists():
        shutil.rmtree(extraits)

    archives = lister_archives()
    globales = [a for a in archives if a.startswith("Freemium_legi_global")]
    globale = args.archive_globale or max(globales, key=date_archive)
    date_globale = date_archive(globale)
    incrementales = sorted(
        (a for a in archives if a.startswith("LEGI_") and date_archive(a) > date_globale), key=date_archive
    )
    print(f"Archive globale : {globale} ; {len(incrementales)} incrémentales à appliquer.")

    n, _ = extraire(telecharger(globale, args.cache), cids, extraits)
    print(f"  {n} fichiers extraits de l'archive globale")
    for nom in incrementales:
        archive = telecharger(nom, args.cache)
        n, suppressions = extraire(archive, cids, extraits)
        s = appliquer_suppressions(suppressions, cids, extraits)
        if n or s:
            print(f"  {nom} : {n} fichiers mis à jour, {s} supprimés")

    derniere = incrementales[-1] if incrementales else globale
    d = date_archive(derniere)
    consolidation = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    source = f"DILA, base LEGI ({DILA}) : {globale} + {len(incrementales)} archives incrémentales jusqu'à {derniere}"
    aujourd_hui = dt.date.today().isoformat()
    for texte in TEXTES:
        document = construire(texte, extraits, consolidation, source, aujourd_hui)
        if not document["articles"]:
            raise SystemExit(f"Aucun article trouvé pour {texte['cid']} : identifiant ou archive à vérifier.")
        sortie = args.sortie / f"{texte['id']}.json"
        sortie.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{sortie} : {len(document['articles'])} articles en vigueur — {document['titre']}")


if __name__ == "__main__":
    main()
