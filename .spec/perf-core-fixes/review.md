# Final Implementation Review — Performance Core Fixes

Reviewed the current working tree against base commit `c40f27c`,
`.spec/perf-core-fixes/plan.md`, and every finding from the initial implementation
review.

## Verdict

**Ready to merge.**

No Critical or Important findings remain. The implementation fixes the original
timeout paths, preserves the intended file set, deliberately makes traversal
order deterministic, and adds regression coverage for the previously reproduced
failures.

## Resolution of previous findings

### 1. Non-regular files entering `_fs_walk` — resolved

- **Implementation:** `src/agents_md_mcp/change_detector.py:55-70`
- **Validation:** `tests/test_perf_fixes.py:163-172`

`_fs_walk` now verifies `Path.is_file()` before returning a path. FIFOs, sockets,
devices, and broken symlinks do not reach hashing. A direct FIFO reproduction
returned an empty walk result and did not block.

### 2. Gitignore discovery ignoring custom excludes — resolved

- **Implementation:** `src/agents_md_mcp/gitignore.py:22-52`
- **Callers:** `src/agents_md_mcp/project_scanner.py:79`,
  `src/agents_md_mcp/change_detector.py:172`
- **Validation:** `tests/test_perf_fixes.py:97-118`

Gitignore pruning now uses the active `ProjectConfig`. When no config is
provided, discovery performs no exclude-based pruning and retains the original
fallback behavior. A project with `exclude: []` correctly honors a nested
`.gitignore` inside a normally excluded directory.

### 3. Stale payload cache after rewrites — resolved

- **Implementation:** `src/agents_md_mcp/server.py:57-85`,
  `src/agents_md_mcp/server.py:251-256`
- **Validation:** `tests/test_perf_fixes.py:265-320`

Cache identity now uses `(st_mtime_ns, st_size)`, and `_run_pipeline` explicitly
evicts cached text whenever it writes a replacement payload. A production-path
pipeline reproduction confirmed that a cached old payload is evicted and the
new payload is read.

### 4. Traversal-order behavior — resolved by explicit design decision

- **Implementation:** `src/agents_md_mcp/project_scanner.py:76-95`,
  `src/agents_md_mcp/change_detector.py:55-70`
- **Validation:** `tests/test_perf_fixes.py:121-137`

The new walk does not reproduce the filesystem-dependent `Path.rglob` byte
order. Instead, directories and filenames are sorted before traversal, producing
canonical lexicographic top-down order. This is an intentional, documented
behavior delta: the semantic file set is preserved while payload ordering becomes
stable across runs and platforms.

### 5. Unbounded payload-cache retention — resolved

- **Implementation:** `src/agents_md_mcp/server.py:64-74`
- **Validation:** `tests/test_perf_fixes.py:322-329`

The process cache is bounded to four entries and evicts the oldest inserted
payload before admitting another. Abandoned partial reads can no longer grow the
number of retained payloads without bound.

### 6. No proof that excluded directories are pruned — resolved for the primary walk

- **Validation:** `tests/test_perf_fixes.py:139-160`

The test instruments directory visitation and verifies that `_walk_files` never
enters `node_modules`, `bin`, or `obj`, rather than merely checking that their
files are filtered from the result.

### 7. Environment-guard coverage — resolved

- **Validation:** `tests/test_perf_fixes.py:213-262`

Python, JavaScript, TypeScript, and Go detection are exercised, the inactive Rust
alternate regex branch is guarded, and a spy verifies that files without guard
substrings do not invoke regex scanning.

### 8. `.csproj` integration and case handling — resolved

- **Implementation:** `src/agents_md_mcp/context_builder.py:151-156`
- **Validation:** `tests/test_perf_fixes.py:174-208`

`build_payload` passes `.csproj` files from the shared walk, build-output copies
remain excluded, and suffix matching is case-insensitive. A direct production
path reproduction included `Legacy.CSPROJ` in both `package_files` and
`dotnet_projects`.

## Remaining non-blocking validation improvements

These do not indicate current implementation defects, but strengthening them
would make future regressions easier to catch.

1. **Exercise cache invalidation through `_run_pipeline` in the test suite.**
   `test_same_mtime_same_size_rewrite_needs_explicit_invalidation` manually
   performs the eviction it intends to guard. Removing the production eviction
   would not fail that test.

2. **Assert canonical directory traversal more directly.**
   `test_walk_order_is_lexicographic_top_down` leaves
   `by_dir_then_name` unused and mainly proves repeatability and per-directory
   filename sorting. Constructing equivalent trees in different creation orders
   or comparing serialized payloads would better guard `dirnames.sort()`.

3. **Exercise uppercase `.csproj` handling through `build_payload`.**
   The current uppercase test repeats the production suffix expression when
   constructing its list. The implementation is correct, but removing
   `.lower()` from `context_builder.py` would not fail that test.

4. **Add an independent visitation test for `_fs_walk`.**
   Pruning is proven for `_walk_files`; the non-git `_fs_walk` test still checks
   output rather than confirming excluded directories were never entered.

5. **Synchronize the plan's equivalence wording.**
   The plan asks for byte-identical output, while the reviewed implementation
   intentionally adopts canonical ordering. The behavior is deterministic,
   documented, and test-guarded, but the plan should record this accepted
   correctness-oriented deviation if it remains the implementation record.

## Final validation

- `uv run pytest -q`: **241 passed**
- `tests/test_perf_fixes.py`: **25 passed**
- `git diff --check`: clean
- Synthetic tree with 20,000 dependency files:
  - same sorted filtered file set
  - pruned walk approximately **151x faster** in this environment
- Repeated 5 MB payload reads:
  - cached slicing approximately **84x faster** in this environment
- Direct reproductions passed:
  - FIFO exclusion
  - active-config nested gitignore handling
  - same-path pipeline cache invalidation
  - uppercase `.CSPROJ` build integration
  - deterministic walk behavior

## Merge assessment

The remaining items are test-hardening and documentation follow-ups. They do not
block the performance fixes from merging.
