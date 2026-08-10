# Performance Core Fixes — Refined Plan

> Refines `.kilo/plans/performance-fix-plan.md`. Scope narrowed on purpose:
> **only clear logic errors and simplifications with provable behavior
> equivalence.** Anything that replaces working enumeration/data-flow logic with
> new logic is explicitly deferred — new logic on a working pipeline is where
> future feature bugs come from.
>
> Baseline verdicts (validated against `dev`, 2026-07-29): F1/F2/F3/F4 confirmed,
> F5 real but deferred, F6 invalid (linear, not quadratic), F7/F8 partially fixed
> already, F9/F10 noise. New: F11 (filter order), F12 (double enumeration —
> deferred).

---

## Guiding rule

Every change below must satisfy ONE of:
1. **Identical output** — same files enumerated, same payload bytes (modulo speed), or
2. **Fixes a latent correctness bug** — and the behavior delta is documented and test-guarded.

If a change can't argue (1) or (2), it does not belong in this plan.

---

## Tier A — Zero behavior change, isolated, trivial to review

### A1 — Reorder filters in `_walk_files` (F11)

- **Where:** `src/agents_md_mcp/project_scanner.py:78-80`
- **Defect (logic error):** the expensive check runs before the cheap one. Every
  file inside `node_modules`/`bin`/`obj` pays a `pathspec` regex evaluation
  (`is_gitignored`) before the O(1) set-membership test in `_is_excluded` gets a
  chance to reject it.
- **Change:** swap the two `if` blocks — `_is_excluded` first, `is_gitignored`
  second.
- **Equivalence:** both filters `continue` on match and are order-independent
  (pure predicates, AND-composed rejection). Output set is byte-identical.
- **Guard:** existing `_walk_files` coverage; no new test needed.

### A2 — In-memory payload cache in `read_payload_chunk` (F4)

- **Where:** `src/agents_md_mcp/server.py:271`
- **Defect (logic error):** the server is a long-lived process, yet every chunk
  call re-reads the ENTIRE payload from disk: O(chunks × payload_size) I/O. A
  multi-MB payload at `CHUNK_CHARS = 20_000` means hundreds of full re-reads.
- **Change:** module-level cache `_payload_cache: dict[Path, tuple[float, str]]`
  keyed on `(path → mtime, text)`. On each call: `stat()` the file; if mtime
  matches, slice the cached string; else read once and refresh. Evict the entry
  in the same place the file is `unlink()`ed after the last chunk.
- **Equivalence:** chunk math is untouched — same `total_chunks`, same slices,
  same UTF-8 semantics. mtime keying means a re-scan (new payload written)
  invalidates naturally.
- **Guard:** existing chunking tests pass unchanged; add one test: two sequential
  scans → second scan's chunks reflect the new payload (cache invalidation).
- **Note:** do NOT switch to byte-offset seeking — chunking is by code point and
  byte offsets don't align with UTF-8. The cache achieves the same win with zero
  semantic risk.

### A3 — Reuse the shared walk for `.csproj` discovery (F8 remnant)

- **Where:** `src/agents_md_mcp/build_system.py:30` + `context_builder.py:154`
- **Defect (redundant logic + latent bug):** `rglob("*.csproj")` is a third full
  tree traversal per `build_payload`, and it collects `.csproj` copies inside
  `bin/`/`obj/` build output — those then produce duplicate `dotnet_projects`
  entries parsed from stale artifacts.
- **Change:** add optional parameter
  `_detect_build_systems(root, csproj_files: list[Path] | None = None)`.
  `build_payload` passes `[p for p, rel in walked_files if p.suffix == ".csproj"]`.
  When `None` (isolated tests, other callers), keep the current `rglob` fallback —
  signature-compatible, no caller breaks.
- **Behavior delta (documented, rule 2):** `bin/obj`-copied and gitignored
  `.csproj` files no longer appear in `package_files`/`dotnet_projects`. That is
  the correct output — the current inclusion of build artifacts is the bug.
- **Guard:** new test: fixture with `A.csproj` at root and a copy under
  `obj/`; assert only the root one is detected. Existing
  `test_context_builder.py` cases must pass unchanged.

---

## Tier B — The hang fix: prune the walks (F1), minimal-delta version

The core logic error: `Path.rglob()` cannot skip a directory, so excluded trees
are entered and enumerated file-by-file. The fix is `os.walk` with in-place
`dirnames[:]` pruning — but restricted to pruning rules that are **provably
equivalent** to the existing per-file filters. No new enumeration strategy, no
`git ls-files` switch, no new module: same functions, same signatures, same
output.

### Pruning rule (shared by B1–B3)

Prune directory `name` (rel path `rel_dir`) when:

1. `name ∈ config._exclude_dir_tokens` — **provably equivalent**: a token in the
   set came from a `**/<dir>/**` pattern, which matches exactly the files having
   `<dir>` as a path component; every file under the pruned dir has it. This set
   covers all the pathological trees: `node_modules`, `bin`, `obj`, `.git`,
   `dist`, `build`, `__pycache__`, `vendor`, `packages`, `.venv`, `venv`,
   `bower_components`, `site-packages` (`config.py:74-100`).
2. *(optional, same-PR refinement)* for each glob in `config._exclude_globs`
   ending in `/**`: `fnmatch(rel_dir, glob[:-3])` — equivalent because
   `p + "/**"` matches a file iff the file lies under a dir matching `p`
   (fnmatch `*` crosses `/`). Covers `**/wwwroot/lib/**`-style multi-segment
   excludes. If skipped, those files are still per-file filtered — correctness
   identical either way.

**Deliberately NOT pruned:** gitignore-matched directories. `pathspec` negation
patterns (`!keep.txt`) can re-include a file under an ignored dir in the current
per-file matching; pruning would change that outcome. Gitignored files keep
being filtered per-file exactly as today. (The dominant cost is dependency dirs,
which rule 1 already kills. A follow-up MAY prune gitignored dirs when the spec
contains no negation lines — only with a dedicated test.)

### B1 — `_walk_files` (`project_scanner.py:63-85`)

Replace the `rglob("*")` loop body with `os.walk(root)`; apply the pruning rule
to `dirnames`; keep the existing per-file filter chain untouched (post-A1 order).
`is_file()` checks disappear — `os.walk` already separates files from dirs, one
less `stat()` per entry.

- **Guard:** equivalence test on the repo's own tree + a fixture tree containing
  `node_modules/`, `bin/`, a nested `.gitignore`, and a negation pattern: sorted
  file list from the new walk == sorted file list from the old `rglob`
  implementation (keep the old one in the test as reference, then delete).

### B2 — `load_gitignore_spec` (`gitignore.py:26`)

`rglob(GITIGNORE_FILE)` walks the FULL tree — including `node_modules` — to find
`.gitignore` files. Replace with `os.walk` + the same pruning rule
(tokens sourced from `DEFAULT_CONFIG["exclude"]`, since this function has no
`config` param — keep its signature).

- **Behavior delta (documented, rule 2):** `.gitignore` files inside dependency
  dirs no longer contribute patterns to the project's spec. Today a
  `node_modules/foo/.gitignore` pollutes the global spec with prefixed patterns —
  a latent correctness bug (third-party ignore rules silently filter project
  files under that prefix). Root and nested project gitignores are unaffected:
  walk order is top-down, discovery set is otherwise identical.
- **Guard:** existing `test_gitignore.py` must pass unchanged; add one test:
  a `.gitignore` inside `node_modules/` is ignored, one inside `src/` is honored.

### B3 — `_fs_walk` (`change_detector.py:42-52`)

Non-git fallback only. Same `os.walk` + pruning-rule swap; keep the
per-file `is_gitignored` check exactly as-is (see negation note). Downstream
`_filter_paths` is untouched.

- **Guard:** existing change-detector tests; the B1 equivalence fixture reused.

---

## Tier C — Bounded micro-optimizations (no data-flow changes)

### C1 — Substring pre-filter before env regex (F3, surgical form)

- **Where:** `project_scanner.py:207-213`
- **Change:** before `pattern.finditer(content)`, skip when none of the
  candidate substrings occur in `content`. Per-language guards:
  `javascript`/`typescript`/`python`/`go` → `"env"` (case-insensitive covers
  `Getenv`/`environ`); `ruby` → `"ENV"`; `rust` → `"env"` **or** `"var("` —
  the rust pattern's `var\s*\(` branch does not contain "env", so a bare `"env"`
  guard would silently drop matches. This is exactly the kind of edge that
  justifies keeping the filter per-language and test-guarded.
- **Equivalence:** a regex can only match if its literal anchors appear in the
  text; the guard strings are those anchors. Output set identical.
- **Guard:** extend env-var tests with a rust fixture using `std::env::var("X")`
  without the literal `env!` macro… and a file with zero env usage (fast path).

### C2 — Drop the per-file `stat()` in `_detect_env_vars` (optional)

`item.stat().st_size` (`project_scanner.py:205`) adds one syscall per candidate
file. Fold into the single `read` via `content = item.read_text(...)` +
`len` check only if profiling shows it matters post-B. Otherwise skip — not worth
review surface.

---

## Explicitly DEFERRED (working logic — do not touch in this pass)

| Item | Why deferred |
| :-- | :-- |
| Single-read-per-file refactor (F2) | Rethreads data flow across `change_detector` → `ast_analyzer` → `project_scanner`. Real win, real regression surface. Only after Tier B is measured insufficient. |
| `git ls-files` enumeration in `build_payload` (F12) | Changes WHICH files are seen (untracked-but-not-ignored files disappear). Behavior change on a working feature. |
| Parallel parsing (F5) | New concurrency = new bug classes (analyzer cache `_ANALYZERS` is not thread-safe as-is). Measure after B; likely unnecessary. |
| Gitignore-based dir pruning with negations | Semantics differ between git and pathspec; needs its own spec + tests. |
| F6 `_extract_class_pattern` | Finding invalid — code is O(10×C) linear. No action. |
| F7 fnmatch precompile, F9 git batching, F10 | Marginal; F7 already has the set fast-path and `fnmatch` LRU-caches patterns. |

---

## Execution order & validation

1. **A1 → A2 → A3** (independent, each its own commit, `uv run pytest` green after each).
2. **B1 → B2 → B3** (share the pruning helper — one small private function, e.g.
   `_prune_dirnames(dirnames, rel_dir, tokens, globs)` placed in `path_utils.py`).
3. **C1** last.

Validation:
- **Equivalence harness (the key gate):** fixture tree with synthetic
  `node_modules` (~thousands of files), `bin/obj` with `.csproj` copies, nested
  `.gitignore` with a negation. Assert old-walk vs new-walk file sets are equal,
  and that visited-directory count excludes every token dir.
- **Benchmark:** time `build_payload` + `detect_changes` on the fixture before/after;
  expect the walk cost to drop from O(all fs entries) to O(project entries).
- **Repro:** re-run against the original failing 50k-line project; compare the
  per-stage `logger.info` timings in `_run_pipeline` (`server.py:140-228`).
- Full suite: `uv run pytest`.
