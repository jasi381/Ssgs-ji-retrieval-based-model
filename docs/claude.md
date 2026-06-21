# Claude Desktop Installation

## Package Install

Install the package with your preferred Python tool:

```bash
pipx install sggs-mcp
```

If the SGGS data files are outside the package checkout, set `SGGS_DATA_DIR` to
the directory that contains `sggs_lines.jsonl`, `sggs_shabads.jsonl`,
`sggs_angs.jsonl`, `sggs_concepts.jsonl`, `embedding_chunks.jsonl`, and
`chroma/`.

## Claude Config

Edit:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Example:

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

Restart Claude Desktop after saving the file.

## Validate

```bash
SGGS_DATA_DIR=/absolute/path/to/output sggs-mcp doctor
```

Claude Desktop MCP logs are usually under `~/Library/Logs/Claude` on macOS.
