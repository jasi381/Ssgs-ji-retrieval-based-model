# Security Policy

## Supported Versions

Security fixes are applied to the latest released version.

## Reporting a Vulnerability

Open a private security advisory or contact the maintainer before public
disclosure. Include:

- affected version or commit
- reproduction steps
- expected and actual behavior
- impact assessment

## MCP Security Notes

This server is read-only and exposes retrieval tools over MCP. It should not
write outside the configured data directory except when explicitly running
maintenance commands such as `sggs-mcp build-index`, `sggs-mcp download-data`,
or `sggs-mcp extract-multilingual`.

For local stdio use, configure clients with absolute paths or a package command
such as `uvx sggs-mcp`. For hosted Streamable HTTP deployments, add origin
validation, authentication, rate limits, request logging, and abuse monitoring
before public use.
