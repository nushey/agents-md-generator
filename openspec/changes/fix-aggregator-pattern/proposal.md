# Proposal: Fix Class Pattern Extraction in Aggregator

## Intent

The `generate_agents_md` payload generation is missing the `naming_pattern` attribute for certain DTO and Request/Response directories (e.g., `TPark.Contracts/Requests/` and `TPark.Contracts/Responses/`). 
This occurs because the current implementation of `_extract_class_pattern` in `src/agents_md_mcp/aggregator.py` requires 100% of the class names in a directory to match a common prefix or suffix. When a directory contains a mostly homogeneous pattern (like 20 classes ending with "Request") but also includes an anomalous name (like `RequestWrapper`), the `all()` check fails and the pattern is not extracted.
We need to relax this constraint to an 80% threshold and include matching examples and total matching class count, so that the pattern is still correctly identified and surfaced to the agent.

## Scope

### In Scope
- Modify `_extract_class_pattern` in `src/agents_md_mcp/aggregator.py` to use an 80% matching threshold instead of 100%.
- Update the extraction logic to return the number of matching classes (`total`) and examples that actually match the pattern.
- Update `test_aggregator.py` (if it exists) or add tests to ensure the new 80% threshold logic works with mixed inputs.

### Out of Scope
- Making changes to other language analyzers or wiring detect logic.
- Rewriting the complete `aggregator.py` logic beyond pattern extraction.

## Approach

1. Instead of checking `if all(n.endswith(suffix) for n in class_names)`, count the occurrences of each possible prefix/suffix.
2. Calculate an absolute threshold: `threshold = max(2, int(len(class_names) * 0.8))`.
3. If a suffix or prefix matches `threshold` or more classes, select it as the pattern.
4. Filter `class_names` to only those that match the discovered pattern to return as `examples`, and use `len(matching_examples)` as the `total`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/agents_md_mcp/aggregator.py` | Modified | Updates `_extract_class_pattern` logic. |
| `tests/test_aggregator.py` (or similar) | Modified | Adds test coverage for partial pattern matches. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Pattern false positives due to short names | Low | The function already checks length down to 3 characters and sorts from longest (11) to shortest (3), preferring longer meaningful patterns. Using an 80% threshold maintains high confidence. |
| Breaks existing tests that expect exact match | Low/Med | Run `pytest` before and after to update any affected assertions. |

## Rollback Plan

Revert `src/agents_md_mcp/aggregator.py` to the previous version that relies on the `all()` constraint and drop any new tests added for the partial matching.

## Dependencies

- None (Standard Python library).

## Success Criteria

- [ ] `payload.json` correctly generates `naming_pattern: {"pattern": "*Request", "examples": [...], "total": 20}` for a directory with 20 matching classes and 1 non-matching class.
- [ ] Tests pass via `pytest`.
