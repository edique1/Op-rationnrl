#!/usr/bin/env python3
"""Fetch MP oral entries from BEOS and generate data.js for the FAQ analyzer."""

from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, build_opener

BASE_URL = "https://beos.prepas.org/index.php?"
SUBJECTS = {
    "63": "Maths",
    "64": "Physique",
}
CONCOURS = {
    "58": "X-ENS",  # X (non PC/PSI)
    "59": "X-ENS",  # ENS (non PSI)
    "55": "Centrale",  # Centrale-Supelec
    "57": "Mines-Ponts",  # Banque Mines-Ponts
    "54": "CCINP",  # CCINP (ou CCP)
}
FILIERE_MP = "45"

TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
LAST_PAGE_RE = re.compile(r'value="(\d+)">Dernier »')


def clean_text(raw: str) -> str:
    text = html.unescape(TAG_RE.sub("", raw))
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_keywords(value: str) -> list[str]:
    if not value:
        return []
    # BEOS entries sometimes use different dash characters/spaces between keywords.
    normalized = (
        value.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u00a0", " ")
    )
    parts = [piece.strip(" -") for piece in re.split(r"\s*-\s*", normalized) if piece.strip()]
    return [p for p in parts if p]


def split_types(value: str) -> list[str]:
    if not value:
        return ["Non précisé"]
    parts = [piece.strip() for piece in re.split(r"\s*-\s*", value) if piece.strip()]
    if not parts:
        return ["Non précisé"]

    def normalize_type(type_name: str) -> str:
        lowered = unicodedata.normalize("NFKD", type_name.lower())
        lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if lowered in {"resolution de probleme", "probleme ouvert", "entretien scientifique"} or lowered.startswith("lecon"):
            return "Exercice"
        return type_name

    normalized = []
    seen = set()
    for part in parts:
        mapped = normalize_type(part)
        if mapped not in seen:
            seen.add(mapped)
            normalized.append(mapped)
    return normalized if normalized else ["Non précisé"]


def normalize_keyword(value: str) -> str:
    lowered = value.lower().strip()
    lowered = unicodedata.normalize("NFKD", lowered)
    lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def parse_rows(html_text: str, banque: str, subject: str) -> list[dict]:
    rows = []

    for tr_match in re.finditer(r'<tr data-id="(\d+)"\s*>(.*?)</tr>', html_text, re.S):
        source_id = tr_match.group(1)
        tr_html = tr_match.group(2)
        cells = TD_RE.findall(tr_html)
        if len(cells) < 8:
            continue

        year_text = clean_text(cells[1])
        filiere = clean_text(cells[2])
        concours_label = clean_text(cells[3])
        subject_label = clean_text(cells[4])
        type_label = clean_text(cells[5])
        keywords = clean_text(cells[6])

        if filiere != "MP":
            continue

        try:
            year = int(year_text)
        except ValueError:
            continue

        rows.append(
            {
                "source_id": source_id,
                "year": year,
                "concours_label": concours_label,
                "subject_label": subject_label,
                "type_label": type_label,
                "keywords": split_keywords(keywords),
                "banque": banque,
                "subject": subject,
            }
        )

    return rows


def fetch_filter_rows(opener, concours_id: str, subject_id: str) -> list[dict]:
    banque = CONCOURS[concours_id]
    subject = SUBJECTS[subject_id]
    opener.open(BASE_URL, timeout=30).read()

    query = {
        "id_filiere": FILIERE_MP,
        "id_concours": concours_id,
        "id_matiere": subject_id,
        "search": "Rechercher",
    }
    page1 = opener.open(BASE_URL, data=urlencode(query).encode(), timeout=30).read().decode("utf-8", "ignore")
    rows = parse_rows(page1, banque=banque, subject=subject)

    last_page_match = LAST_PAGE_RE.search(page1)
    last_page = int(last_page_match.group(1)) if last_page_match else 1

    for page in range(2, last_page + 1):
        page_html = (
            opener.open(BASE_URL, data=urlencode({"page": str(page)}).encode(), timeout=30)
            .read()
            .decode("utf-8", "ignore")
        )
        rows.extend(parse_rows(page_html, banque=banque, subject=subject))

    return rows


def extract_all_rows() -> list[dict]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    all_rows = []

    for concours_id in CONCOURS:
        for subject_id in SUBJECTS:
            rows = fetch_filter_rows(opener, concours_id, subject_id)
            all_rows.extend(rows)

    return all_rows


def build_appearances(rows: list[dict]) -> tuple[list[dict], dict]:
    by_norm = defaultdict(lambda: defaultdict(int))
    entries = []
    seen = set()

    for row in rows:
        concours_label = row["concours_label"]
        banque = row["banque"]
        subject = row["subject"]

        for keyword in row["keywords"]:
            norm = normalize_keyword(keyword)
            if not norm:
                continue
            source_id = row["source_id"]
            dedupe_key = (source_id, norm)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            by_norm[norm][keyword] += 1
            entries.append(
                {
                    "theme_norm": norm,
                    "theme_raw": keyword,
                    "subject": subject,
                    "year": row["year"],
                    "banque": banque,
                    "exam": concours_label,
                    "section": f"BEOS #{source_id}",
                    "sourceUrl": f"https://beos.prepas.org/sujet.php?id={source_id}",
                    "types": split_types(row.get("type_label", "")),
                }
            )

    canonical = {
        norm: sorted(variants.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for norm, variants in by_norm.items()
    }

    appearances = [
        {
            "theme": canonical[item["theme_norm"]],
            "subject": item["subject"],
            "year": item["year"],
            "banque": item["banque"],
            "exam": item["exam"],
            "section": item["section"],
            "sourceUrl": item["sourceUrl"],
            "types": item["types"],
        }
        for item in entries
    ]

    appearances.sort(key=lambda item: (item["year"], item["banque"], item["subject"], item["theme"]))

    stats = {
        "records": len(rows),
        "appearances": len(appearances),
        "themes": len({item["theme"] for item in appearances}),
        "years": [
            min(item["year"] for item in appearances) if appearances else None,
            max(item["year"] for item in appearances) if appearances else None,
        ],
    }

    return appearances, stats


def write_data_js(appearances: list[dict], output_path: Path) -> None:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = json.dumps(appearances, ensure_ascii=False, indent=2)
    output = (
        "// Generated from BEOS MP database\n"
        f"// Generated at: {generated_at}\n"
        "// Source: https://beos.prepas.org/index.php?\n"
        f"const concoursAppearances = {payload};\n"
    )
    output_path.write_text(output, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch BEOS MP data and generate data.js")
    parser.add_argument(
        "--output",
        default=Path(__file__).resolve().parent.parent / "data.js",
        type=Path,
        help="Output JS path",
    )
    args = parser.parse_args()

    rows = extract_all_rows()
    appearances, stats = build_appearances(rows)
    write_data_js(appearances, args.output)

    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
