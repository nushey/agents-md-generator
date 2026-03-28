# Proposal: Architectural Distillation and Instruction Prioritization

## Intent

The current MCP payload for large projects (like TPark) contains significant "noise" from boilerplate directories (Migrations, Properties) and low-entropy files (DTOs, Entities). This bloat increases context costs and can distract the generating agent from core business logic. Additionally, project-specific instructions are currently placed at the end of the payload, whereas they should be foundational and appear first.

## Scope

### In Scope
- **Instruction Prioritization:** Move `instructions` to the top of the JSON payload.
- **Boilerplate Directory Suppression:** Detect and collapse "standard" boilerplate directories (Migrations, Properties, bin/obj if not ignored) in the directory listing.
- **Low-Entropy File Summarization:** Identify DTOs, Entities, and Migrations during AST analysis and provide a "slim" summary (name + kind + tag) instead of a full member listing in `full_analysis`.
- **Directory Significance Map:** Enhance the aggregator to treat directories with 100% low-entropy files as a single "Pattern" entry.

### Out of Scope
- Modifying the AST parser itself (only the formatting/aggregation logic).
- Changing how `AGENTS.md` is rendered (only the payload it receives).

## Approach

1.  **Payload Reordering:** Update `context_builder.py` to insert `instructions` immediately after `metadata`.
2.  **Boilerplate Heuristics:** In `project_scanner.py`, add a list of `_BOILERPLATE_DIR_NAMES` and filter them from the `directories` and `top_level_dirs` output if they match certain criteria (e.g., only contain generated code).
3.  **Entropy-Aware Formatting:** In `symbol_utils.py`, enhance `_format_full` to detect "Low Entropy" files (DTOs/Entities) and return a minified version that omits methods/properties.
4.  **Aggregator Refinement:** Update `aggregator.py` to use these new "Low Entropy" tags to more aggressively collapse folders into single-line summaries (e.g., "34 Entities (DTOs)").

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/agents_md_mcp/context_builder.py` | Modified | Reorder payload keys. |
| `src/agents_md_mcp/project_scanner.py` | Modified | Add boilerplate directory filtering. |
| `src/agents_md_mcp/symbol_utils.py` | Modified | Implement entropy-aware symbol formatting. |
| `src/agents_md_mcp/aggregator.py` | Modified | Refine directory aggregation for low-entropy clusters. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Over-aggressive suppression of important files | Low | Use conservative heuristics (e.g., check for logic/methods before suppressing). |
| Breaking existing payload consumers | Low | Payload structure remains a superset; only internal ordering and detail level change. |

## Rollback Plan

Revert changes to the four affected files in `src/agents_md_mcp/`.

## Dependencies

- None.

## Success Criteria

- [ ] `instructions` appears at the top of the payload.
- [ ] Boilerplate directories (like `Migrations/`) are collapsed or removed from the directory listing.
- [ ] DTO/Entity files in `full_analysis` no longer list properties/methods, only the class name and `is_dto` flag.
- [ ] Total payload size for a large project is reduced by at least 30-50%.
