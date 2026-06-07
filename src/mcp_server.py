"""
SGGS MCP Server — Multilingual Edition

Exposes 10 tools for interacting with Sri Guru Granth Sahib Ji.
Supports queries in any language: English, Hindi, Punjabi, romanized Gurbani,
Gurmukhi (Unicode), Devanagari, Urdu, Spanish, or any other language.

Tools:
  smart_search      — auto-routes: quote → find_line, topic → semantic_search
  find_line         — locate a Gurbani line from any script/language quote
  semantic_search   — multilingual meaning-based search (uses local AI model)
  search_translation— ranked keyword search in English translations
  search_gurmukhi   — ranked keyword search in Gurmukhi text (or roman phonetic)
  get_ang           — full ang by number
  get_shabad        — full shabad by ID
  search_by_author  — lines by author
  search_by_raaga   — lines by raaga
  get_concept       — theological concept (Naam, Hukam, Maya…) with sample verses
  get_line          — single line with prev/next context

IMPORTANT FOR THE AI MODEL USING THESE TOOLS:
  • Each query is fully independent. Never reuse or reference a previous tool result.
  • Always call the tool fresh — do not assume the answer from conversation history.
  • smart_search is the recommended entry point for most user questions.
"""

from __future__ import annotations

import json
import unicodedata
import re
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "output"

def _load_jsonl(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


_lines_raw = _load_jsonl("sggs_lines.jsonl")
_shabads_raw = _load_jsonl("sggs_shabads.jsonl")
_angs_raw = _load_jsonl("sggs_angs.jsonl")
_concepts_raw = _load_jsonl("sggs_concepts.jsonl")

# ---------------------------------------------------------------------------
# Primary indexes
# ---------------------------------------------------------------------------

line_index:   dict[str, dict] = {r["line_id"]: r for r in _lines_raw}
shabad_index: dict[str, dict] = {r["shabad_id"]: r for r in _shabads_raw}
ang_index:    dict[int, dict]  = {r["ang"]: r for r in _angs_raw}
concept_index: dict[str, dict] = {r["concept"].lower(): r for r in _concepts_raw}

author_index: dict[str, list[dict]] = {}
for _r in _lines_raw:
    _k = _r.get("author", "").lower()
    author_index.setdefault(_k, []).append(_r)

raaga_index: dict[str, list[dict]] = {}
for _r in _lines_raw:
    _k = _r.get("raaga", "").lower()
    raaga_index.setdefault(_k, []).append(_r)

# ---------------------------------------------------------------------------
# Lexical helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Normalize to diacritic-free lowercase Latin (for roman/English queries)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_unicode(s: str) -> str:
    """Normalize non-Latin scripts (Gurmukhi/Devanagari/Urdu): NFKC + whitespace only."""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(s: str) -> set[str]:
    return set(s.split())


def _skel(w: str) -> str:
    """
    Consonant skeleton for phonetic fuzzy matching across Punjabi/Hindi romanizations.
    Steps: deduplicate adjacent identical chars, then strip trailing vowels.
    Examples: bikhott→bikhot, kaaran→karan, gavaavai→gavav, paachhai→pach.
    This bridges the gap between Punjabi roman (DB) and Hindi phonetic input (user).
    """
    out: list[str] = []
    for c in w:
        if not out or c != out[-1]:
            out.append(c)
    vowels = "aeiou"
    while out and out[-1] in vowels:
        out.pop()
    return "".join(out)


def _score_fuzzy(
    q_tok: set[str],
    q_skels: dict[str, str],  # token → skeleton
    target_norm: str,
    target_skels: set[str],   # set of skeletons in the target
) -> float:
    """
    Fuzzy token-overlap score.
    Exact token match = 1.0. Skeleton match = 0.8. No match = 0.
    """
    t_tok = set(target_norm.split())
    score = 0.0
    for qt in q_tok:
        if qt in t_tok:
            score += 1.0
        elif q_skels[qt] in target_skels:
            score += 0.8
    return score


# Precompute normalized fields and skeleton sets for every line at startup
for _r in _lines_raw:
    _r["_roman_norm"] = _norm(_r.get("roman", ""))
    _r["_eng_norm"]   = _norm(_r.get("normalized_english_translation", ""))
    _r["_roman_skels"] = {_skel(w) for w in _r["_roman_norm"].split() if w}
    _r["_eng_skels"]   = {_skel(w) for w in _r["_eng_norm"].split() if w}
    # Devanagari kept as-is for script detection


def _has_gurmukhi(s: str) -> bool:
    return any("਀" <= c <= "੿" for c in s)


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s)


def _has_arabic(s: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in s)


_META_QUESTION_WORDS = {
    # Hindi question/meta words — indicate a topical question, not a Gurbani quote
    "ke", "ki", "ka", "mein", "baare", "kya", "hai", "hain", "karo",
    "kaise", "kyun", "batao", "bata", "shiksha", "seekh", "matlab",
    "arth", "matlab", "paribhasha", "matlab", "iska", "uska", "kab",
    # English question/meta words
    "about", "what", "how", "why", "explain", "tell", "describe",
    "meaning", "teachings", "teach", "does", "says", "say", "define",
    "definition", "regarding", "concerning",
}


def _looks_like_gurbani_quote(query: str) -> bool:
    """
    Heuristic: does this look like a specific Gurbani quote to locate?
    True for Gurmukhi/Devanagari/Urdu queries, or Latin queries with
    ≥3 tokens that fuzzy-match the roman index with skeleton overlap ≥3,
    AND do NOT contain meta-question markers (ke, mein, baare, what, about…).
    """
    if _has_gurmukhi(query) or _has_devanagari(query) or _has_arabic(query):
        return True
    q_norm = _norm(query)
    q_tok = _tokens(q_norm)
    if len(q_tok) < 3:
        return False
    # If the query contains meta-question words, it's a topic query, not a quote
    if q_tok & _META_QUESTION_WORDS:
        return False
    q_skels = {t: _skel(t) for t in q_tok}
    # Quick scan: if any single line scores ≥3.0 (fuzzy), treat as quote
    for r in _lines_raw:
        s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_skels"])
        if s >= 3.0:
            return True
    return False


# ---------------------------------------------------------------------------
# Semantic engine (lazy-loaded)
# ---------------------------------------------------------------------------

from search_engine import engine as _semantic_engine  # noqa: E402

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("SGGS-Multilingual")


# ---------------------------------------------------------------------------
# Tool: smart_search
# ---------------------------------------------------------------------------

@mcp.tool()
def smart_search(query: str, limit: int = 5) -> str:
    """
    Intelligent multilingual search — use this as your primary entry point.

    Accepts queries in ANY language: English, Hindi, Punjabi, romanized Gurbani,
    Gurmukhi, Devanagari, Urdu, Spanish, or any other language.

    Auto-routes:
      • If the query looks like a specific Gurbani quote (to locate its ang/page)
        → calls find_line internally (lexical, deterministic, no AI model needed).
      • Otherwise (a topic, concept, or question in any language)
        → calls semantic_search internally (local AI model, language-agnostic).

    IMPORTANT: Call this fresh for every user query. Do not reuse prior results.
    Each call is fully independent of conversation history.

    Returns: list of matching verses with ang, author, gurmukhi, roman, translation.
    The 'routed_to' field tells you which path was taken.
    """
    if _looks_like_gurbani_quote(query):
        raw = find_line(query, limit=limit)
        data = json.loads(raw)
        data["routed_to"] = "find_line"
        return json.dumps(data, ensure_ascii=False, indent=2)
    else:
        raw = semantic_search(query, limit=limit)
        data = json.loads(raw)
        data["routed_to"] = "semantic_search"
        return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: find_line
# ---------------------------------------------------------------------------

@mcp.tool()
def find_line(quote: str, limit: int = 5) -> str:
    """
    Locate the ang (page) of a specific Gurbani line given a partial quote.

    Accepts the quote in ANY script:
      • Romanized phonetic — Punjabi or Hindi style (e.g. "ek karan bikhot gaavave",
        "das vastu le paache paave")
      • Gurmukhi Unicode (e.g. "ਏਕ ਵਸਤੁ ਕਾਰਨਿ ਬਿਖੋਟਿ ਗਵਾਵੈ")
      • Devanagari (e.g. "एक बसतु कारनि बिखोटि गवावै")
      • Urdu script
      • English translation fragment (e.g. "forfeits his faith for the sake")

    Uses fuzzy consonant-skeleton token scoring against native BaniDB roman
    transliterations. Also searches consecutive-line pairs so multi-line quotes
    (spanning two tuks) resolve correctly.

    IMPORTANT: Each call is independent. Do not assume the answer from prior conversation.
    """
    if _has_gurmukhi(quote):
        # Gurmukhi: exact Unicode substring / token matching (no Latin norm needed)
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})
        def _single_score(r: dict) -> float:
            tgt = _norm_unicode(r.get("normalized_punjabi_text", ""))
            t_tok = set(tgt.split())
            overlap = len(q_tok_u & t_tok)
            # substring bonus
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(overlap) + bonus
        q_tok  = q_tok_u
        q_skels = {}
    elif _has_devanagari(quote):
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})
        def _single_score(r: dict) -> float:
            tgt = _norm_unicode(r.get("devanagari", ""))
            t_tok = set(tgt.split())
            overlap = len(q_tok_u & t_tok)
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(overlap) + bonus
        q_tok  = q_tok_u
        q_skels = {}
    elif _has_arabic(quote):
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})
        def _single_score(r: dict) -> float:
            tgt = _norm_unicode(r.get("urdu", ""))
            t_tok = set(tgt.split())
            overlap = len(q_tok_u & t_tok)
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(overlap) + bonus
        q_tok  = q_tok_u
        q_skels = {}
    else:
        q_norm = _norm(quote)
        q_tok  = _tokens(q_norm)
        if not q_tok:
            return json.dumps({"error": "Empty query after normalization."})
        q_skels = {t: _skel(t) for t in q_tok}
        # Latin (roman phonetic or English) — match roman first, then english
        def _single_score(r: dict) -> float:
            roman_s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_skels"])
            eng_s   = _score_fuzzy(q_tok, q_skels, r["_eng_norm"],   r["_eng_skels"])
            return max(roman_s, eng_s * 0.9)  # roman wins ties; english slightly discounted

    # Score single lines
    single_scored: dict[str, float] = {}
    for r in _lines_raw:
        s = _single_score(r)
        if s > 0:
            single_scored[r["line_id"]] = s

    # Score 2-line windows (handles multi-tuk quotes like the das-vastu case)
    # A window gets the max of its two constituent lines, plus overlap bonus.
    pair_scored: dict[str, float] = {}  # key = first line_id
    if not (_has_gurmukhi(quote) or _has_devanagari(quote) or _has_arabic(quote)):
        for r in _lines_raw:
            nxt_id = r.get("next_line_id")
            if not nxt_id or nxt_id not in line_index:
                continue
            nxt = line_index[nxt_id]
            # Combine roman norms
            combined_norm = r["_roman_norm"] + " " + nxt["_roman_norm"]
            combined_skels = r["_roman_skels"] | nxt["_roman_skels"]
            s_pair = _score_fuzzy(q_tok, q_skels, combined_norm, combined_skels)
            if s_pair > 0:
                pair_scored[r["line_id"]] = s_pair

    # Merge: best score for each line_id
    all_scored: dict[str, tuple[float, dict]] = {}
    for r in _lines_raw:
        lid = r["line_id"]
        s = single_scored.get(lid, 0.0)
        # Pair score: if this line is first in a high-scoring pair, boost it
        sp = pair_scored.get(lid, 0.0)
        # Pair score for when this line is SECOND in a pair (check prev)
        prev_id = r.get("previous_line_id")
        if prev_id:
            sp = max(sp, pair_scored.get(prev_id, 0.0))
        best = max(s, sp)
        if best > 0:
            all_scored[lid] = (best, r)

    top = sorted(all_scored.values(), key=lambda x: -x[0])[:limit]

    if not top:
        return json.dumps({
            "query": quote,
            "count": 0,
            "results": [],
            "note": "No matching lines found. Try different spelling or script.",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "query": quote,
        "count": len(top),
        "results": [
            {
                "score": round(s, 2),
                "ang": r["ang"],
                "line_id": r["line_id"],
                "shabad_id": r["shabad_id"],
                "author": r["author"],
                "raaga": r["raaga"],
                "gurmukhi": r["normalized_punjabi_text"],
                "roman": r.get("roman", ""),
                "translation": r["normalized_english_translation"],
            }
            for s, r in top
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: semantic_search
# ---------------------------------------------------------------------------

@mcp.tool()
def semantic_search(query: str, limit: int = 8) -> str:
    """
    Multilingual meaning-based search across the entire SGGS corpus.

    Works with ANY language — type your query in English, Hindi, Punjabi,
    Spanish, Urdu, or any other language. Returns the most semantically
    relevant verses, not just keyword matches.

    Ideal for:
      • Topical questions: "kaam ke baare mein shiksha" (Hindi)
      • Thematic search: "teachings about ego and pride"
      • Conceptual queries: "what does SGGS say about forgiveness?"
      • Any language: "¿qué enseña el Gurú sobre el amor?" (Spanish)

    Uses the local intfloat/multilingual-e5-base model (offline, no API key).

    IMPORTANT: Each call is fully independent. Do not reference previous results.
    Run this tool fresh for every new question — never assume from conversation history.
    """
    if not _semantic_engine.is_ready():
        return json.dumps({
            "error": f"Semantic engine not ready: {_semantic_engine.status()}",
            "fallback": "Use search_translation for keyword-based English search.",
        }, ensure_ascii=False, indent=2)

    hits = _semantic_engine.query(query, k=limit * 2)  # over-fetch, dedupe by ang

    # Resolve line IDs to full verse data; prefer line-level chunks
    results = []
    seen_lines: set[str] = set()

    for hit in hits:
        if len(results) >= limit:
            break
        try:
            line_ids = json.loads(hit["line_ids"].replace("'", '"'))
        except Exception:
            line_ids = []

        for lid in line_ids[:1]:  # take first line of chunk for display
            if lid in seen_lines:
                continue
            seen_lines.add(lid)
            r = line_index.get(lid)
            if not r:
                continue
            results.append({
                "ang": r["ang"],
                "line_id": r["line_id"],
                "shabad_id": r["shabad_id"],
                "author": r["author"],
                "raaga": r["raaga"],
                "gurmukhi": r["normalized_punjabi_text"],
                "roman": r.get("roman", ""),
                "translation": r["normalized_english_translation"],
                "translation_pa": r.get("translation_pa", ""),
                "relevance_score": round(1 - hit["distance"], 4),
            })

    return json.dumps({
        "query": query,
        "count": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: search_translation (ranked, full-scan)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_translation(query: str, limit: int = 10) -> str:
    """
    Ranked keyword search across English translations of SGGS.

    Accepts English keywords or phrases. Returns the best matching lines ranked
    by token overlap — not just the first N substring matches.

    For multilingual or conceptual queries, prefer smart_search or semantic_search.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    q_tok = _tokens(_norm(query))
    if not q_tok:
        return json.dumps({"error": "Empty query."})

    q_skels = {t: _skel(t) for t in q_tok}
    scored = []
    for r in _lines_raw:
        s = _score_fuzzy(q_tok, q_skels, r["_eng_norm"], r["_eng_skels"])
        if s > 0:
            scored.append((s, r))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    if not top:
        return json.dumps({
            "query": query,
            "count": 0,
            "lines": [],
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "query": query,
        "count": len(top),
        "lines": [
            {
                "score": round(s, 2),
                "line_id": r["line_id"],
                "author": r["author"],
                "raaga": r["raaga"],
                "ang": r["ang"],
                "gurmukhi": r["normalized_punjabi_text"],
                "translation": r["normalized_english_translation"],
            }
            for s, r in top
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: search_gurmukhi (ranked, handles roman input too)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_gurmukhi(query: str, limit: int = 10) -> str:
    """
    Ranked search in Gurmukhi text or roman transliterations.

    Accepts:
      • Unicode Gurmukhi text (exact/partial)
      • Romanized phonetic (matched against native roman transliterations)

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    q_tok = _tokens(_norm(query))
    q_skels = {t: _skel(t) for t in q_tok}
    if _has_gurmukhi(query):
        # Exact substring match in Gurmukhi gets big bonus; fallback fuzzy
        scored = []
        for r in _lines_raw:
            gur = r.get("normalized_punjabi_text", "")
            if query in gur:
                tgt = _norm(gur)
                tgt_s = {_skel(w) for w in tgt.split() if w}
                s = _score_fuzzy(q_tok, q_skels, tgt, tgt_s)
                scored.append((s + 10, r))  # bonus for exact substring
            else:
                tgt = _norm(gur)
                tgt_s = {_skel(w) for w in tgt.split() if w}
                s = _score_fuzzy(q_tok, q_skels, tgt, tgt_s)
                if s > 0:
                    scored.append((s, r))
    else:
        # Latin query: match roman_norm with fuzzy skeleton
        scored = []
        for r in _lines_raw:
            s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_skels"])
            if s > 0:
                scored.append((s, r))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    if not top:
        return json.dumps({
            "query": query,
            "count": 0,
            "lines": [],
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "query": query,
        "count": len(top),
        "lines": [
            {
                "score": round(s, 2),
                "line_id": r["line_id"],
                "author": r["author"],
                "raaga": r["raaga"],
                "ang": r["ang"],
                "gurmukhi": r["normalized_punjabi_text"],
                "roman": r.get("roman", ""),
                "translation": r["normalized_english_translation"],
            }
            for s, r in top
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: get_ang
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ang(ang: int) -> str:
    """
    Return the full content of a specific ang (page) of SGGS.

    Returns Gurmukhi text, English translation, and shabad IDs for that ang.
    Valid range: 1–1430.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    rec = ang_index.get(ang)
    if not rec:
        return f"Ang {ang} not found. Valid range: 1–1430."
    return json.dumps({
        "ang": rec["ang"],
        "gurmukhi": rec["text_gurmukhi"],
        "translation": rec["text_translation"],
        "shabad_ids": rec["shabad_ids"],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: get_shabad
# ---------------------------------------------------------------------------

@mcp.tool()
def get_shabad(shabad_id: str) -> str:
    """
    Return a full shabad (hymn): all lines, author, raaga, Gurmukhi, and translation.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
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
        "lines": [
            {
                "line_id": l["line_id"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "roman": l.get("roman", ""),
                "translation": l["normalized_english_translation"],
                "translation_pa": l.get("translation_pa", ""),
            }
            for l in lines
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: search_by_author
# ---------------------------------------------------------------------------

@mcp.tool()
def search_by_author(author: str, limit: int = 10) -> str:
    """
    Return up to `limit` lines written by the given author (case-insensitive partial match).

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    key = author.lower()
    matches = []
    for stored_key, lines in author_index.items():
        if key in stored_key:
            matches.extend(lines)
    if not matches:
        return json.dumps({"error": f"No lines found for author matching '{author}'."})
    return json.dumps({
        "query_author": author,
        "count": len(matches[:limit]),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "roman": l.get("roman", ""),
                "translation": l["normalized_english_translation"],
            }
            for l in matches[:limit]
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: search_by_raaga
# ---------------------------------------------------------------------------

@mcp.tool()
def search_by_raaga(raaga: str, limit: int = 10) -> str:
    """
    Return up to `limit` lines in the given raaga (case-insensitive partial match).

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    key = raaga.lower()
    matches = []
    for stored_key, lines in raaga_index.items():
        if key in stored_key:
            matches.extend(lines)
    if not matches:
        return json.dumps({"error": f"No lines found for raaga matching '{raaga}'."})
    return json.dumps({
        "query_raaga": raaga,
        "count": len(matches[:limit]),
        "lines": [
            {
                "line_id": l["line_id"],
                "author": l["author"],
                "raaga": l["raaga"],
                "ang": l["ang"],
                "gurmukhi": l["normalized_punjabi_text"],
                "roman": l.get("roman", ""),
                "translation": l["normalized_english_translation"],
            }
            for l in matches[:limit]
        ],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: get_concept
# ---------------------------------------------------------------------------

@mcp.tool()
def get_concept(concept: str) -> str:
    """
    Return all information about a theological concept in SGGS, including sample verses.

    Available concepts: Naam, Hukam, Maya, Haumai, Seva, Simran, Satguru, Mukti,
    Anand, Prem, Bhagti, Giaan, Kirpa, Sangat, Sach, Gurbani.

    Returns line count, shabad count, ang count, and the first 5 matching verses
    with full Gurmukhi + translation.

    For concepts not in this list (e.g. Kaam/lust, Krodh/anger), use semantic_search.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    key = concept.lower()
    rec = concept_index.get(key)
    if not rec:
        available = sorted(concept_index.keys())
        return json.dumps({
            "error": f"Concept '{concept}' not found.",
            "available": available,
            "tip": "For concepts not in this list, use semantic_search.",
        }, ensure_ascii=False, indent=2)

    # Resolve first 5 line_ids to full verse text
    sample_lines = []
    for lid in rec["line_ids"][:5]:
        r = line_index.get(lid)
        if r:
            sample_lines.append({
                "line_id": r["line_id"],
                "ang": r["ang"],
                "author": r["author"],
                "gurmukhi": r["normalized_punjabi_text"],
                "roman": r.get("roman", ""),
                "translation": r["normalized_english_translation"],
            })

    return json.dumps({
        "concept": rec["concept"],
        "line_count": len(rec["line_ids"]),
        "shabad_count": len(rec.get("shabad_ids", [])),
        "ang_count": len(rec.get("angs", [])),
        "sample_verses": sample_lines,
        "all_line_ids": rec["line_ids"],
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: get_line
# ---------------------------------------------------------------------------

@mcp.tool()
def get_line(line_id: str) -> str:
    """
    Return full detail for a single SGGS line plus its previous and next lines.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    """
    rec = line_index.get(line_id.upper())
    if not rec:
        return f"Line '{line_id}' not found."

    def _brief(r: dict) -> dict:
        return {
            "line_id": r["line_id"],
            "ang": r["ang"],
            "gurmukhi": r["normalized_punjabi_text"],
            "roman": r.get("roman", ""),
            "translation": r["normalized_english_translation"],
        }

    prev_line = None
    next_line = None
    if rec.get("previous_line_id") and rec["previous_line_id"] in line_index:
        prev_line = _brief(line_index[rec["previous_line_id"]])
    if rec.get("next_line_id") and rec["next_line_id"] in line_index:
        next_line = _brief(line_index[rec["next_line_id"]])

    return json.dumps({
        "line_id": rec["line_id"],
        "ang": rec["ang"],
        "shabad_id": rec["shabad_id"],
        "author": rec["author"],
        "raaga": rec["raaga"],
        "gurmukhi": rec["normalized_punjabi_text"],
        "roman": rec.get("roman", ""),
        "devanagari": rec.get("devanagari", ""),
        "translation": rec["normalized_english_translation"],
        "translation_pa": rec.get("translation_pa", ""),
        "line_position": rec["line_position"],
        "previous_line": prev_line,
        "next_line": next_line,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
