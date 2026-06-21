# SGGS Multilingual AI — MCP Retrieval Server
mcp-name: io.github.jasi381/sggs-mcp

Semantic search and retrieval system for Sri Guru Granth Sahib Ji.  
Built on [BaniDB](https://github.com/KhalisFoundation/BaniDB) by Khalis Foundation.

---

## What It Does

Ask about Gurbani with exact quotes, phonetic romanized text, Gurmukhi, Devanagari, Urdu, English translation fragments, and selected topical queries. Results include the verse, Ang, author, and Punjabi teekas when present in BaniDB.

```
Query:  "das vastu le paache paave ek karan bikhot gaavave"
Result: Ang 268 · Guru Arjan Dev Ji · Raag Gauree  ← rank 1, score 7.0
```

```
Query:  "for the sake of one thing withheld"
Result: Ang 268 · Guru Arjan Dev Ji · Raag Gauree  ← English translation fragment match
```

---

## Architecture

```
Claude Desktop / any LLM
        │  MCP (Model Context Protocol)
        ▼
  src/mcp_server.py          ← 11 tools
  ├── smart_search()         ← auto-routes: quote → find_line, topic → semantic_search
  ├── find_line()            ← fuzzy phonetic locator (any script)
  ├── semantic_search()      ← multilingual-e5-base + ChromaDB
  ├── get_ang()              ← full Ang with Punjabi teekas
  ├── get_shabad()
  ├── search_gurmukhi()
  ├── search_translation()
  ├── get_concept()
  ├── search_by_author()
  ├── search_by_raaga()
  └── get_line()
        │
  src/search_engine.py       ← lazy-loading semantic engine
        │
  output/chroma/             ← 66,104 embeddings (ChromaDB, local)
```

**Embedding model:** `intfloat/multilingual-e5-base` — runs locally after the one-time model download/cache step. No hosted inference API is required.

---

## Corpus

| Dataset | Count |
|---|---|
| Lines | 60,555 |
| Shabads | 5,549 |
| Angs | 1,430 (complete SGGS) |
| Embedding chunks | 66,104 |
| Training QA pairs | 60,021 |

**Per line:** Gurmukhi · Roman transliteration · Devanagari · Urdu · English translation (Dr. Sant Singh Khalsa) · Punjabi teeka (Prof. Sahib Singh) · Spanish (SikhNet)

All sourced from BaniDB (`source_id = 1`, SGGS only).

The generated `output/` artifacts are ignored by git in this repo. Clone users must regenerate them from BaniDB or obtain them through a separate release/dataset package.

---

## Review Status

The corpus is sourced from BaniDB (`source_id = 1`) and the code includes deterministic retrieval tools for quote and Ang lookup. A formal scholar-review report is not included in this repository yet, so review claims should be added only after that artifact exists.

---

## Install

### Option A: package install

```bash
pipx install sggs-mcp
```

Run the server:

```bash
sggs-mcp serve
```

### Option B: local checkout

```bash
pip install -e ".[dev]"
sggs-mcp doctor
```

The legacy direct scripts still work from a checkout:

```bash
python3 src/mcp_server.py
python3 scripts/extract_multilingual.py
python3 scripts/build_index.py
```

## Data Setup

The server needs generated data files in `output/` or in the directory pointed
to by `SGGS_DATA_DIR`.

Required files:

- `sggs_lines.jsonl`
- `sggs_shabads.jsonl`
- `sggs_angs.jsonl`
- `sggs_concepts.jsonl`
- `embedding_chunks.jsonl`
- `chroma/`

Validate the runtime:

```bash
SGGS_DATA_DIR=/path/to/output sggs-mcp doctor
```

Build the semantic index from a local BaniDB database:

```bash
sggs-mcp extract-multilingual
sggs-mcp build-index
```

Requires `database.sqlite` (BaniDB) at project root or set the `DB_PATH` env var:

```bash
DB_PATH=/path/to/database.sqlite sggs-mcp extract-multilingual
```

Public data-bundle downloads are intentionally not hard-coded until corpus and
translation redistribution rights are reviewed:

```bash
sggs-mcp download-data --url https://example.org/approved-data-bundle.zip
```

## Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sggs-multilingual": {
      "command": "sggs-mcp",
      "args": ["serve"],
      "env": {
        "SGGS_DATA_DIR": "/absolute/path/to/output"
      }
    }
  }
}
```

Restart Claude Desktop. Tools appear as `sggs-multilingual`.

More detail: [docs/claude.md](docs/claude.md)

## Codex

Codex can run this server as a local stdio MCP:

```bash
codex mcp add sggs --env SGGS_DATA_DIR=/absolute/path/to/output -- sggs-mcp serve
```

More detail: [docs/codex.md](docs/codex.md)

## MCP Inspector

```bash
SGGS_DATA_DIR=/absolute/path/to/output npx @modelcontextprotocol/inspector sggs-mcp serve
```

More detail: [docs/mcp-inspector.md](docs/mcp-inspector.md)

## Distribution Status

The code is packaged for local Python distribution through `sggs-mcp`. Generated
corpus artifacts are not licensed by this repository's MIT license. Complete the
source-license review in [NOTICE](NOTICE) before publishing JSONL, embeddings,
Chroma indexes, or hosted data bundles.

Publishing guide: [docs/publishing.md](docs/publishing.md)

---

## How the Search Works

### Quote locator (`find_line`)
1. Detect script: Gurmukhi / Devanagari / Latin
2. Normalize: NFKD → strip diacritics → lowercase (Latin); NFKC + whitespace (Devanagari/Gurmukhi)
3. Consonant-skeleton fuzzy scoring: bridges Hindi `vastu` ↔ Punjabi `basat` (same Gurmukhi ਵਸਤੁ)
4. 2-line window: scores consecutive line pairs — handles multi-tuk quotes

### Semantic search
- Embeds query with `"query: "` prefix (e5 convention)
- ChromaDB cosine similarity over 66,104 passage embeddings
- Returns top-k with ang, author, raaga, translations

### Smart routing (`smart_search`)
- Gurmukhi/Devanagari codepoints → `find_line`
- High roman token overlap with corpus → `find_line`
- Strong meta-question markers (`baare`, `kya`, `about`, `explain`…) → `semantic_search`
- `find_line` returns 0 results → fallback to `semantic_search`

---

## Training Dataset

`output/training_dataset.jsonl` — 60,021 generated QA pairs.  
Format: `{"question": "...", "answer": "...", "ang": 268, "author": "..."}`

Potentially useful for experiments or fine-tuning after license review, quality evaluation, and scholar review.

---

## Source

Data sourced from [BaniDB](https://github.com/KhalisFoundation/BaniDB) by Khalis Foundation.  
Translations: Dr. Sant Singh Khalsa · Prof. Sahib Singh · SikhNet.

---

*Waheguru Ji Ka Khalsa, Waheguru Ji Ki Fateh*
