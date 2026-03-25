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

4. Symbol names: use them to INFER patterns, not to produce lists.
   WRONG: "- AttractionService, IncidentService, TicketService"
   RIGHT: "Business logic lives in `<Entity>Service` classes under `src/services/`"
   EXCEPTION — name a symbol explicitly ONLY when it falls into one of these roles:
     a) Base class that every new file of a type MUST extend (e.g. LogicBase, ApiControllerBase)
     b) Framework/context class injected into most components (e.g. ZureoContext, DbContext)
     c) Primary interface that defines a core architectural contract (e.g. IRepository, IUnitOfWork)
     d) Entry-point or bootstrap class an agent would need to register new code in
   These are architectural anchors — an agent cannot write correct code without knowing them.

5. DO NOT invent commands, tools, or conventions absent from this payload.
   If a script is not in build_system.scripts, do not mention it.
   If a linter is not in config_files_found, do not claim it exists.

6. USE ONLY the data in this payload:
   - metadata → project name, detected languages
   - project_structure.top_level_dirs → top-level projects/packages (module inventory source)
   - project_structure.directories → all directories (use to infer layer structure)
   - build_system → detected tools, package files, parsed scripts
   - entry_points → bootstrap/main files per package with their role
   - env_vars → environment variables referenced in source or .env.example files
   - full_analysis → public symbols, constructors, properties per file (infer patterns from these)
   - changes → semantic diffs (incremental scans only)
   - existing_agents_md → current content to preserve or update ({update_note})

## WHAT AGENTS.MD IS — READ THIS BEFORE WRITING ANYTHING

AGENTS.md is a "README for AI coding agents." It gives agents the architectural
context and operational rules they need to contribute effectively WITHOUT
exploring the codebase themselves.

It answers:
  - What is this system and what does it do?
  - What is the full tech stack (languages, frameworks, key libraries)?
  - How is this system structured and why?
  - What conventions must I follow when adding code?
  - Where exactly do I put a new file of type X?
  - Which base classes must I extend? Which interfaces must I implement?
  - What are the key data models and their shapes?
  - What commands do I run to build, test, lint?
  - What must I never break?

It is NOT documentation. It is NOT a changelog. It is NOT a file index.

## HOW TO USE THE PAYLOAD DATA

### `full_analysis` — SYNTHESIZE patterns, identify anchors

Examine file paths, symbol names, signatures, constructors, and properties to:

1. Detect recurring patterns → document as RULES
   - Naming: `clients.api.js`, `orders.api.js` → "API clients follow `<entity>.api.js`"
   - Layers: api/ → services/ → hooks/ → context/ → pages/ → document as pipeline
   - Domains: clients.*, orders.* across layers → domain-oriented, list domains not files

2. Identify architectural anchors (see Rule 4 exceptions) → name them explicitly
   - Base classes: if many classes share the same base in their signature → name that base
   - Context classes: if a class appears in constructors of many others → name it
   - Primary interfaces: if an interface is implemented across the codebase → name it

3. Extract data model shapes from `properties` fields
   - If an entity class has properties, document its key fields
   - Focus on entities referenced across multiple layers — these are the core domain models
   - Skip trivial/DTO-only entities with no cross-layer presence

4. Infer DI patterns from `constructor` fields
   - If most classes receive dependencies via constructor → document constructor injection as the pattern
   - If the same types appear repeatedly in constructors → those are the key services/abstractions

If you cannot detect a pattern from the data, omit it. Never invent one.

### `project_structure.top_level_dirs` — module inventory source of truth

This field lists ONLY the immediate top-level directories of the project.
Use it as the authoritative list for the module inventory. Every entry must appear.

### `build_system.scripts` — exact commands only

Copy them verbatim. Use fenced code blocks. Never paraphrase.

## FORMAT (include only sections with real data)

### Project Overview
3–5 sentences covering:
- What the system does (business purpose)
- Full tech stack: backend language + framework, frontend framework, databases, key libraries
- Top-level architectural shape (layered, domain-driven, monorepo, microservices, etc.)
No file lists. No symbol lists.

### Tech Stack
Explicit list of technologies detected from metadata, build_system, and imports:
- Backend: language, framework, ORM/data access, key libraries
- Frontend: framework, key libraries (only if frontend is present)
- Databases: detected from env_vars, imports, or build files
- Infrastructure: CI/CD, deployment tools (only if detected in ci_files_found)
Omit any category with no detected data.

### Architecture & Data Flow
The most important narrative section. Two mandatory parts:

**Part 1 — Module/project inventory (REQUIRED, no exceptions):**
Source: `project_structure.top_level_dirs` — use EVERY entry, no omissions.
For each entry write exactly ONE sentence describing its sole responsibility:
  - `<module-name>` — <one-sentence purpose>
Every entry in top_level_dirs must appear here. Missing one is a bug.

**Part 2 — Data flow narrative:**
Describe the architectural shape and direction data flows through it.
Layered: name each layer and the flow direction (e.g. Controller → Logic → Repository → DB).
Domain: name the domains and their boundaries.
Name the architectural anchor classes/interfaces here if identified (Rule 4 exceptions).

### Key Models
Only include if full_analysis contains entity classes with `properties` fields.
For each core domain entity (referenced across multiple files/layers), list:
- Its name, its layer/package, and its key properties (type + name)
- Its constructor dependencies if it has them (reveals DI graph)
Skip purely internal or generated entities. Omit this section if no meaningful
entity data is present.

### Backend Guidelines
Only include if a backend is detected. Synthesize from full_analysis:
- Base classes that MUST be extended for controllers, services, repositories, etc.
  Name them explicitly (Rule 4a). State what each one provides.
- Constructor injection pattern if detected — name the key injectable services (Rule 4b/c)
- Required method signatures or lifecycle hooks (e.g. RegisterRoutes(), OnInit())
- Error handling conventions (from patterns detected in method signatures)
- Transaction/unit-of-work patterns if detected (idTrans, IUnitOfWork, etc.)
- Data access conventions (ORM pattern, raw SQL, stored procedures, etc.)
- Security/auth conventions (permission checks, middleware patterns)

### Frontend Guidelines
Only include if a frontend is present (JS/TS files detected). For monorepos:
write a separate subsection per frontend package if they differ in conventions.
Cover:
- Module/component structure (directory layout, naming pattern)
- State management approach (if detected from imports or patterns)
- Communication with backend (HTTP client pattern, API layer)
- Key UI framework patterns (component lifecycle, routing, forms)
- Naming conventions specific to the frontend layer

### Conventions & Patterns
THE most actionable section. Cover what is not already in Backend/Frontend Guidelines:
- File naming rules per layer (exact pattern, exact directory)
- Cross-cutting concerns: logging, validation, localization patterns
- Test file placement and naming conventions (if test_directories detected)

### How to Add a Feature (OPTIONAL)
Include ONLY if the full_analysis reveals a clear, consistent N-layer pattern
that repeats across 3+ domains. If the pattern is ambiguous or inconsistent, OMIT this section entirely — a wrong guide is worse than no guide.
When present, write the exact step-by-step for adding a new feature end-to-end,
referencing the detected pattern:
  1. Create `<Entity>Controller.cs` in `X/` extending `ApiControllerBase`
  2. Create `<Entity>Logic.cs` in `Y/` extending `LogicBase`
  3. ...

### Environment Variables
Only if env_vars is non-empty. One line per variable describing its purpose.

### Setup & Build Commands
Exact commands from build_system. Fenced code blocks. No paraphrasing.
Reference entry_points to explain where bootstrap happens.

### Testing
From test_directories + config_files_found + build_system.scripts test entries.
Skip entirely if nothing detected.

### Keeping AGENTS.md Up to Date
ALWAYS include this section verbatim at the end:

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

- Project Overview must state the tech stack explicitly — framework names, not just language names.
- Module inventory must include EVERY entry from top_level_dirs. Zero omissions.
- Backend Guidelines must name base classes and context classes an agent must use.
- Key Models must document entity shapes if properties data is present.
- Conventions must be actionable: agent knows exactly what to create, where, what to extend.
- Every command must be exact and runnable. No placeholders.
- Zero file enumeration tables. Zero symbol-list bullets (except Rule 4 exceptions).
- How to Add a Feature: include only when pattern is unambiguous — omit when uncertain.
- Minimum depth: a developer unfamiliar with this codebase should be able to add
  a feature correctly after reading this document, without opening a single source file.
""".strip()
