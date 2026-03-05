#!/usr/bin/env python3
"""Reclassify exercise analyses by context extracted from detailed exercise text only."""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "exercise_analyses.json"
DEFAULT_OUTPUT_JSON = Path(__file__).resolve().parent.parent / "exercise_analyses.json"
DEFAULT_OUTPUT_JS = Path(__file__).resolve().parent.parent / "exercise_analyses.js"

STOPWORDS = {
    "alors", "ainsi", "avec", "avoir", "cette", "cela", "celle", "celui", "ceux", "chaque", "comme", "dans",
    "des", "donc", "dont", "elle", "elles", "encore", "entre", "etre", "fait", "faire", "fois", "leur", "leurs",
    "mais", "meme", "moins", "nous", "pour", "plus", "par", "pas", "que", "quel", "quelle", "quelles", "quels",
    "sans", "sera", "sont", "sous", "sur", "tout", "tous", "tres", "une", "votre", "vous", "dans", "donner",
    "montrer", "supposer", "soit", "on", "il", "ils", "elle", "elles", "du", "de", "la", "le", "les", "un",
    "et", "ou", "a", "au", "aux", "ce", "cet", "cette", "est", "si", "en", "ne", "se", "sa", "son", "ses",
    "d", "l", "n", "m", "x", "y", "z", "alpha", "beta", "gamma", "delta", "epsilon", "lambda", "mu", "nu",
    "mathbb", "mathbf", "boldsymbol", "begin", "end", "left", "right", "frac", "text", "forall", "exists", "pmatrix",
    "cdot", "sum", "prod", "int", "sqrt", "geq", "leq", "to",
    "exercice", "banque", "concours", "mathematiques", "physique", "question", "questions", "partie", "parties",
    "point", "points", "donnees", "donnee", "soient", "montrer", "calculer", "determiner",
}

MATH_CONTEXT_RULES = [
    ("Algebre spectrale et reductions", ["matrice", "endomorph", "valeur propre", "vecteur propre", "diagonal", "jordan", "spectre", "determinant"]),
    ("Analyse des suites, series et asymptotique", ["serie", "suite", "convergence", "equivalent", "asymptot", "developpement limite", "serie entiere"]),
    ("Integrales et analyse continue", ["integrale", "integration", "riemann", "changement de variable", "theoreme de fubini", "dominee", "uniforme"]),
    ("Probabilites et variables aleatoires", ["probabil", "variable aleatoire", "esperance", "variance", "loi", "gauss", "markov", "bernoulli"]),
    ("Equations differentielles et systemes", ["equation differentielle", "edo", "systeme differentiel", "solution generale", "stabilite", "derivee seconde"]),
    ("Optimisation et calcul differentiel", ["gradient", "hessien", "convexe", "extremum", "lagrange", "derivee"]),
    ("Geometrie et espaces euclidiens", ["espace euclid", "produit scalaire", "orthogonal", "distance", "projection", "courbe", "surface"]),
    ("Polynomes et fractions rationnelles", ["polynome", "racine", "interpolation", "fraction rationnelle"]),
]

PHYS_CONTEXT_RULES = [
    ("Mecanique newtonienne et dynamique", ["newton", "mecanique", "energie", "moment", "force", "trajectoire", "orbite", "pendule", "mouvement", "vitesse", "acceleration", "position"]),
    ("Oscillations et systemes lineaires", ["oscillation", "resonance", "oscillateur", "amortissement", "pulsation", "rlc", "regime sinusoidal"]),
    ("Electromagnetisme et induction", ["induction", "maxwell", "flux", "champ magnet", "champ electrique", "electromagnet", "faraday"]),
    ("Electrostatique et potentiels", ["electrostat", "potentiel", "gauss", "dipole", "capacite", "condensateur"]),
    ("Thermodynamique et bilans energetiques", ["thermo", "entrop", "rendement", "cycle", "gaz parfait", "bilan", "carnot"]),
    ("Ondes et optique", ["onde", "interference", "diffraction", "optique", "fresnel", "laser", "propagation"]),
    ("Fluides et ecoulements", ["fluide", "bernoulli", "viscos", "ecoulement", "pression", "navier"]),
    ("Diffusion et transferts thermiques", ["diffusion", "conduction", "chaleur", "equation de la chaleur", "gradient thermique"]),
    ("Physique quantique", ["schrodinger", "quantique", "etat", "fonction d onde", "incertitude"]),
]

CONCEPT_PATTERNS = {
    "diagonalisation": ["diagonal", "jordan", "valeur propre", "vecteur propre"],
    "matrices": ["matrice", "determinant", "trace"],
    "series": ["serie", "serie entiere"],
    "convergence": ["convergence", "uniforme", "dominee"],
    "integrales": ["integrale", "integration", "riemann"],
    "equations differentielles": ["equation differentielle", "edo", "systeme differentiel"],
    "probabilites": ["probabil", "variable aleatoire", "esperance", "variance", "loi"],
    "optimisation": ["gradient", "hessien", "extremum", "lagrange", "convexe"],
    "espaces euclidiens": ["espace euclid", "produit scalaire", "orthogonal", "projection"],
    "mecanique": ["newton", "mecanique", "force", "moment", "energie"],
    "oscillateurs": ["oscillation", "resonance", "oscillateur", "pulsation"],
    "electromagnetisme": ["maxwell", "induction", "flux", "champ magnet", "champ electrique"],
    "electrostatique": ["electrostat", "potentiel", "gauss", "dipole"],
    "thermodynamique": ["thermo", "entrop", "cycle", "rendement"],
    "ondes": ["onde", "interference", "diffraction", "propagation"],
    "optique": ["optique", "fresnel", "laser"],
    "fluides": ["fluide", "bernoulli", "viscos", "ecoulement"],
    "diffusion thermique": ["diffusion", "conduction", "equation de la chaleur"],
}



def normalize_for_match(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_first_sentence(statement: str) -> str:
    clean = re.sub(r"\s+", " ", html.unescape(statement).strip())
    if not clean:
        return ""
    parts = re.split(r"(?<=[\.!?])\s+", clean)
    return parts[0] if parts else clean


def assign_context_groups(subject: str, detail_text_norm: str) -> tuple[str, list[str], list[str]]:
    rules = MATH_CONTEXT_RULES if subject == "Maths" else PHYS_CONTEXT_RULES

    scored: list[tuple[str, int, list[str]]] = []
    for label, patterns in rules:
        matched = [p for p in patterns if p in detail_text_norm]
        if matched:
            scored.append((label, len(matched), matched))

    if not scored:
        fallback = "Contexte non detecte (texte a completer)"
        return fallback, [], []

    scored.sort(key=lambda item: (-item[1], item[0]))
    primary = scored[0][0]
    secondary = [label for label, _, _ in scored[1:3]]
    evidence = scored[0][2][:5]
    return primary, secondary, evidence


def extract_important_keywords(detail_text_norm: str, limit: int = 10) -> list[str]:
    concept_hits: list[tuple[str, int]] = []
    for concept, patterns in CONCEPT_PATTERNS.items():
        count = sum(1 for p in patterns if p in detail_text_norm)
        if count:
            concept_hits.append((concept, count))

    concept_hits.sort(key=lambda item: (-item[1], item[0]))
    prioritized = [label for label, _ in concept_hits][:limit]

    if len(prioritized) < limit:
        tokens = [t for t in detail_text_norm.split() if len(t) >= 5 and t not in STOPWORDS and not t.isdigit()]
        counts = Counter(tokens)
        for token, _ in counts.most_common(limit * 2):
            if token not in prioritized:
                prioritized.append(token)
            if len(prioritized) >= limit:
                break

    return prioritized[:limit]


def build_contextual_summary(first_sentence: str, primary_group: str, important_keywords: list[str]) -> str:
    if first_sentence:
        base = re.sub(r"\s+", " ", first_sentence)
        short = (base[:210] + "...") if len(base) > 210 else base
    else:
        short = "L'enonce complet n'est pas disponible dans cette entree."

    kw = ", ".join(important_keywords[:4]) if important_keywords else ""
    if kw:
        return f"{short} Contexte detecte: {primary_group.lower()}. Motifs centraux: {kw}."
    return f"{short} Contexte detecte: {primary_group.lower()}."


def reclassify_record(record: dict[str, Any]) -> dict[str, Any]:
    statement = record.get("statement", "")
    hints = record.get("hints", "")
    comments = record.get("comments", "")

    # Context inference uses detailed content only (statement/hints/comments).
    # If detail text is missing, fallback to BEOS content tags to avoid dropping the exercise.
    detail_text = "\n".join(part for part in [statement, hints, comments] if part)
    detail_norm = normalize_for_match(detail_text)
    used_fallback_keywords = False
    if len(detail_norm) < 20:
        keyword_text = " ".join(record.get("keywords", []))
        detail_norm = normalize_for_match(keyword_text)
        used_fallback_keywords = True

    primary_group, secondary_groups, evidence_terms = assign_context_groups(record.get("subject", ""), detail_norm)
    important_keywords = extract_important_keywords(detail_norm)

    first_sentence = extract_first_sentence(statement)
    summary = build_contextual_summary(first_sentence, primary_group, important_keywords)

    cleaned = {k: v for k, v in record.items() if k not in {"classification"}}

    return {
        **cleaned,
        "context": {
            "primaryGroup": primary_group,
            "secondaryGroups": secondary_groups,
            "evidenceTerms": evidence_terms,
            "importantKeywords": important_keywords,
        },
        "analysis": {
            "summary": summary,
            "contextNotes": [
                "Classification fondee sur l'enonce, les indications et les commentaires.",
                "Groupe principal choisi par signaux textuels dominants du detail de l'exercice.",
                "Fallback sur mots-cles BEOS active faute de detail textuel." if used_fallback_keywords else "Aucun fallback: detail textuel suffisant.",
            ],
            "importantKeywords": important_keywords,
        },
    }


def to_compact(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": rec["id"],
            "url": rec["url"],
            "year": rec["year"],
            "banque": rec["banque"],
            "subject": rec["subject"],
            "statementPreview": extract_first_sentence(rec.get("statement", "")),
            "context": rec.get("context", {}),
            "analysis": rec.get("analysis", {}),
        }
        for rec in records
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Reclassify exercises by detailed context")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-js", type=Path, default=DEFAULT_OUTPUT_JS)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    recs = [reclassify_record(rec) for rec in source]

    recs.sort(key=lambda x: (x.get("year") or 0, x.get("banque", ""), x.get("subject", ""), x.get("id", 0)))

    args.output_json.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")

    compact = to_compact(recs)
    args.output_js.write_text(
        "// Generated from BEOS detailed exercise context analysis\n"
        f"const exerciseAnalyses = {json.dumps(compact, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )

    primary_counts = Counter(rec["context"]["primaryGroup"] for rec in recs)
    print(
        json.dumps(
            {
                "records": len(recs),
                "primary_groups": dict(primary_counts.most_common()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
