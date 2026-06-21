# Publishing Guide

This guide covers publishing `sggs-mcp` for real users through package managers,
MCP discovery surfaces, Claude Desktop, and Codex.

## Current Distribution Model

Publish in this order:

1. **GitHub repository** for source, docs, issues, and releases.
2. **PyPI** for the installable `sggs-mcp` Python package.
3. **Official MCP Registry** for MCP server discovery metadata.
4. **Claude Desktop and Codex docs** for client setup.
5. **Community MCP directories** after the package and registry entry are stable.

Claude Desktop and Codex do not need a hosted remote server for local stdio use.
They can launch:

```bash
sggs-mcp serve
```

## Before Publishing

Run these checks from the repo root:

```bash
python3 -m pytest -q
sggs-mcp doctor
printf '' | sggs-mcp serve
python3 -m build
```

Confirm the build artifacts exist:

```bash
ls dist/
```

Expected:

```text
sggs_mcp-0.1.0-py3-none-any.whl
sggs_mcp-0.1.0.tar.gz
```

## Data Licensing Gate

Do not publish generated corpus artifacts until source permissions are verified.

This includes:

- `output/*.jsonl`
- `output/chroma/`
- generated embeddings
- generated training data
- data zip/tar bundles
- hosted API responses containing restricted translations

The MIT license in this repository applies to code and docs only. See
[`NOTICE`](../NOTICE).

Until rights are confirmed, publish code only and require users to build data
locally from an authorized BaniDB copy:

```bash
DB_PATH=/path/to/database.sqlite sggs-mcp extract-multilingual
sggs-mcp build-index
```

## GitHub Release

Create a release tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Suggested release notes:

```text
Initial packaged release of SGGS MCP.

- Adds `sggs-mcp` console command.
- Supports local stdio MCP via `sggs-mcp serve`.
- Supports external data with `SGGS_DATA_DIR`.
- Includes Claude Desktop, Codex, and MCP Inspector setup docs.
- Data artifacts are not bundled pending corpus redistribution review.
```

Attach `dist/sggs_mcp-0.1.0-py3-none-any.whl` and
`dist/sggs_mcp-0.1.0.tar.gz` only if you want GitHub release downloads in
addition to PyPI.

## PyPI Publishing

Install publishing tools:

```bash
python3 -m pip install --upgrade build twine
```

Build clean artifacts:

```bash
rm -rf dist/ build/ src/*.egg-info
python3 -m build
```

Check package metadata:

```bash
python3 -m twine check dist/*
```

Upload to TestPyPI first:

```bash
python3 -m twine upload --repository testpypi dist/*
```

Install from TestPyPI in a clean environment:

```bash
python3 -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ sggs-mcp
sggs-mcp --version
```

Upload to PyPI:

```bash
python3 -m twine upload dist/*
```

After publishing, the install command becomes:

```bash
pipx install sggs-mcp
```

## MCP Registry

The official MCP Registry is the right discovery target for MCP servers. It
stores server metadata and points users to package artifacts such as PyPI,
Docker, npm, or source repos.

Recommended package identity format:

```text
io.github.<github-username>/sggs-mcp
```

Before registry publishing, add the registry name marker to `README.md`:

```text
mcp-name: io.github.<github-username>/sggs-mcp
```

Then use the registry publisher:

```bash
mcp-publisher init
mcp-publisher login github
mcp-publisher publish
```

During `init`, choose the Python/PyPI package transport and point the server
command at:

```bash
sggs-mcp serve
```

The generated `server.json` should describe:

- server name and description
- package source: PyPI package `sggs-mcp`
- runtime command: `sggs-mcp serve`
- environment variable: `SGGS_DATA_DIR`
- license: MIT for code
- data licensing warning from `NOTICE`
- repository URL

Do not claim bundled data availability unless an approved data bundle exists.

## Claude Desktop Distribution

Claude Desktop users can install through PyPI and configure the local stdio
server manually.

Document this config:

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

Keep [`docs/claude.md`](claude.md) as the canonical user setup page.

## Codex Distribution

Codex users can add the server with:

```bash
codex mcp add sggs --env SGGS_DATA_DIR=/absolute/path/to/output -- sggs-mcp serve
```

Keep [`docs/codex.md`](codex.md) as the canonical Codex setup page.

## Community Directories

After PyPI and MCP Registry are live, submit to community discovery sites.

Useful targets:

- Smithery
- PulseMCP
- MCP.so
- Glama
- GitHub topics: `mcp-server`, `model-context-protocol`, `gurbani`

Use the same description everywhere:

```text
Multilingual MCP retrieval server for Sri Guru Granth Sahib Ji. Supports
Gurmukhi, romanized Gurbani, Devanagari, Urdu, English translation fragments,
Ang lookup, shabad lookup, and local semantic search.
```

Include this caveat:

```text
Corpus artifacts are not bundled pending source-license review. Users must set
SGGS_DATA_DIR to an approved local data directory.
```

## Hosted Remote MCP Later

A remote Streamable HTTP MCP is optional and should come after local package
distribution is stable.

Before hosting publicly, add:

- auth
- rate limits
- request logging
- abuse monitoring
- uptime monitoring
- data rights review for every returned text field

Suggested hosted endpoint shape:

```text
https://api.example.org/mcp
```

Local stdio distribution is the safer first release because users control their
own data directory and runtime.

## Release Checklist

- [ ] `README.md` has the final repo URL.
- [ ] `pyproject.toml` has the final project metadata.
- [ ] `NOTICE` has completed source attribution and redistribution notes.
- [ ] `python3 -m pytest -q` passes.
- [ ] `sggs-mcp doctor` passes with local data.
- [ ] `python3 -m build` succeeds.
- [ ] `python3 -m twine check dist/*` succeeds.
- [ ] TestPyPI install works.
- [ ] PyPI upload is complete.
- [ ] MCP Registry `server.json` is published.
- [ ] Claude setup docs are tested.
- [ ] Codex setup docs are tested.
- [ ] Community directories are submitted.
