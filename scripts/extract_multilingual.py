"""
Extract multilingual transliterations and translations from database.sqlite
and enrich output/sggs_lines.jsonl + regenerate output/embedding_chunks.jsonl.

DB is opened read-only. Only SGGS data (source_id=1) is touched.

Translation sources used:
  1 - English, Dr. Sant Singh Khalsa   (already in JSONL; kept as primary)
  6 - Punjabi, Prof. Sahib Singh
  4 - Spanish, SikhNet

Transliterations:
  language_id=1 - Roman (English script phonetic)
  language_id=4 - Hindi (Devanagari script)
  language_id=5 - Urdu
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent.parent / "database.sqlite"))
OUTPUT_DIR = Path(__file__).parent.parent / "output"
LINES_JSONL = OUTPUT_DIR / "sggs_lines.jsonl"
CHUNKS_JSONL = OUTPUT_DIR / "embedding_chunks.jsonl"

# translation_source_id -> field name
TRANSLATION_SOURCES = {
    6: "translation_pa",   # Punjabi, Prof. Sahib Singh
    4: "translation_es",   # Spanish, SikhNet
}
# transliteration language_id -> field name
TRANSLIT_LANGS = {
    1: "roman",
    4: "devanagari",
    5: "urdu",
}


def connect_db():
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def build_lookup(conn, line_ids: list[str]) -> dict[str, dict]:
    """Return {line_id: {roman, devanagari, urdu, translation_pa, translation_es}}"""
    result: dict[str, dict] = {lid: {} for lid in line_ids}

    # Batch fetch transliterations
    placeholders = ",".join("?" * len(line_ids))
    rows = conn.execute(
        f"SELECT line_id, language_id, transliteration "
        f"FROM transliterations WHERE line_id IN ({placeholders})",
        line_ids,
    ).fetchall()
    for r in rows:
        field = TRANSLIT_LANGS.get(r["language_id"])
        if field:
            result[r["line_id"]][field] = r["transliteration"]

    # Batch fetch extra translations
    src_ids = list(TRANSLATION_SOURCES.keys())
    src_ph = ",".join("?" * len(src_ids))
    rows = conn.execute(
        f"SELECT line_id, translation_source_id, translation "
        f"FROM translations WHERE line_id IN ({placeholders}) "
        f"AND translation_source_id IN ({src_ph})",
        line_ids + src_ids,
    ).fetchall()
    for r in rows:
        field = TRANSLATION_SOURCES.get(r["translation_source_id"])
        if field:
            result[r["line_id"]][field] = r["translation"]

    return result


def build_embedding_text(rec: dict) -> str:
    """Rich multilingual text for embedding: Gurmukhi + English + roman."""
    parts = []
    gurmukhi = rec.get("normalized_punjabi_text", "").strip()
    english = rec.get("normalized_english_translation", "").strip()
    roman = rec.get("roman", "").strip()
    if gurmukhi:
        parts.append(gurmukhi)
    if english:
        parts.append(english)
    if roman and roman != english:
        parts.append(roman)
    return "\n".join(parts)


def main():
    print(f"Reading {LINES_JSONL} ...")
    original_lines = []
    with open(LINES_JSONL, encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                original_lines.append(json.loads(raw))
    print(f"  {len(original_lines)} lines loaded.")

    line_ids = [r["line_id"] for r in original_lines]

    print(f"Connecting to DB (read-only): {DB_PATH}")
    conn = connect_db()

    # Process in batches to avoid SQLite variable limit (999)
    BATCH = 900
    lookup: dict[str, dict] = {}
    total = len(line_ids)
    start = time.time()
    for i in range(0, total, BATCH):
        batch = line_ids[i : i + BATCH]
        lookup.update(build_lookup(conn, batch))
        done = min(i + BATCH, total)
        elapsed = time.time() - start
        print(f"  {done}/{total} lines enriched ... ({elapsed:.1f}s)", end="\r", flush=True)
    print(f"\n  DB fetch done in {time.time()-start:.1f}s")

    conn.close()

    # Enrich records
    enriched = []
    for rec in original_lines:
        extra = lookup.get(rec["line_id"], {})
        rec = dict(rec)
        rec["roman"] = extra.get("roman", "")
        rec["devanagari"] = extra.get("devanagari", "")
        rec["urdu"] = extra.get("urdu", "")
        rec["translation_pa"] = extra.get("translation_pa", "")
        rec["translation_es"] = extra.get("translation_es", "")
        enriched.append(rec)

    # Write enriched sggs_lines.jsonl
    print(f"Writing {LINES_JSONL} ...")
    with open(LINES_JSONL, "w", encoding="utf-8") as f:
        for rec in enriched:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  {len(enriched)} lines written.")

    # Regenerate embedding_chunks.jsonl
    # One chunk per line (keep it simple; shabad-level chunks can be added later)
    print(f"Writing {CHUNKS_JSONL} ...")
    shabad_seen: dict[str, list] = {}
    chunks = []
    for rec in enriched:
        text = build_embedding_text(rec)
        chunks.append({
            "chunk_id": f"line:{rec['line_id']}",
            "chunk_type": "line",
            "text": text,
            "ang": str(rec["ang"]),
            "author": rec.get("author", ""),
            "raaga": rec.get("raaga", ""),
            "line_ids": str([rec["line_id"]]),
            "shabad_ids": str([rec["shabad_id"]]),
        })
        shabad_seen.setdefault(rec["shabad_id"], []).append(rec)

    # Also add one shabad-level chunk per shabad (richer context for topical queries)
    for shabad_id, recs in shabad_seen.items():
        # Combine all lines' english translations into one shabad chunk
        en_parts = [r.get("normalized_english_translation", "").strip() for r in recs]
        en_text = " ".join(p for p in en_parts if p)
        roman_parts = [r.get("roman", "").strip() for r in recs]
        roman_text = " ".join(p for p in roman_parts if p)
        text = en_text
        if roman_text:
            text += "\n" + roman_text
        angs = sorted({str(r["ang"]) for r in recs})
        authors = sorted({r.get("author", "") for r in recs} - {""})
        raagas = sorted({r.get("raaga", "") for r in recs} - {""})
        line_ids_list = [r["line_id"] for r in recs]
        chunks.append({
            "chunk_id": f"shabad:{shabad_id}",
            "chunk_type": "shabad",
            "text": text,
            "ang": ",".join(angs),
            "author": authors[0] if authors else "",
            "raaga": raagas[0] if raagas else "",
            "line_ids": str(line_ids_list),
            "shabad_ids": str([shabad_id]),
        })

    with open(CHUNKS_JSONL, "w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")
    print(f"  {len(chunks)} chunks written ({len(enriched)} line + {len(shabad_seen)} shabad).")
    print("Done.")


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    main()
