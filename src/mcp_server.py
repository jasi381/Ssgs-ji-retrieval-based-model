import json
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

DATA_DIR = Path(__file__).parent.parent / "output"

def _load_jsonl(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

# Load all datasets at startup
_lines_raw = _load_jsonl("sggs_lines.jsonl")
_shabads_raw = _load_jsonl("sggs_shabads.jsonl")
_angs_raw = _load_jsonl("sggs_angs.jsonl")
_concepts_raw = _load_jsonl("sggs_concepts.jsonl")

# Build indexes
line_index: dict[str, dict] = {r["line_id"]: r for r in _lines_raw}
shabad_index: dict[str, dict] = {r["shabad_id"]: r for r in _shabads_raw}
ang_index: dict[int, dict] = {r["ang"]: r for r in _angs_raw}
concept_index: dict[str, dict] = {r["concept"].lower(): r for r in _concepts_raw}

author_index: dict[str, list[dict]] = {}
for r in _lines_raw:
    key = r.get("author", "").lower()
    author_index.setdefault(key, []).append(r)

raaga_index: dict[str, list[dict]] = {}
for r in _lines_raw:
    key = r.get("raaga", "").lower()
    raaga_index.setdefault(key, []).append(r)

mcp = FastMCP("SGGS")


@mcp.tool()
def get_ang(ang: int) -> str:
    """Return full ang content: Gurmukhi text, English translation, and shabad IDs."""
    rec = ang_index.get(ang)
    if not rec:
        return f"Ang {ang} not found. Valid range: 1–1430."
    return json.dumps({
        "ang": rec["ang"],
        "gurmukhi": rec["text_gurmukhi"],
        "translation": rec["text_translation"],
        "shabad_ids": rec["shabad_ids"],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_shabad(shabad_id: str) -> str:
    """Return full shabad: all lines, author, raaga, Gurmukhi, and translation."""
    rec = shabad_index.get(shabad_id.upper())
    if not rec:
        return f"Shabad '{shabad_id}' not found."
    lines = [line_index[lid] for lid in rec["line_ids"] if lid in line_index]
    return json.dumps({
        "shabad_id": rec["shabad_id"],
        "author": rec["author"],
        "raaga": rec["raaga"],
        "start_ang": rec["start_ang"],
        "end_ang": rec["end_ang"],
        "full_gurmukhi": rec["full_gurmukhi"],
        "full_translation": rec["full_translation"],
        "lines": [
            {
                "line_id": l["line_id"],
                "gurmukhi": l["normalized_punjabi_text"],
                "translation": l["normalized_english_translation"],
                "ang": l["ang"],
                "position": l["line_position"],
            }
            for l in lines
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def search_by_author(author: str, limit: int = 10) -> str:
    """Return up to `limit` lines written by the given author (case-insensitive partial match)."""
    key = author.lower()
    matches = []
    for stored_key, lines in author_index.items():
        if key in stored_key:
            matches.extend(lines)
    if not matches:
        return f"No lines found for author matching '{author}'."
    matches = matches[:limit]
    return json.dumps({
        "query_author": author,
        "count": len(matches),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "translation": l["normalized_english_translation"],
            }
            for l in matches
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def search_by_raaga(raaga: str, limit: int = 10) -> str:
    """Return up to `limit` lines in the given raaga (case-insensitive partial match)."""
    key = raaga.lower()
    matches = []
    for stored_key, lines in raaga_index.items():
        if key in stored_key:
            matches.extend(lines)
    if not matches:
        return f"No lines found for raaga matching '{raaga}'."
    matches = matches[:limit]
    return json.dumps({
        "query_raaga": raaga,
        "count": len(matches),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "translation": l["normalized_english_translation"],
            }
            for l in matches
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def search_translation(query: str, limit: int = 10) -> str:
    """Full-text search across English translations (case-insensitive substring match)."""
    key = query.lower()
    matches = []
    for l in _lines_raw:
        translation = l.get("normalized_english_translation", "") or l.get("english_translation", "")
        if key in translation.lower():
            matches.append(l)
            if len(matches) >= limit:
                break
    if not matches:
        return f"No translations found matching '{query}'."
    return json.dumps({
        "query": query,
        "count": len(matches),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "translation": l["normalized_english_translation"],
            }
            for l in matches
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def search_gurmukhi(query: str, limit: int = 10) -> str:
    """Full-text search across Unicode Gurmukhi text (substring match)."""
    matches = []
    for l in _lines_raw:
        gurmukhi = l.get("normalized_punjabi_text", "") or l.get("punjabi_text", "")
        if query in gurmukhi:
            matches.append(l)
            if len(matches) >= limit:
                break
    if not matches:
        return f"No Gurmukhi text found matching '{query}'."
    return json.dumps({
        "query": query,
        "count": len(matches),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "translation": l["normalized_english_translation"],
            }
            for l in matches
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_concept(concept: str) -> str:
    """Return all line_ids and angs associated with a theological concept (e.g. Naam, Hukam, Maya)."""
    key = concept.lower()
    rec = concept_index.get(key)
    if not rec:
        available = sorted(concept_index.keys())
        return f"Concept '{concept}' not found. Available: {available}"
    return json.dumps({
        "concept": rec["concept"],
        "line_count": len(rec["line_ids"]),
        "shabad_count": len(rec.get("shabad_ids", [])),
        "ang_count": len(rec.get("angs", [])),
        "line_ids": rec["line_ids"],
        "shabad_ids": rec.get("shabad_ids", []),
        "angs": rec.get("angs", []),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_line(line_id: str) -> str:
    """Return full detail for a single line plus its previous and next lines."""
    rec = line_index.get(line_id.upper())
    if not rec:
        return f"Line '{line_id}' not found."

    prev_line = None
    next_line = None
    if rec.get("previous_line_id") and rec["previous_line_id"] in line_index:
        p = line_index[rec["previous_line_id"]]
        prev_line = {
            "line_id": p["line_id"],
            "gurmukhi": p["normalized_punjabi_text"],
            "translation": p["normalized_english_translation"],
        }
    if rec.get("next_line_id") and rec["next_line_id"] in line_index:
        n = line_index[rec["next_line_id"]]
        next_line = {
            "line_id": n["line_id"],
            "gurmukhi": n["normalized_punjabi_text"],
            "translation": n["normalized_english_translation"],
        }

    return json.dumps({
        "line_id": rec["line_id"],
        "ang": rec["ang"],
        "shabad_id": rec["shabad_id"],
        "author": rec["author"],
        "raaga": rec["raaga"],
        "gurmukhi": rec["normalized_punjabi_text"],
        "translation": rec["normalized_english_translation"],
        "line_position": rec["line_position"],
        "shabad_position": rec["shabad_position"],
        "previous_line": prev_line,
        "next_line": next_line,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
