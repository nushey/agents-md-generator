# Contributing to agents-md-generator

**Welcome!** We appreciate your interest in contributing.

## Quick Links

- [Report an Issue](../../issues/new)
- [Open a Pull Request](../../pulls)

---

## What is agents-md-generator?

An MCP server that analyzes codebases with tree-sitter AST parsing and generates `AGENTS.md` files — structured context documents for AI coding agents. The pipeline is linear: detect changes → analyze AST → build payload → serve via MCP → AI writes `AGENTS.md`.

---

## Ways to Contribute

| Type | Examples |
|------|----------|
| **Report** | File an issue with steps to reproduce and expected vs actual behavior |
| **Fix** | Bug fixes, parser corrections, broken language support |
| **Build** | New language analyzers, new MCP tools, performance improvements |
| **Document** | Improve docs, add usage examples, clarify existing content |

---

## Branch Naming

| Prefix | When to Use |
|--------|-------------|
| `feature/` | New language support, new MCP tools, new capabilities |
| `fix/` | Bug fixes, parser corrections, broken behavior |
| `chore/` | Dependency updates, CI, version bumps, non-functional changes |

Branch names must be lowercase with hyphens. The description must clearly state what is affected.

```
feature/add-ruby-analyzer
fix/typescript-generic-parsing
chore/bump-tree-sitter-python
```

---

## Pull Request Process

**Each PR must focus on a single change.** Out-of-scope refactors or drive-by fixes go in a separate PR.

### 1. Branch off `dev`

```bash
git checkout dev
git pull origin dev
git checkout -b feature/your-description
```

### 2. Make Your Changes

**Follow the existing architecture.** New language analyzers go in `src/agents_md_mcp/languages/`. New data models go in `models.py`. Business logic never goes in `server.py`.

**Adding a new language?** See the [conventions in AGENTS.md](AGENTS.md#adding-a-new-language-analyzer) — there are four concrete steps to follow.

### 3. Add Tests

Every change **must** include tests. Tests live in `tests/` and use pytest.

Add a fixture file in `tests/fixtures/sample.<ext>` when adding a new language analyzer.

```bash
uv run pytest
```

All tests must pass before opening a PR.

### 4. Open PR against `dev`

Target the `dev` branch. `main` is the release branch — PRs go to `dev` first.

---

## Setup

```bash
uv sync
uv run pytest        # run tests
uv run agents-md-generator  # run the server
```

---

## Questions?

Open an [issue](../../issues) or start a [discussion](../../discussions).

**Thank you for contributing!**
