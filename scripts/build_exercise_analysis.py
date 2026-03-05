#!/usr/bin/env python3
"""Build per-exercise analysis/classification from BEOS sujet pages."""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import time
import unicodedata
from collections import Counter
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, build_opener

BASE_SUBJECT_URL = "https://beos.prepas.org/sujet.php?id={id}"
DEFAULT_DATA_JS = Path(__file__).resolve().parent.parent / "data.js"
DEFAULT_OUTPUT_JSON = Path(__file__).resolve().parent.parent / "exercise_analyses.json"
DEFAULT_OUTPUT_JS = Path(__file__).resolve().parent.parent / "exercise_analyses.js"
DEFAULT_CACHE_JSONL = Path(__file__).resolve().parent.parent / "exercise_analyses_cache.jsonl"

TAG_RE = re.compile(r"<[^>]+>")
FIELD_RE_TEMPLATE = r"<p><b>{label}</b>\s*(.*?)</p>"
TEXTAREA_RE = re.compile(r'<div id="showSources" class="modal">.*?<textarea[^>]*>(.*?)</textarea>', re.S)
SOURCE_ID_RE = re.compile(r"#(\d+)$")


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "")
    value = value.replace("\xa0", " ")
    value = TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_for_match(value: str) -> str:
    value = strip_accents(value.lower())
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_field(html_text: str, label: str) -> str:
    pattern = re.compile(FIELD_RE_TEMPLATE.format(label=re.escape(label)), re.S)
    match = pattern.search(html_text)
    if not match:
        return ""
    return normalize_text(match.group(1))


def parse_sources_blob(html_text: str) -> dict[str, str]:
    match = TEXTAREA_RE.search(html_text)
    if not match:
        return {"raw": "", "statement": "", "hints": "", "comments": ""}

    raw = html.unescape(match.group(1)).replace("\r", "")
    raw = raw.replace("\xa0", " ")

    def section(start: str, end: str | None) -> str:
        if start not in raw:
            return ""
        begin = raw.index(start) + len(start)
        finish = raw.index(end, begin) if end and end in raw[begin:] else len(raw)
        return re.sub(r"\n{2,}", "\n\n", raw[begin:finish]).strip()

    statement = section("Énoncé(s) donné(s)", "Indication(s) fournie(s) par l'examinateur pendant l'épreuve")
    hints = section("Indication(s) fournie(s) par l'examinateur pendant l'épreuve", "Commentaires divers")
    comments = section("Commentaires divers", None)

    return {
        "raw": re.sub(r"\n{3,}", "\n\n", raw).strip(),
        "statement": statement,
        "hints": hints,
        "comments": comments,
    }


def classify_subject_domain(subject: str, text_norm: str) -> tuple[str, list[str]]:
    if subject == "Maths":
        rules = [
            ("Algebre lineaire", ["matrice", "diagonal", "endomorph", "jordan", "valeur propre", "espace euclid", "forme quadratique"]),
            ("Probabilites", ["probabil", "variable aleatoire", "esperance", "variance", "loi", "markov", "bernoulli"]),
            ("Equations differentielles", ["equation differentielle", "edo", "systeme differentiel"]),
            ("Analyse (integrales)", ["integrale", "riemann", "gauss", "convergence d integrale"]),
            ("Analyse (suites et series)", ["serie", "suite", "developpement limite", "serie entiere", "convergence"]),
            ("Geometrie", ["courbe", "surface", "geometr", "conique"]),
            ("Polynomes", ["polynome", "fraction rationnelle", "interpolation"]),
        ]
    else:
        rules = [
            ("Mecanique", ["mecanique", "newton", "pendule", "ressort", "moment", "energie", "orbite"]),
            ("Electromagnetisme", ["electro", "induction", "maxwell", "champ magnet", "circuit", "rlc", "dipole"]),
            ("Thermodynamique", ["thermo", "entrop", "rendement", "carnot", "gaz parfait"]),
            ("Ondes et optique", ["onde", "interference", "diffraction", "optique", "fresnel", "laser"]),
            ("Fluides", ["bernoulli", "viscos", "ecoulement", "fluide"]),
            ("Transferts thermiques", ["diffusion", "chaleur", "conduction", "equation de la chaleur"]),
            ("Physique quantique", ["schrodinger", "quantique", "paquet d onde", "incertitude"]),
        ]

    hits: list[tuple[str, int]] = []
    for label, patterns in rules:
        count = sum(1 for p in patterns if p in text_norm)
        if count:
            hits.append((label, count))

    if not hits:
        return ("Autres", [])

    hits.sort(key=lambda item: (-item[1], item[0]))
    primary = hits[0][0]
    secondary = [label for label, _ in hits[1:3]]
    return primary, secondary


def infer_task_type(text_norm: str) -> str:
    if any(token in text_norm for token in ["montrer", "justifier", "etablir", "prouver"]):
        return "Demonstration"
    if any(token in text_norm for token in ["determiner", "calculer", "evaluer", "donner"]):
        return "Calcul"
    if any(token in text_norm for token in ["modeliser", "equation du mouvement", "simuler", "numerique"]):
        return "Modelisation"
    if "python" in text_norm:
        return "Algorithmique"
    return "Mixte"


def infer_skills(text_norm: str, keywords: list[str]) -> list[str]:
    skill_map = {
        "Rigueur de preuve": ["montrer", "justifier", "preuve", "theoreme"],
        "Calcul technique": ["calcul", "integrale", "derivee", "determinant", "developpement"],
        "Changement de variable": ["changement de variable", "substitution"],
        "Approximation asymptotique": ["equivalent", "asymptot", "dl", "developpement limite"],
        "Resolution d'ED": ["equation differentielle", "solution generale", "edo"],
        "Raisonnement probabiliste": ["probabil", "loi", "esperance", "variance"],
        "Modelisation physique": ["modele", "systeme", "hypothese", "ordre de grandeur"],
        "Analyse dimensionnelle": ["dimension", "unite", "homogeneite"],
        "Interpretation physique": ["interpreter", "sens physique", "commenter"],
    }

    full_text = f"{text_norm} {' '.join(normalize_for_match(x) for x in keywords)}"
    skills = [name for name, pats in skill_map.items() if any(p in full_text for p in pats)]
    return skills[:5]


def infer_difficulty(statement: str, hints: str, keywords: list[str]) -> str:
    score = 0
    length = len(statement)
    score += 1 if length > 350 else 0
    score += 1 if length > 700 else 0
    score += 1 if len(keywords) >= 3 else 0
    score += 1 if len(keywords) >= 5 else 0
    score += 1 if hints else 0

    hard_tokens = [
        "uniforme",
        "spectre",
        "jordan",
        "interversion",
        "stokes",
        "residu",
        "non lineaire",
        "coupl",
    ]
    statement_norm = normalize_for_match(statement)
    score += sum(1 for t in hard_tokens if t in statement_norm)

    if score <= 1:
        return "Facile"
    if score <= 3:
        return "Moyen"
    if score <= 5:
        return "Difficile"
    return "Tres difficile"


def one_liner(summary_text: str, domain: str, task_type: str) -> str:
    sentence = summary_text.strip()
    if not sentence:
        return f"Exercice de {domain.lower()} axe sur un travail de type {task_type.lower()}."
    compact = re.sub(r"\s+", " ", sentence)
    return compact[:220] + ("..." if len(compact) > 220 else "")


def extract_first_sentence(statement: str) -> str:
    cleaned = re.sub(r"\s+", " ", statement.replace("\n", " ")).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[\.!?])\s+", cleaned)
    return parts[0] if parts else cleaned


def parse_data_js(data_js: Path) -> list[dict[str, Any]]:
    text = data_js.read_text(encoding="utf-8")
    start = text.find("[")
    end = text.rfind("];")
    if start == -1 or end == -1:
        raise ValueError("Unable to parse concoursAppearances in data.js")
    return json.loads(text[start : end + 1])


def map_banque(concours_label: str) -> str:
    if "Centrale-Sup" in concours_label:
        return "Centrale"
    if "Mines-Ponts" in concours_label:
        return "Mines-Ponts"
    if "CCINP" in concours_label or "CCP" in concours_label:
        return "CCINP"
    if concours_label.startswith("X") or concours_label.startswith("ENS"):
        return "X-ENS"
    return concours_label


def fetch_sujet_html(opener, source_id: int, retries: int = 3, timeout: int = 15) -> str:
    url = BASE_SUBJECT_URL.format(id=source_id)
    for attempt in range(1, retries + 1):
        try:
            return opener.open(url, timeout=timeout).read().decode("utf-8", "ignore")
        except (HTTPError, URLError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(0.5 * attempt + random.random() * 0.25)
    raise RuntimeError("unreachable")


def build_exercise_record(source_id: int, html_text: str) -> dict[str, Any]:
    year_raw = extract_field(html_text, "Année :")
    filiere = extract_field(html_text, "Filière :")
    concours = extract_field(html_text, "Concours :")
    matiere = extract_field(html_text, "Matière(s) concernée(s) :")
    types = extract_field(html_text, "Type(s) de sujet(s) :")
    keywords_raw = extract_field(html_text, "Mots-clés relatifs au contenu de l'épreuve :")

    source_blob = parse_sources_blob(html_text)
    statement = source_blob["statement"]
    hints = source_blob["hints"]
    comments = source_blob["comments"]

    try:
        year = int(year_raw)
    except ValueError:
        year = None

    subject = "Maths" if "Math" in matiere else "Physique"
    banque = map_banque(concours)
    keywords = [k.strip() for k in keywords_raw.split(" - ") if k.strip()]

    analysis_text = " ".join([keywords_raw, statement, hints, comments])
    analysis_norm = normalize_for_match(analysis_text)

    domain, secondary_domains = classify_subject_domain(subject, analysis_norm)
    task_type = infer_task_type(analysis_norm)
    skills = infer_skills(analysis_norm, keywords)
    difficulty = infer_difficulty(statement, hints, keywords)

    first_sentence = extract_first_sentence(statement)
    quick_analysis = {
        "summary": one_liner(first_sentence, domain, task_type),
        "focus": f"{domain} | {task_type} | {difficulty}",
        "approach": [
            "Identifier la structure mathematique/physique avant de calculer.",
            "Isoler les hypotheses cle et choisir l'outil principal adapte.",
            "Verifier le resultat (ordre de grandeur, coherence, cas limites).",
        ],
    }

    return {
        "id": source_id,
        "url": BASE_SUBJECT_URL.format(id=source_id),
        "year": year,
        "filiere": filiere,
        "banque": banque,
        "concours": concours,
        "subject": subject,
        "subjectRaw": matiere,
        "types": [x.strip() for x in types.split(" - ") if x.strip()],
        "keywords": keywords,
        "statement": statement,
        "hints": hints,
        "comments": comments,
        "classification": {
            "primaryDomain": domain,
            "secondaryDomains": secondary_domains,
            "taskType": task_type,
            "difficulty": difficulty,
            "skills": skills,
        },
        "analysis": quick_analysis,
    }


def write_outputs(records: list[dict[str, Any]], output_json: Path, output_js: Path) -> None:
    output_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    compact = [
        {
            "id": r["id"],
            "url": r["url"],
            "year": r["year"],
            "banque": r["banque"],
            "subject": r["subject"],
            "keywords": r["keywords"],
            "statementPreview": extract_first_sentence(r["statement"]),
            "classification": r["classification"],
            "analysis": r["analysis"],
        }
        for r in records
    ]

    output_js.write_text(
        "// Generated from BEOS sujet details\n"
        f"const exerciseAnalyses = {json.dumps(compact, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


def load_cache(cache_path: Path) -> dict[int, dict[str, Any]]:
    if not cache_path.exists():
        return {}
    cached: dict[int, dict[str, Any]] = {}
    with cache_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                cached[int(item["id"])] = item
            except Exception:
                continue
    return cached


def append_cache(cache_path: Path, record: dict[str, Any]) -> None:
    with cache_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build per-exercise analysis from BEOS")
    parser.add_argument("--data-js", type=Path, default=DEFAULT_DATA_JS)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-js", type=Path, default=DEFAULT_OUTPUT_JS)
    parser.add_argument("--cache-jsonl", type=Path, default=DEFAULT_CACHE_JSONL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.0, help="Pause between requests in seconds")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    appearances = parse_data_js(args.data_js)
    source_ids = sorted(
        {
            int(match.group(1))
            for item in appearances
            if (match := SOURCE_ID_RE.search(item.get("section", "")))
        }
    )

    if args.limit > 0:
        source_ids = source_ids[: args.limit]

    opener = build_opener(HTTPCookieProcessor(CookieJar()))

    cached_by_id = load_cache(args.cache_jsonl) if args.resume else {}
    records: list[dict[str, Any]] = list(cached_by_id.values())
    errors: list[dict[str, Any]] = []
    seen_ids = {r["id"] for r in records}

    if args.resume:
        print(f"Loaded cache records: {len(records)} from {args.cache_jsonl}", flush=True)
    else:
        if args.cache_jsonl.exists():
            os.remove(args.cache_jsonl)

    total = len(source_ids)
    for idx, source_id in enumerate(source_ids, start=1):
        if source_id in seen_ids:
            if idx % 200 == 0 or idx == total:
                print(f"Progress: {idx}/{total} | kept={len(records)} | errors={len(errors)}", flush=True)
            continue
        try:
            html_text = fetch_sujet_html(opener, source_id, retries=args.retries, timeout=args.timeout)
            record = build_exercise_record(source_id, html_text)
            # Keep the exact scope requested by user.
            if record["filiere"] != "MP":
                continue
            if record["banque"] not in {"X-ENS", "Centrale", "Mines-Ponts", "CCINP"}:
                continue
            if record["subject"] not in {"Maths", "Physique"}:
                continue
            records.append(record)
            seen_ids.add(source_id)
            append_cache(args.cache_jsonl, record)
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": source_id, "error": str(exc)})

        if args.sleep > 0:
            time.sleep(args.sleep)

        if idx % 200 == 0 or idx == total:
            print(f"Progress: {idx}/{total} | kept={len(records)} | errors={len(errors)}", flush=True)

    records.sort(key=lambda r: (r["year"] or 0, r["banque"], r["subject"], r["id"]))
    write_outputs(records, args.output_json, args.output_js)

    stats = {
        "fetched_ids": total,
        "kept_records": len(records),
        "errors": len(errors),
        "years": [min((r["year"] for r in records), default=None), max((r["year"] for r in records), default=None)],
        "domain_counts": Counter(r["classification"]["primaryDomain"] for r in records),
        "difficulty_counts": Counter(r["classification"]["difficulty"] for r in records),
        "task_type_counts": Counter(r["classification"]["taskType"] for r in records),
    }

    print(json.dumps({
        "stats": {
            **{k: v for k, v in stats.items() if not isinstance(v, Counter)},
            "domain_counts": dict(stats["domain_counts"]),
            "difficulty_counts": dict(stats["difficulty_counts"]),
            "task_type_counts": dict(stats["task_type_counts"]),
        },
        "errors_preview": errors[:20],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
