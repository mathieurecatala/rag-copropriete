"""Recherche hybride : plein texte français (Postgres) + similarité vectorielle (pgvector), fusion RRF.

- Plein texte : les mots de la question (racinisés, mots vides retirés par la configuration « french »)
  sont cherchés un par un (en OU : une question courante ne contient presque jamais tous les mots d'un
  article) ; un passage vaut la somme des poids des mots qu'il contient, chaque mot pesant d'autant plus
  qu'il est rare dans le corpus, et le score est BM25 (fréquence du mot, longueur du passage), calculé dans
  Postgres à partir du tsvector. « Désigner » ou « ascenseur » comptent ainsi plus que « syndic », présent
  partout, et un long article qui répète « syndic » ne passe plus devant un article court et précis.
- Vecteurs : distance cosinus sur les embeddings bge-m3.
- Fusion : Reciprocal Rank Fusion, score = somme de 1 / (60 + rang) sur les deux listes.
- Reclasseur (app/reclasseur.py) : les RECLASSEUR_CANDIDATS premiers articles de la fusion sont remis en ordre
  par un cross-encoder qui lit la question et le passage ensemble.
- Un article nommé dans la question (« que dit l'article 26 de la loi ? ») est placé en tête, sauf si la question
  nomme un autre texte (« article 1 du code de la consommation », « loi du 6 juillet 1989 », « loi Hamon »).
- « Je ne sais pas » : la meilleure similarité cosinus est sous le seuil (config.SEUIL_SIMILARITE), sauf si la
  question cite un article du corpus ET désigne sans ambiguïté la loi de 1965 ou le décret de 1967 (ou dépasse
  config.PLANCHER_ARTICLE_CITE) : « tarte aux pommes, article 42 » reste refusée.
  Le score RRF ne dépend que des rangs ; il ne dit pas si le meilleur passage est réellement proche.
"""

import re
from dataclasses import asdict, dataclass

import psycopg

from app import config
from app.embeddings import Encodeur, encodeur
from app.lexique import reformuler
from app.reclasseur import reclasseur

K_RRF = 60
CANDIDATS = 60
BM25_K1, BM25_B = 1.2, 0.75  # valeurs usuelles de BM25, non réglées sur l'évaluation


# « article 25 », « art. 10-1 », « l'article 17-1 A de la loi » : numéro tel qu'écrit dans les textes.
MOTIF_ARTICLE = re.compile(r"\bart(?:icles?|\.)?\s+(\d+(?:-\d+)*(?:\s?(?:A{1,2}|bis|B)\b)?)", re.IGNORECASE)


# Un autre texte que la loi du 10 juillet 1965 et le décret du 17 mars 1967 : code, ordonnance, loi ou décret d'une
# autre date (« loi du 6 juillet 1989 », « décret de 1987 »), numéroté autrement (« loi n° 89-462 ») ou désigné par
# un nom (« loi Hamon », « loi ALUR »). Un « article 1 » de ce texte n'est pas un article du corpus.
_LOI_OU_DECRET = r"\b(?:loi|d[ée]cret)\s+"
MOTIF_AUTRE_TEXTE = re.compile(
    r"\bcode\b|\bordonnance\b|\bdirective\b|\bconstitution\b"
    + "|" + _LOI_OU_DECRET + r"(?:n°\s*)?(?!65-557|67-223)\d{2,4}-\d+"
    + "|" + _LOI_OU_DECRET + r"du\s+\d{1,2}(?:er)?\s+\w+\s+(?!1965|1967)\d{4}"
    + "|" + _LOI_OU_DECRET + r"de\s+(?!1965|1967)\d{4}",
    re.IGNORECASE,
)
# Nom propre après « loi » ou « décret » (majuscule : sensible à la casse).
MOTIF_TEXTE_A_NOM = re.compile(r"\b[Ll]oi\s+(?!Du\b|De\b|Sur\b)[A-ZÉ][\w-]+|\b[Dd][ée]cret\s+(?!Du\b|De\b)[A-ZÉ][\w-]+")
# La loi de 1965 ou le décret de 1967 désignés sans ambiguïté (année, numéro ou date complète).
MOTIF_LOI_1965 = re.compile(r"1965|65-557")
MOTIF_DECRET_1967 = re.compile(r"1967|67-223")


def texte_du_corpus_designe(question: str) -> bool:
    """La question désigne sans ambiguïté la loi de 1965 ou le décret de 1967 (« loi de 1965 », « 17 mars 1967 »,
    « n° 65-557 »…) ; « de la loi » seul ne suffit pas."""
    return bool(MOTIF_LOI_1965.search(question) or MOTIF_DECRET_1967.search(question))


def articles_cites(question: str) -> list[tuple[str | None, str]]:
    """Articles nommés dans la question : (texte_id ou None si le texte n'est pas précisé, numéro). Liste vide si la
    question nomme un autre texte sans désigner la loi de 1965 ni le décret de 1967."""
    autre = MOTIF_AUTRE_TEXTE.search(question) or MOTIF_TEXTE_A_NOM.search(question)
    if autre and not texte_du_corpus_designe(question):
        return []
    texte = None
    if re.search(r"d[ée]cret|1967", question, re.IGNORECASE):
        texte = "decret-1967"
    elif re.search(r"\bloi\b|1965", question, re.IGNORECASE):
        texte = "loi-1965"
    numeros = [re.sub(r"(\d)\s?(A{1,2}|B|bis)$", r"\1 \2", m.group(1).strip()) for m in MOTIF_ARTICLE.finditer(question)]
    return [(texte, n) for n in numeros]


@dataclass
class Resultat:
    texte_id: str
    texte_titre: str
    article_id: str
    article_num: str
    chemin: str
    morceau: int
    contenu: str
    url: str
    score: float
    similarite: float
    rang_vectoriel: int | None
    rang_plein_texte: int | None
    cite_dans_la_question: bool = False
    pertinence: float | None = None  # score du reclasseur, s'il est actif

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Reponse:
    question: str
    je_ne_sais_pas: bool
    meilleure_similarite: float
    seuil: float
    passages: list[Resultat]


def rechercher(
    conn: psycopg.Connection,
    question: str,
    k: int = 5,
    seuil: float | None = None,
    enc: Encodeur | None = None,
    mode: str = "hybride",
    reclasser: bool | None = None,
) -> Reponse:
    """mode : « hybride » (par défaut), « vecteur » ou « plein_texte » (ces deux-là servent à l'évaluation).
    reclasser : None = selon config.RECLASSEUR ; le reclasseur ne s'applique qu'au mode hybride."""
    reclasser = (config.RECLASSEUR if reclasser is None else reclasser) and mode == "hybride"
    seuil = config.SEUIL_SIMILARITE if seuil is None else seuil
    # La recherche part de la question reformulée (app/lexique.py) ; le « je ne sais pas » et les similarités
    # affichées restent calculés sur la question d'origine.
    etendue = reformuler(question)
    vecteurs = (enc or encodeur()).questions([question] if etendue == question else [question, etendue])
    vecteur, vecteur_recherche = vecteurs[0], vecteurs[-1]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, 1 - (embedding <=> %s) FROM passages ORDER BY embedding <=> %s LIMIT %s",
            (vecteur_recherche, vecteur_recherche, CANDIDATS),
        )
        vectoriel = cur.fetchall()
        cur.execute(
            """
            WITH mots AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('french', %(q)s))) AS mot),
            corpus AS (SELECT count(*) AS n, avg(length(tsv)) AS longueur_moyenne FROM passages),
            occurrences AS (
                SELECT p.id, u.lexeme AS mot, array_length(u.positions, 1) AS tf, length(p.tsv) AS longueur
                FROM passages p, unnest(p.tsv) AS u
                WHERE u.lexeme IN (SELECT mot FROM mots)
            ),
            df AS (SELECT mot, count(*) AS df FROM occurrences GROUP BY mot)
            SELECT o.id
            FROM occurrences o JOIN df USING (mot) CROSS JOIN corpus c
            GROUP BY o.id
            ORDER BY sum(
                ln((c.n - df.df + 0.5) / (df.df + 0.5) + 1)
                * o.tf * (%(k1)s + 1)
                / (o.tf + %(k1)s * (1 - %(b)s + %(b)s * o.longueur / c.longueur_moyenne))
            ) DESC, o.id
            LIMIT %(n)s
            """,
            {"q": etendue, "n": CANDIDATS, "k1": BM25_K1, "b": BM25_B},
        )
        plein_texte = [r[0] for r in cur.fetchall()]
        if etendue != question:
            cur.execute("SELECT 1 - (embedding <=> %s) FROM passages ORDER BY embedding <=> %s LIMIT 1",
                        (vecteur, vecteur))
            ligne = cur.fetchone()
            meilleure = float(ligne[0]) if ligne else 0.0
        else:
            meilleure = max((float(x) for _, x in vectoriel), default=0.0)

    rang_v = {i: r for r, (i, _) in enumerate(vectoriel, 1)}
    rang_t = {i: r for r, i in enumerate(plein_texte, 1)}
    scores: dict[int, float] = {}
    poids_t = config.POIDS_PLEIN_TEXTE
    listes = {"hybride": ((rang_v, 1.0), (rang_t, poids_t)), "vecteur": ((rang_v, 1.0),),
              "plein_texte": ((rang_t, 1.0),)}[mode]
    for rangs, poids in listes:
        for i, r in rangs.items():
            scores[i] = scores.get(i, 0.0) + poids / (K_RRF + r)
    classement = sorted(scores, key=lambda i: (-scores[i], i))

    # Un article long est coupé en morceaux : on ne garde que le meilleur morceau de chaque article,
    # pour que les k passages renvoyés soient k articles distincts.
    # Un article nommé dans la question (« que dit l'article 26 ? ») passe en tête, quel que soit son score.
    directs = []
    cites = articles_cites(question)
    for texte_id, num in cites:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM passages WHERE article_num = %s AND morceau = 0
                  AND (%s::text IS NULL OR texte_id = %s) ORDER BY texte_id DESC
                """,
                (num, texte_id, texte_id),
            )
            directs += [r[0] for r in cur.fetchall() if r[0] not in directs]
    classement = directs + [i for i in classement if i not in directs]

    with conn.cursor() as cur:
        cur.execute("SELECT id, article_id FROM passages WHERE id = ANY(%s)", (classement,))
        article_de = dict(cur.fetchall())
    nombre = max(k, config.RECLASSEUR_CANDIDATS) if reclasser else k
    meilleurs, vus = [], set()
    for i in classement:
        if article_de[i] not in vus:
            vus.add(article_de[i])
            meilleurs.append(i)
        if len(meilleurs) == nombre:
            break

    pertinence: dict[int, float] = {}
    if reclasser and meilleurs:
        meilleurs, pertinence = _reclasser(conn, etendue, meilleurs, directs, article_de, k)

    resultats = []
    if meilleurs:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, texte_id, texte_titre, article_id, article_num, chemin, morceau, contenu, url,
                       1 - (embedding <=> %s)
                FROM passages WHERE id = ANY(%s)
                """,
                (vecteur, meilleurs),
            )
            lignes = {r[0]: r for r in cur.fetchall()}
        for i in meilleurs:
            _, tid, ttitre, aid, anum, chemin, morceau, contenu, url, sim = lignes[i]
            resultats.append(
                Resultat(tid, ttitre, aid, anum, chemin, morceau, contenu, url,
                         round(scores.get(i, 0.0), 5), round(float(sim), 4), rang_v.get(i), rang_t.get(i),
                         i in directs, round(pertinence[i], 3) if i in pertinence else None)
            )

    # Un article cité ne lève le « je ne sais pas » que si la question désigne sans ambiguïté la loi de 1965 ou le
    # décret de 1967, ou si elle est déjà assez proche du corpus : sinon « tarte aux pommes, article 42 » ou « article
    # 42 de la loi sur la tarte aux pommes » passeraient.
    passe_droit = bool(directs) and (texte_du_corpus_designe(question)
                                     or meilleure >= config.PLANCHER_ARTICLE_CITE)
    je_ne_sais_pas = meilleure < seuil and not passe_droit
    return Reponse(question, je_ne_sais_pas, round(meilleure, 4), seuil, resultats)


# Questions de majorité ou de vote : les majorités de l'assemblée générale sont fixées par les articles 24, 25 et 26
# de la loi. L'article 25 est une longue énumération (a à o) dont le vecteur est dilué : « changer de syndic » ne le
# retrouve pas. Pour ces questions, ces articles entrent parmi les candidats du reclasseur, qui seul décide de leur
# rang. Règle choisie à partir des deux échecs du jeu de mise au point.
MOTIF_MAJORITE = re.compile(r"\bmajorit|\bvot(?:e|er|é|ée|ent)\b|accord de l.assembl|unanimit", re.IGNORECASE)


def question_de_majorite(question: str) -> bool:
    return bool(MOTIF_MAJORITE.search(question))


# Un point d'énumération : « a) », « 1° », « II.- ».
MOTIF_POINT = re.compile(r"^(?:[a-z]\)|\d+°|[IVX]+\.?\s?-)")


def segments(contenu: str, chapeau: str = "") -> list[str]:
    """Découpe un morceau en segments pour le reclasseur : un segment par point d'énumération (« a) … », « 1° … »),
    précédé de la phrase d'introduction de l'article ; un morceau sans énumération reste entier."""
    lignes = [ligne.strip() for ligne in contenu.split("\n") if ligne.strip()]
    if sum(1 for ligne in lignes if MOTIF_POINT.match(ligne)) < 2:
        return [contenu]
    if lignes and lignes[0] == chapeau:
        lignes = lignes[1:]
    blocs: list[list[str]] = [[]]
    for ligne in lignes:
        if MOTIF_POINT.match(ligne) and blocs[-1]:
            blocs.append([])
        blocs[-1].append(ligne)
    return [(f"{chapeau}\n" if chapeau else "") + "\n".join(b) for b in blocs if b]


def _reclasser(conn, question, meilleurs, directs, article_de, k):
    """Remet en ordre les RECLASSEUR_CANDIDATS premiers articles (les articles nommés dans la question restent en
    tête).

    Avec RECLASSEUR_PAR_POINT, chaque article candidat est lu morceau par morceau, et point par point s'il est une
    énumération ; son score est le meilleur de ses segments, et le passage affiché est le morceau qui contient ce
    segment. Sinon, le reclasseur lit le meilleur morceau de chaque article (comportement d'origine)."""
    candidats = [article_de[i] for i in meilleurs[: config.RECLASSEUR_CANDIDATS] if i not in directs]
    if config.MAJORITES and question_de_majorite(question):
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT article_id FROM passages WHERE texte_id = 'loi-1965' "
                        "AND article_num = ANY(%s)", (list(config.ARTICLES_MAJORITES),))
            # Déjà candidats ou cités : pas en double. Un article classé après les candidats y entre.
            deja = set(candidats) | {article_de[i] for i in directs if i in article_de}
            candidats += [a for (a,) in cur.fetchall() if a not in deja]
    if not candidats:
        return meilleurs[:k], {}
    choisi = {article_de[i]: i for i in meilleurs}
    with conn.cursor() as cur:
        if config.RECLASSEUR_PAR_POINT:
            cur.execute("SELECT id, article_id, morceau, contenu, texte_titre, article_num, chemin FROM passages "
                        "WHERE article_id = ANY(%s) ORDER BY article_id, morceau", (candidats,))
        else:
            cur.execute("SELECT id, article_id, morceau, contenu, texte_titre, article_num, chemin FROM passages "
                        "WHERE id = ANY(%s) OR (article_id = ANY(%s) AND morceau = 0) ORDER BY article_id, morceau",
                        ([choisi[a] for a in candidats if a in choisi], [a for a in candidats if a not in choisi]))
        morceaux = cur.fetchall()
    paires: list[tuple[str, int, str]] = []
    chapeaux: dict[str, str] = {}
    for pid, aid, morceau, contenu, titre, num, chemin in morceaux:
        if morceau == 0:
            premier = contenu.split("\n", 1)[0].strip()
            chapeaux[aid] = premier if premier.endswith(":") and len(premier) <= 300 else ""
        textes = segments(contenu, chapeaux.get(aid, "")) if config.RECLASSEUR_PAR_POINT else [contenu]
        paires += [(aid, pid, f"{titre}, article {num}. {chemin}\n{t}") for t in textes]
    notes = reclasseur().scores(question, [t for _, _, t in paires])
    meilleur: dict[str, tuple[float, int]] = {}
    for (aid, pid, _), note in zip(paires, notes):
        if aid not in meilleur or note > meilleur[aid][0]:
            meilleur[aid] = (note, pid)
    ordre = sorted(meilleur, key=lambda a: -meilleur[a][0])
    pertinence = {meilleur[a][1]: meilleur[a][0] for a in ordre}
    tete = [i for i in meilleurs if i in directs]
    reste = [i for i in meilleurs[config.RECLASSEUR_CANDIDATS:] if i not in directs and article_de[i] not in meilleur]
    return (tete + [meilleur[a][1] for a in ordre] + reste)[:k], pertinence
