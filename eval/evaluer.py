"""Évaluation de la recherche sur deux jeux de questions.

- `eval/questions.json` (jeu de mise au point, 20 questions) : sert à régler la recherche (poids, seuil, lexique) ;
  la mesure sur ce jeu est donc optimiste.
- `eval/controle/questions.json` (jeu de contrôle, mis à part) : écrit après les premiers réglages (modèle, poids,
  seuil, reclasseur) mais avant le correctif de l'article 25 ; mesuré avant et après ce correctif, jamais utilisé pour
  régler. C'est la mesure la plus honnête, sans être aveugle : ses échecs étaient visibles pendant le correctif.

Mesures, pour chaque jeu :
- hit@1, hit@3 (mesure principale : un syndic lit les trois premiers résultats) et MRR@10 ;
- « je ne sais pas » : part des questions hors corpus correctement refusées, et part des questions du domaine
  refusées à tort, au seuil configuré.
Les modes (hybride avec reclasseur, hybride sans reclasseur, vecteurs seuls, plein texte seul) sont mesurés pour
justifier la fusion et le reclasseur.

Prérequis : base remplie (ingestion faite). Usage :
    python eval/evaluer.py                  # les deux jeux, rapport et README mis à jour
    python eval/evaluer.py --sans-readme    # sans réécrire le README
    python eval/evaluer.py --jeux controle  # un seul jeu
    python eval/evaluer.py --ingerer        # charge d'abord le corpus (idempotent) : une seule commande
    python eval/evaluer.py --comparer       # échoue si un chiffre recule par rapport aux résultats commités (CI)
Écrit eval/resultats/<jeu>.json et eval/resultats/rapport.md, et met à jour la section « Évaluation » du README.
"""

import argparse
import json
import os
import platform
import sys
import time
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app import config  # noqa: E402
from app.db import connexion, nombre_passages  # noqa: E402
from app.ingestion import ingerer  # noqa: E402
from app.recherche import rechercher  # noqa: E402

MODES = ("hybride", "rrf", "vecteur", "plein_texte")
DEBUT, FIN = "<!-- EVAL:DEBUT -->", "<!-- EVAL:FIN -->"
JEUX = {
    "mise_au_point": ("eval/questions.json", "jeu de mise au point (sert aux réglages : mesure optimiste)"),
    "controle": ("eval/controle/questions.json", "jeu de contrôle (mis à part, jamais utilisé pour régler)"),
}
DOSSIER_RESULTATS = RACINE / "eval" / "resultats"


def rang_attendu(resultats, attendus) -> int | None:
    cles = {(a["texte"], a["article"]) for a in attendus}
    for rang, p in enumerate(resultats, 1):
        if (p.texte_id, p.article_num) in cles:
            return rang
    return None


def mesures(rangs: list[int | None]) -> dict:
    n = max(len(rangs), 1)
    return {
        "hit@1": round(sum(1 for x in rangs if x and x <= 1) / n, 3),
        "hit@3": round(sum(1 for x in rangs if x and x <= 3) / n, 3),
        "mrr@10": round(sum(1 / x for x in rangs if x) / n, 3),
    }


def evaluer(conn, jeu: dict) -> dict:
    questions, hors_sujet = jeu["questions"], jeu["hors_sujet"]
    resultats = {"seuil": config.SEUIL_SIMILARITE, "reclasseur": config.RECLASSEUR, "n_questions": len(questions),
                 "n_hors_sujet": len(hors_sujet), "modes": {}, "detail": []}
    debut = time.perf_counter()
    for mode in MODES:
        rangs = []
        for q in questions:
            if mode == "rrf":
                r = rechercher(conn, q["question"], k=10, reclasser=False)
            else:
                r = rechercher(conn, q["question"], k=10, mode=mode)
            rang = rang_attendu(r.passages, q["attendu"])
            rangs.append(rang)
            if mode == "hybride":
                resultats["detail"].append({
                    "question": q["question"],
                    "attendu": [f"{a['texte']} art. {a['article']}" for a in q["attendu"]],
                    "rang": rang,
                    "top3": [f"{p.texte_id} art. {p.article_num}" for p in r.passages[:3]],
                    "meilleure_similarite": r.meilleure_similarite,
                    "je_ne_sais_pas": r.je_ne_sais_pas,
                })
        resultats["modes"][mode] = mesures(rangs)
        if mode == "hybride":
            resultats["secondes_par_question"] = round((time.perf_counter() - debut) / max(len(questions), 1), 2)

    refus = []
    for q in hors_sujet:
        r = rechercher(conn, q, k=3)
        refus.append({"question": q, "je_ne_sais_pas": r.je_ne_sais_pas,
                      "meilleure_similarite": r.meilleure_similarite})
    resultats["hors_sujet"] = refus
    resultats["refus_hors_sujet"] = round(sum(r["je_ne_sais_pas"] for r in refus) / max(len(refus), 1), 3)
    resultats["refus_a_tort"] = round(
        sum(d["je_ne_sais_pas"] for d in resultats["detail"]) / max(len(questions), 1), 3
    )
    return resultats


NOMS = {"rrf": "Hybride (RRF) sans reclasseur", "vecteur": "Vecteurs seuls", "plein_texte": "Plein texte seul"}


def _nom(mode: str, r: dict) -> str:
    if mode == "hybride":
        return "Hybride + reclasseur" if r.get("reclasseur") else "Hybride (RRF)"
    return NOMS[mode]


def tableau(r: dict) -> list[str]:
    lignes = ["| Mode | hit@1 | hit@3 | MRR@10 |", "|---|---|---|---|"]
    for mode in MODES:
        if mode == "rrf" and not r.get("reclasseur"):
            continue
        m = r["modes"][mode]
        lignes.append(f"| {_nom(mode, r)} | {m['hit@1']:.0%} | {m['hit@3']:.0%} | {m['mrr@10']:.2f} |")
    return lignes


def ratees(r: dict) -> list[str]:
    lignes = []
    for d in r["detail"]:
        if d["rang"] and d["rang"] <= 3:
            continue
        rang = f"rang {d['rang']}" if d["rang"] else "absent des 10 premiers"
        lignes.append(f"- {d['question']} — attendu {', '.join(d['attendu'])}, {rang} ; "
                      f"trouvé : {', '.join(d['top3'])}")
    return lignes or ["- aucune"]


def resume(nom: str, r: dict) -> str:
    h = r["modes"]["hybride"]
    n = r["n_questions"]
    return (f"{nom} : hit@3 {round(h['hit@3'] * n)}/{n} = {h['hit@3']:.0%}, hit@1 {h['hit@1']:.0%}, "
            f"MRR@10 {h['mrr@10']:.2f} ; hors sujet refusées {r['refus_hors_sujet']:.0%} "
            f"({r['n_hors_sujet']} questions), refus à tort {r['refus_a_tort']:.0%}")


def section_readme(tous: dict[str, dict]) -> str:
    lignes = [
        "Mesuré par `eval/evaluer.py` (rapport complet : `eval/resultats/rapport.md`). Deux jeux de questions, chacune "
        "avec l'article attendu, plus des questions hors corpus. **Les questions ont été écrites par une IA à partir du "
        "texte, pas par un juriste.**",
        "",
    ]
    for cle, r in tous.items():
        lignes.append(f"- {resume(JEUX[cle][1].capitalize(), r)}.")
    lignes.append("")
    for cle, r in tous.items():
        lignes += [f"**{JEUX[cle][1].capitalize()}** (`{JEUX[cle][0]}`, {r['n_questions']} questions) :", ""]
        lignes += tableau(r) + [""]
    return "\n".join(lignes).rstrip()


def rapport(tous: dict[str, dict]) -> str:
    lignes = [
        "# Rapport d'évaluation de la recherche",
        "",
        f"Produit par `python eval/evaluer.py` le {date.today().isoformat()} (Python {platform.python_version()}), "
        f"sur {machine()}. "
        f"Seuil « je ne sais pas » : {config.SEUIL_SIMILARITE} ; reclasseur : "
        f"{'actif' if config.RECLASSEUR else 'désactivé'} ; poids du plein texte dans la fusion : "
        f"{config.POIDS_PLEIN_TEXTE}.",
        "",
        "Les questions ont été écrites par une IA (Claude) à partir du texte des articles, pas par un juriste. "
        "hit@k : part des questions dont un article attendu est dans les k premiers résultats ; MRR@10 : moyenne de "
        "1/rang de l'article attendu (0 s'il n'est pas dans les 10 premiers).",
        "",
    ]
    for cle, r in tous.items():
        chemin, description = JEUX[cle]
        lignes += [
            f"## {description.capitalize()}",
            "",
            f"`{chemin}` : {r['n_questions']} questions du domaine, {r['n_hors_sujet']} hors corpus. "
            f"Temps moyen en mode hybride + reclasseur : {r.get('secondes_par_question', '?')} s par question.",
            "",
            *tableau(r),
            "",
            f"« Je ne sais pas » au seuil {r['seuil']} : {r['refus_hors_sujet']:.0%} des questions hors corpus "
            f"refusées, {r['refus_a_tort']:.0%} des questions du domaine refusées à tort.",
            "",
            "Questions dont l'article attendu n'est pas dans les trois premiers (mode hybride + reclasseur) :",
            "",
            *ratees(r),
            "",
            "Questions hors corpus non refusées :",
            "",
            *([f"- {h['question']} (similarité {h['meilleure_similarite']})"
               for h in r["hors_sujet"] if not h["je_ne_sais_pas"]] or ["- aucune"]),
            "",
        ]
    return "\n".join(lignes)


def ecrire_readme(texte: str, readme: Path = RACINE / "README.md") -> None:
    contenu = readme.read_text(encoding="utf-8")
    if DEBUT in contenu and FIN in contenu:
        avant, reste = contenu.split(DEBUT, 1)
        apres = reste.split(FIN, 1)[1]
        readme.write_text(f"{avant}{DEBUT}\n{texte}\n{FIN}{apres}", encoding="utf-8")


def machine() -> str:
    """Système, processeur et nombre de cœurs : les temps de réponse n'ont de sens qu'avec eux."""
    modele = platform.processor() or "processeur inconnu"
    try:
        for ligne in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if ligne.startswith("model name"):
                modele = ligne.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}, {modele}, {os.cpu_count()} cœurs logiques"


# Chiffres comparés par --comparer : un recul d'une seule question fait échouer (les mesures sont déterministes).
HAUSSE_ATTENDUE = ("hit@1", "hit@3", "mrr@10")


def reculs(ancien: dict, nouveau: dict) -> list[str]:
    """Chiffres du mode hybride + reclasseur et du « je ne sais pas » qui reculent par rapport à `ancien`."""
    problemes = []
    for m in HAUSSE_ATTENDUE:
        if nouveau["modes"]["hybride"][m] < ancien["modes"]["hybride"][m]:
            problemes.append(f"{m} {ancien['modes']['hybride'][m]} -> {nouveau['modes']['hybride'][m]}")
    if nouveau["refus_hors_sujet"] < ancien["refus_hors_sujet"]:
        problemes.append(f"hors sujet refusées {ancien['refus_hors_sujet']} -> {nouveau['refus_hors_sujet']}")
    if nouveau["refus_a_tort"] > ancien["refus_a_tort"]:
        problemes.append(f"refus à tort {ancien['refus_a_tort']} -> {nouveau['refus_a_tort']}")
    return problemes


def main(argv: list[str] | None = None) -> None:
    parseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parseur.add_argument("--sans-readme", action="store_true", help="ne pas réécrire le README")
    parseur.add_argument("--jeux", nargs="+", choices=list(JEUX), default=list(JEUX))
    parseur.add_argument("--ingerer", action="store_true", help="charger le corpus avant de mesurer (idempotent)")
    parseur.add_argument("--comparer", action="store_true",
                         help="échouer si un chiffre recule par rapport à eval/resultats/<jeu>.json (avant réécriture)")
    args = parseur.parse_args(argv)
    references = {cle: json.loads((DOSSIER_RESULTATS / f"{cle}.json").read_text(encoding="utf-8"))
                  for cle in args.jeux if args.comparer}
    tous = {}
    with connexion() as conn:
        if args.ingerer:
            print("Ingestion :", ingerer(conn))
        if nombre_passages(conn) == 0:
            raise SystemExit("Base vide : lancez l'ingestion d'abord (POST /ingestion).")
        for cle in args.jeux:
            jeu = json.loads((RACINE / JEUX[cle][0]).read_text(encoding="utf-8"))
            tous[cle] = evaluer(conn, jeu)
    DOSSIER_RESULTATS.mkdir(parents=True, exist_ok=True)
    for cle, r in tous.items():
        (DOSSIER_RESULTATS / f"{cle}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    texte = rapport(tous)
    (DOSSIER_RESULTATS / "rapport.md").write_text(texte, encoding="utf-8")
    for cle, r in tous.items():
        print(resume(JEUX[cle][1], r))
    print(f"Rapport : {DOSSIER_RESULTATS.relative_to(RACINE) / 'rapport.md'}")
    if not args.sans_readme and set(tous) == set(JEUX):
        ecrire_readme(section_readme(tous))
    problemes = [f"{cle} : {p}" for cle in references for p in reculs(references[cle], tous[cle])]
    if problemes:
        raise SystemExit("Recul par rapport aux résultats commités :\n" + "\n".join(problemes))
    if args.comparer:
        print("Aucun recul par rapport aux résultats commités.")


if __name__ == "__main__":
    main()
