# Codex MCP Installation

Codex supports local stdio MCP servers and shared MCP configuration through
`~/.codex/config.toml` or a trusted project `.codex/config.toml`.

## Add With CLI

```bash
codex mcp add sggs --env SGGS_DATA_DIR=/absolute/path/to/output -- sggs-mcp serve
```

If using `uvx` instead of a global install:

```bash
codex mcp add sggs --env SGGS_DATA_DIR=/absolute/path/to/output -- uvx sggs-mcp serve
```

## Manual `config.toml`

```toml
[mcp_servers.sggs]
command = "sggs-mcp"
args = ["serve"]
env = { SGGS_DATA_DIR = "/absolute/path/to/output" }
startup_timeout_sec = 30
tool_timeout_sec = 120
```

Use `/mcp` in the Codex TUI to inspect active MCP servers.

## Validate

```bash
SGGS_DATA_DIR=/absolute/path/to/output sggs-mcp doctor
```
