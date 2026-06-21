# Distribution Checklist

## Local Package

- Build and publish `sggs-mcp` as a Python package.
- Use `sggs-mcp serve` as the stable console entry point.
- Use `SGGS_DATA_DIR` for data outside the source tree.
- Keep direct script wrappers for existing local workflows.

## Data Bundle

The current source tree can use local `output/` artifacts, but public
redistribution of generated JSONL, Chroma indexes, embeddings, or archives
requires license review first.

After approval, publish a versioned data bundle and document:

```bash
sggs-mcp download-data --url https://example.org/sggs-mcp-data-vX.Y.Z.zip
sggs-mcp doctor
```

## Release Gates

- `sggs-mcp doctor` passes in a clean install.
- Smoke tests cover all 11 tools.
- MCP Inspector can connect to `sggs-mcp serve`.
- Claude Desktop config is documented.
- Codex config is documented.
- `NOTICE`, `LICENSE`, and `SECURITY.md` are present.

## Docker

Add Docker only after the local package works reliably. The image should include
the package and either mount `SGGS_DATA_DIR` or download an approved data bundle
at build/deploy time.
