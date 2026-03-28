# Delta for Aggregator

## MODIFIED Requirements

### Requirement: Extract Class Naming Pattern

The system MUST identify a common suffix or prefix if it is shared by at least 80% (and at minimum 2) of the classes in a directory. It MUST return the pattern, up to 3 examples of classes that match that pattern, and the total count of classes matching the pattern.
(Previously: The system MUST identify a common suffix or prefix if it is shared by 100% of the classes. It returned the pattern, up to 3 class names from the directory, and the total count of classes in the directory.)

#### Scenario: All classes match a pattern

- GIVEN a directory with 5 classes, all ending in `Service`
- WHEN `_extract_class_pattern` is called
- THEN it MUST return `{"pattern": "*Service", "examples": ["UserService", ...], "total": 5}`

#### Scenario: Mostly homogeneous directory with an anomaly

- GIVEN a directory with 20 classes ending in `Request` and 1 class named `RequestWrapper`
- WHEN `_extract_class_pattern` is called
- THEN it MUST identify `*Request` as the pattern
- AND it MUST return the matching total count as 20
- AND the examples MUST only include classes that end in `Request`

#### Scenario: No dominant pattern (below threshold)

- GIVEN a directory with 10 classes, where only 5 share a common suffix (50%)
- WHEN `_extract_class_pattern` is called
- THEN it MUST return `None`

#### Scenario: Short patterns are ignored

- GIVEN a directory where all classes end in `s` but have no longer common suffix
- WHEN `_extract_class_pattern` is called
- THEN it MUST NOT identify `*s` as a pattern (length < 3)
- AND it MUST return `None` (assuming no longer prefix matches either)
