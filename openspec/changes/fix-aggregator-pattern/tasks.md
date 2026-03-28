# Implementation Tasks: Fix Class Pattern Extraction in Aggregator

## 1. Infrastructure / Setup
- [x] Analyze `generate_agents_md` payload output and identify missing naming patterns for `TPark.Contracts/Requests/` and `TPark.Contracts/Responses/`.
- [x] Experiment with python script to rewrite `_extract_class_pattern` logic with 80% threshold.

## 2. Implementation
- [x] Modify `_extract_class_pattern` in `src/agents_md_mcp/aggregator.py`:
  - [x] Determine the matching threshold dynamically as `max(2, int(len(class_names) * 0.8))`.
  - [x] Instead of using `all()`, iterate through all class names and build frequency counts for all possible suffixes (lengths 3 to 12).
  - [x] Identify the longest suffix that meets or exceeds the threshold.
  - [x] If no suffix matches, repeat the same frequency counting for prefixes (lengths 3 to 12) and find the longest matching prefix that meets or exceeds the threshold.
  - [x] If a pattern is found, filter `class_names` to keep only those that match the exact suffix/prefix (`matching_examples`).
  - [x] Update the return dictionary to use `matching_examples[:3]` for `examples` and `len(matching_examples)` for `total`.

## 3. Testing & Verification
- [x] Search for existing unit tests covering `aggregator.py` (e.g. `tests/test_aggregator.py`).
- [x] If tests exist, update or add test cases to cover the following scenarios:
  - [x] 100% homogenous class names.
  - [x] 80%+ homogeneous class names with some anomalies.
  - [x] <80% homogeneous class names (should return None).
- [x] Run `pytest` and ensure all tests pass.
- [x] Validate locally or via an integration test that the new logic processes without errors.
