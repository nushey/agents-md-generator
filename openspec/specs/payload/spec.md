# Payload Specification

## Purpose

Defines the structure, ordering, and content requirements for the MCP JSON payload generated for `AGENTS.md` consumption.

## Requirements

### Requirement: Instruction Prioritization

The system SHALL place the `instructions` object at the beginning of the payload, immediately after the `metadata` object.

#### Scenario: Verify instruction placement in payload

- GIVEN a project with a `GEMINI.md` or existing `AGENTS.md`
- WHEN the `generate_agents_md` tool is executed
- THEN the resulting JSON payload MUST contain the `instructions` key at index 1 (0-based)
- AND the `metadata` key MUST be at index 0

### Requirement: Boilerplate Directory Suppression

The system SHALL detect and suppress standard boilerplate directories in the `project_structure` output.

#### Scenario: Suppress .NET Migrations directory

- GIVEN a .NET project with a `DataAccess/Migrations/` directory
- WHEN the project structure scan is performed
- THEN the `directories` and `top_level_dirs` objects SHOULD NOT list the individual files inside `Migrations/`
- AND SHOULD instead provide a single entry for the directory with a `kind: "boilerplate"` tag

### Requirement: Low-Entropy File Summarization

The system SHALL identify files that primarily contain data structures (DTOs, Entities) and provide a minified summary in `full_analysis`.

#### Scenario: Summarize DTO folder

- GIVEN a directory `Contracts/Requests/` containing 20 DTO classes with no methods
- WHEN the AST analysis is performed
- THEN the `full_analysis` entry for this directory MUST NOT list every property of every class
- AND MUST instead provide a summary count and a `is_dto: true` indicator for the cluster
