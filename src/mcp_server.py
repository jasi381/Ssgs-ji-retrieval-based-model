"""
SGGS MCP Server — Multilingual Edition

Exposes 11 tools for interacting with Sri Guru Granth Sahib Ji.
Supports queries in any language: English, Hindi, Punjabi, romanized Gurbani,
Gurmukhi (Unicode), Devanagari, Urdu, Spanish, or any other language.

Tools:
  smart_search      — auto-routes: quote → find_line, topic → semantic_search
  find_line         — locate a Gurbani line from any script/language quote
  semantic_search   — multilingual meaning-based search (uses local AI model)
  search_translation— ranked keyword search in English translations
  search_gurmukhi   — ranked keyword search in Gurmukhi text (or roman phonetic)
  get_ang           — full ang by number (Gurmukhi + English + Punjabi)
  get_shabad        — full shabad by ID
  search_by_author  — lines by author
  search_by_raaga   — lines by raaga
  get_concept       — theological concept (Naam, Hukam, Maya…) with sample verses
  get_line          — single line with prev/next context

IMPORTANT FOR THE AI MODEL USING THESE TOOLS:
  • Each query is fully independent. Never reuse or reference a previous tool result.
  • Always call the tool fresh — do not assume the answer from conversation history.
  • smart_search is the recommended entry point for most user questions.
  • get_ang returns text in Gurmukhi, English, AND Punjabi (ਪੰਜਾਬੀ).
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


_lines_raw   = _load_jsonl("sggs_lines.jsonl")
_shabads_raw = _load_jsonl("sggs_shabads.jsonl")
_angs_raw    = _load_jsonl("sggs_angs.jsonl")
_concepts_raw = _load_jsonl("sggs_concepts.jsonl")

# ---------------------------------------------------------------------------
# Primary indexes
# ---------------------------------------------------------------------------

line_index:    dict[str, dict] = {r["line_id"]: r   for r in _lines_raw}
shabad_index:  dict[str, dict] = {r["shabad_id"]: r for r in _shabads_raw}
ang_index:     dict[int, dict] = {r["ang"]: r        for r in _angs_raw}
concept_index: dict[str, dict] = {r["concept"].lower(): r for r in _concepts_raw}

author_index: dict[str, list[dict]] = {}
for _r in _lines_raw:
    author_index.setdefault(_r.get("author", "").lower(), []).append(_r)

raaga_index: dict[str, list[dict]] = {}
for _r in _lines_raw:
    raaga_index.setdefault(_r.get("raaga", "").lower(), []).append(_r)

# Punjabi translation per ang: ang → concatenated translation_pa from all lines
ang_pa_index: dict[int, str] = {}
for _r in _lines_raw:
    _pa = _r.get("translation_pa", "").strip()
    if _pa:
        ang_pa_index.setdefault(_r["ang"], []).append(_pa)  # type: ignore[arg-type]
ang_pa_index = {a: "\n".join(parts) for a, parts in ang_pa_index.items()}  # type: ignore[assignment]

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
    Returns empty string for all-vowel tokens; callers must filter these out.
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
    q_skels: dict[str, str],   # token → skeleton (may be "")
    target_norm: str,
    target_tok: set[str],       # Fix 8: precomputed token set
    target_skels: set[str],     # Fix 8: precomputed skeleton set (no empty strings)
) -> float:
    """
    Fuzzy token-overlap score.
    Exact token match = 1.0. Non-empty skeleton match = 0.8. No match = 0.
    Fix 3: skeleton match only awarded when q_skels[qt] is non-empty.
    """
    score = 0.0
    for qt in q_tok:
        if qt in target_tok:
            score += 1.0
        else:
            qs = q_skels[qt]
            if qs and qs in target_skels:   # Fix 3: guard empty skeleton
                score += 0.8
    return score


# Fix 8: Precompute token sets alongside skeleton sets for every line at startup.
for _r in _lines_raw:
    _r["_roman_norm"]  = _norm(_r.get("roman", ""))
    _r["_eng_norm"]    = _norm(_r.get("normalized_english_translation", ""))
    _r["_roman_toks"]  = set(_r["_roman_norm"].split())
    _r["_eng_toks"]    = set(_r["_eng_norm"].split())
    # Fix 3: filter empty skeletons out of the precomputed sets.
    _r["_roman_skels"] = {s for w in _r["_roman_toks"] if (s := _skel(w))}
    _r["_eng_skels"]   = {s for w in _r["_eng_toks"]   if (s := _skel(w))}


def _has_gurmukhi(s: str) -> bool:
    return any("਀" <= c <= "੿" for c in s)


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s)


def _has_arabic(s: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in s)


# Fix 2: Only strong question signals classify as topic.
# Removed common particles (ke, ki, ka, mein, hai, hain) which appear in Gurbani quotes.
_STRONG_META_WORDS = {
    # Hindi — unambiguous question/meta words
    "baare", "kya", "kaise", "kyun", "batao", "bata", "shiksha",
    "seekh", "arth", "paribhasha", "matlab", "iska", "uska", "kab",
    # English — unambiguous question/meta words
    "about", "what", "how", "why", "explain", "tell", "describe",
    "meaning", "teachings", "teach", "does", "says", "say",
    "define", "definition", "regarding", "concerning",
}


def _looks_like_gurbani_quote(query: str) -> bool:
    """
    Heuristic: does this look like a specific Gurbani quote to locate?

    Fix 1: Script-detected queries (Gurmukhi/Devanagari/Urdu) no longer bypass
    meta detection — smart_search falls back to semantic_search if find_line
    returns 0 results for them.

    Fix 2: Common particles (ke, ki, ka, mein…) removed from the blocklist;
    only strong question-verbs/nouns trigger topic routing.
    """
    if _has_gurmukhi(query) or _has_devanagari(query) or _has_arabic(query):
        # Script queries are quote-like by default. smart_search will fall back
        # to semantic_search if find_line returns nothing (Fix 1 fallback).
        return True

    q_norm = _norm(query)
    q_tok  = _tokens(q_norm)
    if len(q_tok) < 3:
        return False

    # Fix 2: only strong meta markers override quote detection.
    if q_tok & _STRONG_META_WORDS:
        return False

    q_skels = {t: _skel(t) for t in q_tok}
    for r in _lines_raw:
        s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_toks"], r["_roman_skels"])
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
        → find_line (lexical, deterministic). Falls back to semantic_search if
        find_line returns no results (Fix 1).
      • Otherwise (a topic, concept, or question in any language)
        → semantic_search (local AI model, language-agnostic).

    IMPORTANT: Call this fresh for every user query. Do not reuse prior results.
    Each call is fully independent of conversation history.

    Returns: matching verses with ang, author, gurmukhi, roman, translation.
    The 'routed_to' field shows which path was taken.
    """
    if _looks_like_gurbani_quote(query):
        raw  = find_line(query, limit=limit)
        data = json.loads(raw)
        # Fix 1: fall back to semantic if find_line returned nothing.
        if data.get("count", 0) == 0:
            raw  = semantic_search(query, limit=limit)
            data = json.loads(raw)
            data["routed_to"] = "semantic_search (find_line fallback)"
        else:
            data["routed_to"] = "find_line"
        return json.dumps(data, ensure_ascii=False, indent=2)
    else:
        raw  = semantic_search(query, limit=limit)
        data = json.loads(raw)
        data["routed_to"] = "semantic_search"
        return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: find_line
# ---------------------------------------------------------------------------

def _unicode_pair_score(
    q_tok_u: set[str],
    field: str,
    r1: dict,
    r2: dict,
) -> float:
    """Combined single-field token overlap for a 2-line window (Fix 4)."""
    tgt = _norm_unicode(r1.get(field, "") + " " + r2.get(field, ""))
    t_tok = set(tgt.split())
    overlap = len(q_tok_u & t_tok)
    bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
    return float(overlap) + bonus


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
    (spanning two tuks) resolve correctly — for ALL scripts (Fix 4).

    IMPORTANT: Each call is independent. Do not assume the answer from prior conversation.
    """
    is_gurmukhi   = _has_gurmukhi(quote)
    is_devanagari = _has_devanagari(quote)
    is_arabic     = _has_arabic(quote)

    if is_gurmukhi:
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})

        def _single_score(r: dict) -> float:
            tgt   = _norm_unicode(r.get("normalized_punjabi_text", ""))
            t_tok = set(tgt.split())
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(len(q_tok_u & t_tok)) + bonus

        def _pair_score(r1: dict, r2: dict) -> float:
            return _unicode_pair_score(q_tok_u, "normalized_punjabi_text", r1, r2)

    elif is_devanagari:
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})

        def _single_score(r: dict) -> float:
            tgt   = _norm_unicode(r.get("devanagari", ""))
            t_tok = set(tgt.split())
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(len(q_tok_u & t_tok)) + bonus

        def _pair_score(r1: dict, r2: dict) -> float:
            return _unicode_pair_score(q_tok_u, "devanagari", r1, r2)

    elif is_arabic:
        q_norm_u = _norm_unicode(quote)
        q_tok_u  = set(q_norm_u.split())
        if not q_tok_u:
            return json.dumps({"error": "Empty query after normalization."})

        def _single_score(r: dict) -> float:
            tgt   = _norm_unicode(r.get("urdu", ""))
            t_tok = set(tgt.split())
            bonus = 2.0 if any(qt in tgt for qt in q_tok_u) else 0.0
            return float(len(q_tok_u & t_tok)) + bonus

        def _pair_score(r1: dict, r2: dict) -> float:
            return _unicode_pair_score(q_tok_u, "urdu", r1, r2)

    else:
        # Latin (roman phonetic or English)
        q_norm  = _norm(quote)
        q_tok   = _tokens(q_norm)
        if not q_tok:
            return json.dumps({"error": "Empty query after normalization."})
        q_skels = {t: _skel(t) for t in q_tok}

        def _single_score(r: dict) -> float:
            roman_s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_toks"], r["_roman_skels"])
            eng_s   = _score_fuzzy(q_tok, q_skels, r["_eng_norm"],   r["_eng_toks"],   r["_eng_skels"])
            return max(roman_s, eng_s * 0.9)

        def _pair_score(r1: dict, r2: dict) -> float:
            combined_norm  = r1["_roman_norm"] + " " + r2["_roman_norm"]
            combined_toks  = r1["_roman_toks"]  | r2["_roman_toks"]
            combined_skels = r1["_roman_skels"] | r2["_roman_skels"]
            return _score_fuzzy(q_tok, q_skels, combined_norm, combined_toks, combined_skels)

    # Score single lines
    single_scored: dict[str, float] = {}
    for r in _lines_raw:
        s = _single_score(r)
        if s > 0:
            single_scored[r["line_id"]] = s

    # Fix 4: 2-line window for ALL scripts, not just Latin.
    pair_scored: dict[str, float] = {}
    for r in _lines_raw:
        nxt_id = r.get("next_line_id")
        if not nxt_id or nxt_id not in line_index:
            continue
        sp = _pair_score(r, line_index[nxt_id])
        if sp > 0:
            pair_scored[r["line_id"]] = sp

    # Merge: best score for each line_id
    all_scored: dict[str, tuple[float, dict]] = {}
    for r in _lines_raw:
        lid    = r["line_id"]
        s      = single_scored.get(lid, 0.0)
        sp     = pair_scored.get(lid, 0.0)
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
                "translation_pa": r.get("translation_pa", ""),
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

    # Fix 5: engine.query() is already wrapped in try/except; returns [] on any error.
    hits = _semantic_engine.query(query, k=limit * 2)

    if not hits:
        return json.dumps({
            "query": query,
            "count": 0,
            "results": [],
            "note": "Semantic engine returned no results.",
        }, ensure_ascii=False, indent=2)

    results = []
    seen_lines: set[str] = set()

    for hit in hits:
        if len(results) >= limit:
            break
        try:
            line_ids = json.loads(hit["line_ids"].replace("'", '"'))
        except Exception:
            line_ids = []

        for lid in line_ids[:1]:
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
        s = _score_fuzzy(q_tok, q_skels, r["_eng_norm"], r["_eng_toks"], r["_eng_skels"])
        if s > 0:
            scored.append((s, r))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    if not top:
        return json.dumps({"query": query, "count": 0, "lines": []}, ensure_ascii=False, indent=2)

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
    if _has_gurmukhi(query):
        scored = []
        for r in _lines_raw:
            gur = r.get("normalized_punjabi_text", "")
            if query in gur:
                scored.append((10.0, r))   # exact substring → top rank
            else:
                q_tok_u = set(_norm_unicode(query).split())
                tgt     = _norm_unicode(gur)
                t_tok   = set(tgt.split())
                s = float(len(q_tok_u & t_tok))
                if s > 0:
                    scored.append((s, r))
    else:
        q_tok   = _tokens(_norm(query))
        q_skels = {t: _skel(t) for t in q_tok}
        scored  = []
        for r in _lines_raw:
            s = _score_fuzzy(q_tok, q_skels, r["_roman_norm"], r["_roman_toks"], r["_roman_skels"])
            if s > 0:
                scored.append((s, r))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    if not top:
        return json.dumps({"query": query, "count": 0, "lines": []}, ensure_ascii=False, indent=2)

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
# Tool: get_ang  — now includes Punjabi translation (ਪੰਜਾਬੀ)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ang(ang: int) -> str:
    """
    Return the full content of a specific ang (page) of SGGS.

    Returns:
      • gurmukhi      — Gurmukhi text (Unicode)
      • translation   — English translation (Dr. Sant Singh Khalsa)
      • translation_pa— Punjabi translation / teeka (Prof. Sahib Singh)
      • roman         — Roman transliteration line-by-line
      • shabad_ids    — list of shabad IDs on this ang

    Valid range: 1–1430.

    IMPORTANT: Each call is independent. Do not reuse prior results.
    When the user asks for content of an ang in Punjabi, use translation_pa.
    """
    rec = ang_index.get(ang)
    if not rec:
        return f"Ang {ang} not found. Valid range: 1–1430."

    # Assemble per-line detail from line_index for roman + Punjabi
    shabad_ids = rec.get("shabad_ids", [])
    line_data = []
    for lid, r in line_index.items():
        if r["ang"] == ang:
            line_data.append(r)
    line_data.sort(key=lambda r: r.get("line_position", 0))

    return json.dumps({
        "ang": rec["ang"],
        "gurmukhi": rec["text_gurmukhi"],
        "translation": rec["text_translation"],
        "translation_pa": ang_pa_index.get(ang, ""),
        "lines": [
            {
                "line_id": r["line_id"],
                "gurmukhi": r["normalized_punjabi_text"],
                "roman": r.get("roman", ""),
                "translation": r["normalized_english_translation"],
                "translation_pa": r.get("translation_pa", ""),
                "author": r["author"],
            }
            for r in line_data
        ],
        "shabad_ids": shabad_ids,
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
                "translation_pa": r.get("translation_pa", ""),
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
            "translation_pa": r.get("translation_pa", ""),
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
