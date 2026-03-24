"""Builds the instruction string embedded in the analysis payload."""


def _build_instructions(has_existing: bool) -> str:
    """Build the instruction string embedded in the payload."""
    action = "UPDATE the existing" if has_existing else "CREATE a new"
    update_note = (
        "The existing AGENTS.md content is provided in 'existing_agents_md'. "
        "Preserve sections that are not affected by the detected changes. "
        "Only rewrite sections where the analysis shows something changed."
        if has_existing
        else "Write the complete file from scratch using the analysis data."
    )

    return f"""
TASK: {action} AGENTS.md file at the project root.

## ABSOLUTE RULES — NEVER BREAK THESE

1. DO NOT read any source files. Do not call Read, Glob, Grep, Bash, or any
   file-reading tool. ALL information needed is already in this payload.

2. DO NOT call generate_agents_md again.

3. DO NOT enumerate files. Never write tables or bullet lists of filenames with
   their exports. If you find yourself writing "| clients.api.js | getClients, addClient |"
   — STOP. That is wrong. AGENTS.md is not a file index.

4. DO NOT enumerate classes, interfaces, functions, or any code symbols by name.
   Never produce a bullet list like "- AttractionService, IncidentService, TicketService".
   Use symbol names ONLY to infer patterns and naming conventions, then document
   the PATTERN — not the instances. The only exception: classes that are unique
   and have no peers (e.g. Guard, ResultHandler, ServiceFactoryInjector) may be
   named once when their role cannot be inferred from a convention.

5. DO NOT invent commands, tools, or conventions absent from this payload.
   If a script is not in build_system.scripts, do not mention it.
   If a linter is not in config_files_found, do not claim it exists.

6. USE ONLY the data in this payload:
   - metadata → project name, detected languages
   - project_structure → directories, config files, CI files, test directories
   - build_system → detected tools, package files, parsed scripts
   - entry_points → bootstrap/main files per package with their role
   - env_vars → environment variables referenced in source or .env.example files
   - full_analysis → public symbols per file (use to INFER patterns)
   - changes → semantic diffs (incremental scans only)
   - existing_agents_md → current content to preserve or update ({update_note})

## WHAT AGENTS.MD IS — READ THIS BEFORE WRITING ANYTHING

AGENTS.md is a "README for AI coding agents." It gives agents the architectural
context and operational rules they need to contribute effectively WITHOUT
exploring the codebase themselves.

It answers:
  - How is this system structured and why?
  - What conventions must I follow when adding code?
  - Where exactly do I put a new file of type X?
  - What commands do I run to build, test, lint?
  - What must I never break?

It is NOT documentation. It is NOT a changelog. It is NOT a file index.

## HOW TO USE THE PAYLOAD DATA

### `full_analysis` — SYNTHESIZE patterns, never list files

Examine the file paths and symbol names to detect recurring patterns, then
document those patterns as RULES.

Examples of synthesis (infer these from the data, do not hard-code them):
- Naming convention: if you see `clients.api.js`, `orders.api.js`, `transports.api.js`
  → rule: "API clients follow the pattern `<entity>.api.js` in `src/api/`"
- Export convention: if every *.api.js exports getX, addX, modifyX, deleteX
  → rule: "API modules export CRUD functions named getX / addX / modifyX / deleteX"
- Layer pattern: if api/ → services/ → hooks/ → context/ → pages/ appears
  → document the data flow as a pipeline, not as individual files
- Domain grouping: if clients.*, orders.*, quotations.* appear across layers
  → the project is domain-oriented; list the domains, not the files

If you cannot detect a pattern, omit that convention. Never invent one.

### `project_structure.directories` — describe architecture, not a tree

Write what each directory layer IS and DOES, not a directory listing.
"src/api/ contains one HTTP client module per business entity" is good.
A table of directory paths with file counts is useless to an agent.

### `build_system.scripts` — exact commands only

Copy them verbatim. Use fenced code blocks. Never paraphrase.
`scripts.python` contains install, test, and CLI entry point commands derived
from `pyproject.toml` and the detected package manager (uv, poetry, pip).
`scripts.npm` contains scripts from `package.json`.
`scripts.make` contains Makefile targets.

## FORMAT (include only sections with real data)

### Project Overview
2–4 sentences: what the system does, the tech stack, and the top-level
architectural shape (e.g., layered, domain-driven, monorepo). No file lists.

### Architecture & Data Flow
The most important narrative section. It has two mandatory parts:

**Part 1 — Module/project inventory (REQUIRED, no exceptions):**
List EVERY top-level project, package, or module detected in
project_structure.directories. For each, write exactly ONE sentence describing
its sole responsibility. Nothing more. Use this format:
  - `<module-name>` — <one-sentence purpose>
Example:
  - `TPark.Domain` — Pure domain models, enums, and validation with no external dependencies.
  - `TPark.Services` — Business logic implementing all IServices interfaces.
Every module must appear. Missing a module is a bug in this document.

**Part 2 — Data flow narrative:**
After the module list, describe the architectural shape and data direction.
For a layered architecture: name each layer and the direction data flows
(e.g., WebApi → Orchestrators → Services → IDataAccess → DataAccess).
For a domain architecture: name the domains and their boundaries.
This section replaces any need to enumerate files or classes.

### Conventions & Patterns
THE most actionable section for AI agents. Synthesize from full_analysis:
- File naming rules per layer/type (exact pattern, exact directory)
- Export contract per file type (what every file of that type must export)
- Import rules (which layers may import from which — e.g., "pages import
  only from Context, never directly from api/")
- How to add a new entity end-to-end (step-by-step, referencing the detected
  pattern — e.g., "1. Create <entity>.api.js in src/api/ with CRUD exports.
  2. Create <entity>Service.js in src/services/. 3. Add hook in src/hooks/.
  4. Register in DataContext.")

### Environment Variables
Only if env_vars is non-empty. List each variable with a one-line description
of its purpose inferred from its name and the files it appears in.
If a .env.example is present, mention it explicitly.

### Setup Commands
Exact install and environment commands from build_system. Fenced code blocks.
Reference entry_points to explain where bootstrap happens.

### Development Workflow
Run/build/watch commands from build_system.scripts. Fenced code blocks.
Skip if no scripts detected.

### Testing Instructions
From test_directories + config_files_found (jest/pytest/vitest) +
build_system.scripts test entries. Skip entirely if nothing detected.

### Code Style
Only if linting/formatting config files appear in config_files_found.
Include the exact lint/format commands. Omit if nothing detected.

### Build and Deployment
Build commands and CI pipeline info from ci_files_found. Omit if empty.

### Keeping AGENTS.md Up to Date
ALWAYS include this section verbatim at the end of every AGENTS.md, regardless
of the project:

```
## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask your AI assistant:

> "Update the AGENTS.md for this project"

The assistant will invoke the `generate_agents_md` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
```

## QUALITY BAR

- Conventions section must be actionable: an agent reading it should know
  exactly what file to create, where, and what to export — with zero guessing.
- Every command must be exact and runnable. No placeholders like <your-value>.
- Omit any section with zero real data from the payload.
- Zero file enumeration tables or lists anywhere in the document.
- Zero class/interface/function enumeration anywhere. No lists of symbol names.
- Architecture section MUST list every detected module/project — no omissions.
- Describe patterns, not instances: "one service per entity named <Entity>Service"
  is correct; "AttractionService, IncidentService, TicketService" is wrong.
""".strip()
