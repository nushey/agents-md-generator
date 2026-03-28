# Heuristics Specification

## Purpose

Defines the detection logic for identifying "Low Entropy" code sections and "Boilerplate" structures.

## Requirements

### Requirement: Low Entropy Detection (DTOs/Entities)

The system SHALL classify a file as `low_entropy` if more than 90% of its symbols are `class` or `struct` kind with ZERO methods.

#### Scenario: Identify DTO-only file

- GIVEN a file `TPark.Contracts/Requests/CreateAttractionRequest.cs` containing only properties
- WHEN the `symbol_utils._format_full` is executed
- THEN it MUST classify the file as a `low_entropy` DTO
- AND it MUST NOT include property-level details in the output

### Requirement: Boilerplate Pattern Recognition

The system SHALL maintain a list of standard boilerplate directory names (e.g., `Migrations`, `Properties`).

#### Scenario: Recognize .NET Properties directory

- GIVEN a directory named `Properties` at the project level
- WHEN the `project_scanner._scan_project_structure` is executed
- THEN it SHOULD flag this directory as `kind: "boilerplate"` in the output
