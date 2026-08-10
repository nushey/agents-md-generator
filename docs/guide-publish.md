# Publishing Guide

How to release a new version of `agents-md-generator`. The full process is
automated by [`publish.sh`](../publish.sh), but it assumes two things are
already in place: a valid `.env` and an authenticated `mcp-publisher`.

## What gets published, and where

A release publishes to **two independent registries**:

| Step | Command | Target | Auth |
| :--- | :--- | :--- | :--- |
| 1 | `uv publish` | **PyPI** — the Python package (the code) | `PYPI_TOKEN` from `.env` |
| 2 | `mcp-publisher publish` | **MCP Registry** — the `server.json` metadata (the listing) | `mcp-publisher login` (separate) |

These are separate systems with separate credentials. PyPI hosts the
installable package; the MCP Registry (`registry.modelcontextprotocol.io`) is
the public catalog where the server is discoverable. `mcp-publisher` does
**not** use `PYPI_TOKEN`.

## `mcp-publisher`

`mcp-publisher` is the official CLI for the MCP Registry. `publish.sh` only
checks that the binary exists — it does **not** authenticate for you. If you are
not logged in (or the token expired), `mcp-publisher publish` will fail *after*
PyPI has already been published, leaving the release half-done.

### Authentication

The auth method is dictated by the `name` field in [`server.json`](../server.json):

```json
"name": "io.github.nushey/agents-md-generator"
```

The `io.github.nushey` prefix means the registry requires proof that you own the
GitHub account `nushey`. So the method is **GitHub**:

```bash
mcp-publisher login github
```

This runs an interactive device flow (it shows a code and a GitHub link;
authorize it there). The token is stored locally, so you only need to do this
once — or again when the token expires.

Other methods supported by the CLI:

- `github-oidc` — for GitHub Actions CI (non-interactive)
- `dns` / `http` — only if publishing under a custom domain instead of `io.github.*`

## Full release procedure

```bash
# 1. One-time (or when the token expires): authenticate with the MCP Registry
mcp-publisher login github

# 2. Make sure .env exists with PYPI_TOKEN set
#    (copy .env.example and fill it in if needed)

# 3. Bump the version in pyproject.toml, then run the release
./publish.sh
```

`publish.sh` then, in order:

1. Loads `.env` and validates `PYPI_TOKEN`.
2. Reads `version` from `pyproject.toml` and syncs it into `server.json`.
3. Cleans `dist/` and runs `uv build`.
4. Publishes the package to PyPI (`uv publish`).
5. Publishes `server.json` to the MCP Registry (`mcp-publisher publish`).
6. Commits the version bump, pushes `dev`, merges `dev` into `main`, pushes `main`.

## Troubleshooting

- **`mcp-publisher not found`** — install the CLI, then re-run.
- **`publish` fails with an auth error** — run `mcp-publisher login github` again;
  the token likely expired.
- **Release stopped after PyPI** — PyPI rejects re-uploading the same version.
  Bump the version in `pyproject.toml` before retrying, then re-run.
