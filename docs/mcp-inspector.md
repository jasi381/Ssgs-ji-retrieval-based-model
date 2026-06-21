# MCP Inspector

Use MCP Inspector before submitting a release or marketplace listing.

## Local Package

```bash
npx @modelcontextprotocol/inspector sggs-mcp serve
```

With an external data directory:

```bash
SGGS_DATA_DIR=/absolute/path/to/output npx @modelcontextprotocol/inspector sggs-mcp serve
```

## Smoke Test Tools

Confirm these tools are listed and callable:

- `smart_search`
- `find_line`
- `semantic_search`
- `search_translation`
- `search_gurmukhi`
- `get_ang`
- `get_shabad`
- `search_by_author`
- `search_by_raaga`
- `get_concept`
- `get_line`

Recommended calls:

- `smart_search("das vastu le paache paave ek karan bikhot gaavave", 3)`
- `find_line("for the sake of one thing withheld", 3)`
- `get_ang(268)`
- `get_concept("Naam")`
