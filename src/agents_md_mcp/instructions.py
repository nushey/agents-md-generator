"""Builds the instruction string embedded in the analysis payload."""


def _build_instructions(has_existing: bool) -> str:
    """Build the instruction string embedded in the payload."""
    action = "UPDATE the existing" if has_existing else "CREATE a new"
    update_note = (
        "\n\nUPDATE MODE: The current AGENTS.md is in 'existing_agents_md'. "
        "Preserve sections unaffected by detected changes. "
        "Rewrite only sections where the analysis shows something changed."
        if has_existing
        else ""
    )

    return f"""\
TASK: {action} AGENTS.md file at the project root.

AGENTS.md is a "README for AI coding agents." It gives agents the architectural
context and rules they need to contribute correctly WITHOUT exploring the codebase.
It is NOT documentation, NOT a changelog, NOT a file index.{update_note}

===================================================================
BLOCK 1 -- HARD CONSTRAINTS (never break these)
===================================================================

1. Use ONLY the data in this payload. Never read source files, never call any
   file-reading tool (Read, Glob, Grep, Bash), never call generate_agents_md.
2. Never enumerate files or symbols in lists. Describe PATTERNS and CONVENTIONS.
   WRONG: "UserService, OrderService, TicketService handle business logic"
   RIGHT: "Business logic lives in `<Entity>Service` classes under `src/services/`"
3. Never invent commands, tools, or conventions absent from this payload.
   If a script is not in build_system.scripts, do not mention it.
4. Every entry from `project_structure.top_level_dirs` MUST appear in the
   Project Map table. Zero omissions. This is non-negotiable.
5. Name a symbol explicitly ONLY when it is an architectural anchor --a class
   or interface an agent MUST know to write correct code. See Synthesis Rules.

===================================================================
BLOCK 2 -- SYNTHESIS RULES (how to transform payload into prose)
===================================================================

PATTERN INFERENCE
Examine file paths, symbol names, signatures, constructors, and decorators
across `full_analysis` to detect recurring patterns. Document as rules:
  - Naming: `clients.api.js`, `orders.api.js` ->"API clients follow `<entity>.api.js`"
  - Layers: api/ ->services/ ->hooks/ ->pages/ ->document the pipeline
  - Domains: clients.*, orders.* across layers ->name domains, not files

ARCHITECTURAL ANCHORS (the only symbols you may name explicitly)
Three categories:
  a) Base classes that new files MUST extend (detected: many classes share
     the same base in their `signature` or `implements` field)
  b) Context/service classes injected everywhere (detected: same type appears
     in `constructor_deps` of many classes)
  c) Primary interfaces defining layer boundaries (detected: entries in
     `interface_impl_map` with 3+ implementors)

READING AGGREGATED ENTRIES in `full_analysis`
  - `kind: "directory_summary"` --collapsed directory. Key fields:
    `common_methods` (signatures shared by 60%+ files = the layer's interface),
    `naming_pattern` (e.g. `*Service`), `outliers`, `sample_files`
  - `kind: "dto_container"` --file with only data classes, no logic methods
  - `kind: "overflow"` --directory exceeded cap; `remaining_files` = hidden count
  - `kind: "test_directory_summary"` --collapsed test dir with file/function counts

METHOD PATTERN LOOKUP
If `method_patterns` exists in the payload, short keys like "m0" in method
lists resolve to full signatures via this lookup table.

CONDITIONAL SECTIONS
Include an output section ONLY if the payload has data for it.
If no frontend files ->omit Frontend Guidelines. If env_vars is empty ->omit
Environment Variables. Never generate empty or speculative sections.

===================================================================
BLOCK 3 -- OUTPUT SECTIONS (produce in this exact order)
===================================================================

Each section below specifies SOURCE (payload fields to read), WRITE (what to
produce), and SKIP (what to omit). Include only sections whose condition is met.

---------------------------------------------------
### 1. Project Overview [REQUIRED]
---------------------------------------------------
SOURCE: metadata, build_system (detected, *_packages), entry_points,
        project_structure.top_level_dirs
WRITE: 3-5 sentences covering:
  - What the system does (business purpose, inferred from project name,
    entry points, and detected frameworks)
  - Full tech stack with SPECIFIC framework names from packages --say
    "Python / FastAPI / SQLAlchemy", not just "Python"
  - Top-level architectural shape (layered, monorepo, microservices, etc.)
  - If multiple entry points suggest separate applications (e.g. WebApp.ON,
    WebApp.LITE), name them with their inferred role
SKIP: File lists. Symbol lists. Directory trees.

---------------------------------------------------
### 2. Tech Stack [REQUIRED]
---------------------------------------------------
SOURCE: metadata.languages_detected, build_system (detected, *_packages),
        project_structure.config_files_found, project_structure.ci_files_found
WRITE: Categorized list:
  - Backend: language, framework, ORM, key libraries (from package lists)
  - Frontend: framework, UI libs (only if JS/TS detected)
  - Databases: inferred from packages (e.g. `pg` ->PostgreSQL) or env vars
  - Infrastructure: CI/CD from ci_files_found, linters from config_files_found
SKIP: Any category with no detected data. Never guess databases not in payload.

---------------------------------------------------
### 3. Project Map [REQUIRED --NON-NEGOTIABLE]
---------------------------------------------------
SOURCE: project_structure.top_level_dirs (EVERY entry, no exceptions)
WRITE: A Markdown table with columns: Module | Purpose
  - Infer each module's purpose from its name, languages field, kind field,
    and cross-reference with full_analysis entries under that path
  - If directories share a strict namespace (e.g. Zureo.Queries.*), you MAY
    group them into one row, but never omit unique outliers
  - EVERY top_level_dirs entry must appear --count them before and after
SKIP: Nested subdirectories. File counts. Language badges.

---------------------------------------------------
### 4. Architecture & Data Flow [REQUIRED]
---------------------------------------------------
SOURCE: project_structure.directories, full_analysis (directory summaries,
        constructor_deps), interface_impl_map, wiring.route_map
WRITE: Narrative describing:
  - Architectural shape and how data flows through layers
  - Layer names and flow direction (e.g. Controller ->Service ->Repository ->DB)
  - Architectural anchor classes/interfaces (from Synthesis Rules)
  - If interface_impl_map shows contracts with 3+ implementors, name them as
    layer boundaries
  - If wiring.route_map exists, describe the routing CONVENTION (attribute-based,
    decorator-based, file-based) and URL naming pattern --not individual routes
SKIP: Individual file paths. Individual route listings. Repeating the Project Map.

---------------------------------------------------
### 5. Key Models [CONDITIONAL: is_dto entries across multiple directories]
---------------------------------------------------
SOURCE: full_analysis (is_dto markers, dto_container entries, directory
        summaries with DTO notes), naming_pattern fields
WRITE: Domain model PATTERN:
  - Where domain entities live (directory convention)
  - Naming convention (from naming_pattern if available)
  - How entities relate to the architecture (consumed via constructor_deps?
    implement shared interfaces?)
  - Pattern for creating a new entity
SKIP: Listing individual entity names or properties. Omit section entirely
      if no clear domain model layer is detected.

---------------------------------------------------
### 6. Backend Guidelines [CONDITIONAL: backend language detected]
---------------------------------------------------
SOURCE: full_analysis (symbols, constructor_deps, decorators, common_methods),
        interface_impl_map, wiring.route_map
WRITE:
  - Base classes that MUST be extended --name explicitly, state what each provides
  - Constructor injection pattern with key injectable types
  - Required method signatures / lifecycle hooks (from common_methods)
  - Routing convention: URL pattern, HTTP method mapping, attribute vs decorator
  - Error handling conventions (from patterns in method signatures)
  - Transaction / unit-of-work patterns if detected
  - Data access conventions (ORM, raw SQL, stored procedures)
  - Security/auth conventions if detected
SKIP: Frontend concerns. Individual file paths.

---------------------------------------------------
### 7. Frontend Guidelines [CONDITIONAL: JS/TS files in non-backend context]
---------------------------------------------------
SOURCE: full_analysis (JS/TS entries), build_system.npm_packages
WRITE:
  - Component structure and naming convention
  - State management approach (from detected packages)
  - API communication pattern (HTTP client layer)
  - Key framework patterns (routing, forms, lifecycle)
  - Per-package subsections in monorepos if conventions differ
SKIP: Backend concerns.

---------------------------------------------------
### 8. Conventions & Patterns [REQUIRED if any patterns detected]
---------------------------------------------------
SOURCE: full_analysis (naming patterns, directory structure),
        project_structure.test_directories, project_structure.config_files_found
WRITE: What is NOT already in Backend/Frontend Guidelines:
  - File naming rules per layer (exact pattern, exact directory)
  - Cross-cutting: logging, validation, localization patterns
  - Test file placement and naming conventions
SKIP: Anything already covered in earlier sections.

---------------------------------------------------
### 9. How to Add a Feature [CONDITIONAL: clear N-layer pattern in 3+ domains]
---------------------------------------------------
SOURCE: Synthesis of all above sections
WRITE: Exact step-by-step with concrete templates:
  "1. Create `<Entity>Controller.cs` in `X/` extending `ApiControllerBase`"
  "2. Create `<Entity>Logic.cs` in `Y/` extending `LogicBase`"
  etc.
SKIP: This entire section if the pattern is ambiguous or inconsistent.
      A wrong guide is worse than no guide.

---------------------------------------------------
### 10. Environment Variables [CONDITIONAL: env_vars non-empty]
---------------------------------------------------
SOURCE: env_vars
WRITE: One line per variable with its inferred purpose.
SKIP: Entire section if env_vars is empty.

---------------------------------------------------
### 11. Setup & Build Commands [CONDITIONAL: build_system.scripts non-empty]
---------------------------------------------------
SOURCE: build_system.scripts, entry_points
WRITE: Exact commands in fenced code blocks, copied VERBATIM from payload.
       Reference entry_points to explain where bootstrap happens.
SKIP: Paraphrased or invented commands.

---------------------------------------------------
### 12. Testing [CONDITIONAL: test directories or test scripts detected]
---------------------------------------------------
SOURCE: project_structure.test_directories, config_files_found (test configs),
        build_system.scripts (test commands), full_analysis (test_directory_summary)
WRITE: Test framework, test command, file placement convention, naming convention.
SKIP: Entire section if nothing detected.

---------------------------------------------------
### 13. Keeping AGENTS.md Up to Date [REQUIRED --include verbatim]
---------------------------------------------------
Include this section exactly as written:

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask your AI assistant:

> "Update the AGENTS.md for this project"

The assistant will invoke the `generate_agents_md` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".

===================================================================
BLOCK 4 -- QUALITY CHECKLIST (verify before producing output)
===================================================================

1. Project Overview names SPECIFIC frameworks (from packages), not just languages.
2. Project Map includes EVERY entry from top_level_dirs --count them.
3. Backend Guidelines names base classes and context classes by symbol name.
4. Key Models describes the PATTERN --never lists individual entities.
5. Every convention is actionable: agent knows what to create, where, what to extend.
6. Every command is exact and runnable --no placeholders, no paraphrasing.
7. Zero file enumeration tables. Zero symbol-list bullets (except anchors).
8. How to Add a Feature is present ONLY when pattern is unambiguous.
9. A developer unfamiliar with this codebase can add a feature correctly after
   reading this document, without opening a single source file.""".strip()
