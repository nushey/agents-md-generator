# Tasks: Architectural Distillation and Instruction Prioritization

## Phase 1: Foundation (Ordering & Boilerplate)

- [ ] 1.1 Update `src/agents_md_mcp/context_builder.py`: Reorder `payload` dict in `build_payload` to put `instructions` second (index 1).
- [ ] 1.2 Update `src/agents_md_mcp/project_scanner.py`: Add `_BOILERPLATE_DIRS` set containing `Migrations`, `Properties`, `bin`, `obj`.
- [ ] 1.3 Update `src/agents_md_mcp/project_scanner.py`: In `_scan_project_structure`, flag directories matching `_BOILERPLATE_DIRS` as `kind: "boilerplate"`.

## Phase 2: Core Analysis (Entropy & DTO Summarization)

- [ ] 2.1 Update `src/agents_md_mcp/symbol_utils.py`: Add `_is_low_entropy(analysis: FileAnalysis)` function (Logic: >90% symbols are methodless classes/structs).
- [ ] 2.2 Update `src/agents_md_mcp/symbol_utils.py`: Modify `_format_full` to return a minified summary if `_is_low_entropy` is true.
- [ ] 2.3 Ensure minified summary includes `file`, `language`, `kind: "dto_container"`, and `symbols_count`.

## Phase 3: Aggregation (Semantic Clustering)

- [ ] 3.1 Update `src/agents_md_mcp/aggregator.py`: Modify `_aggregate_by_directory` to detect clusters of minified DTO summaries.
- [ ] 3.2 Enhance `directory_summary` to include a `naming_pattern` or `note: "Contains X DTO classes"` for these clusters.

## Phase 4: Testing & Verification

- [ ] 4.1 Create `tests/test_distillation.py`: Unit tests for `_is_low_entropy` with sample `FileAnalysis` objects.
- [ ] 4.2 Create `tests/test_payload_order.py`: Verify `instructions` key position in `build_payload` output.
- [ ] 4.3 Manual Test: Run `generate_agents_md` on a local test project with DTOs and verify payload reduction.
