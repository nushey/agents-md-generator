# Design: Architectural Distillation and Instruction Prioritization

## Technical Approach

The goal is to reduce the cognitive load and token cost of the generated MCP payload by prioritizing high-signal information (Instructions, Logic-heavy Services) and summarizing low-signal information (DTOs, Boilerplate).

We will implement a tiered analysis approach:
1.  **Foundational Phase:** Instructions are moved to the top of the payload.
2.  **Filesystem Phase:** Common boilerplate directories are identified and flagged.
3.  **AST Phase:** Entropy detection identifies files with minimal logic (DTOs) and provides a "slim" summary instead of full member analysis.
4.  **Aggregation Phase:** Directory-level summaries are enhanced to group low-entropy files into meaningful clusters.

## Architecture Decisions

### Decision: In-Place Dictionary Reordering

**Choice**: Reorder the `payload` dictionary keys in `context_builder.py` manually during assembly.
**Alternatives considered**: Using an `OrderedDict` or a post-processing sort.
**Rationale**: Manual assembly is the most explicit and least complex way to ensure `instructions` appears early in the JSON serialization.

### Decision: Entropy-Based Summarization

**Choice**: If a file contains >90% methodless classes, it is marked as `is_dto` and individual symbols are NOT fully formatted.
**Alternatives considered**: Listing only the class names but still providing a `symbols` array.
**Rationale**: For DTOs/Entities, the naming pattern is usually sufficient for an agent to understand the "What" (e.g., `CreateUserRequest`). Detailed property listings are rarely needed during the architectural mapping phase and can be retrieved via `read_file` if necessary.

## Data Flow

```
[Project Path] ──→ [Project Scanner] ──→ (Flag Boilerplate Dirs)
                        │
                        ↓
[Source Files] ──→ [AST Analyzer] ──→ [Symbol Utils] ──→ (Detect Low Entropy)
                                            │
                                            ↓
[File Analyses] ──→ [Aggregator] ──→ (Summarize DTO Clusters)
                        │
                        ↓
[Context Builder] ─────→ [Final Payload] (Instructions at Top)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/agents_md_mcp/context_builder.py` | Modify | Update `build_payload` to reorder dictionary keys. |
| `src/agents_md_mcp/project_scanner.py` | Modify | Add `_BOILERPLATE_DIRS` list and use it in `_scan_project_structure`. |
| `src/agents_md_mcp/symbol_utils.py` | Modify | Add `_is_low_entropy` and update `_format_full` to return slim summaries for DTOs. |
| `src/agents_md_mcp/aggregator.py` | Modify | Update `_aggregate_by_directory` to group DTO-flagged files into summaries. |

## Interfaces / Contracts

```python
# New minified DTO summary structure in full_analysis
{
    "file": "path/to/dto.cs",
    "language": "c_sharp",
    "kind": "dto_container",
    "is_dto": True,
    "symbols_count": 5
}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `_is_low_entropy` | Test with a mix of DTO-only and Logic-heavy files. |
| Unit | `build_payload` order | Assert that `list(payload.keys())[1] == "instructions"`. |
| Integration | `generate_agents_md` | Run on `tests/fixtures/` and verify that the payload size is reduced for DTO-heavy folders. |

## Migration / Rollout

No migration required. This is a non-breaking optimization of the MCP payload.
