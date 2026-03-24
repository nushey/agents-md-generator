# context_builder.py

## Rol

Es el orquestador del ensamblado del payload. No contiene lógica propia — su única responsabilidad es invocar los módulos especializados en el orden correcto y armar el dict JSON final que el servidor escribe a disco.

## Por qué existe como módulo separado

Antes de la refactorización, este archivo concentraba seis responsabilidades distintas. Al separar cada una en su propio módulo, `context_builder.py` quedó como el único punto que conoce el orden de ejecución y la estructura del payload — una sola razón para cambiar: si cambia el contrato del JSON.

## Lo que orquesta

```
build_payload()
    │
    ├─ project_scanner._scan_project_structure()   → project_structure
    ├─ build_system._detect_build_systems()         → build_system
    ├─ project_scanner._detect_env_vars()           → env_vars
    ├─ project_scanner._detect_entry_points()       → entry_points
    │
    ├─ [por cada FileChange]
    │   ├─ symbol_utils._is_test_file()
    │   ├─ symbol_utils._is_public()
    │   ├─ ast_analyzer.diff_analysis()             → diff semántico
    │   ├─ ast_analyzer.classify_impact()           → clasificación
    │   ├─ symbol_utils._passes_threshold()         → filtrado
    │   ├─ symbol_utils._slim_symbol()              → serialización
    │   └─ symbol_utils._format_full()              → entrada full_analysis
    │
    ├─ aggregator._aggregate_by_directory()         → colapso de dirs
    ├─ symbol_utils._summarize_test_files()         → colapso de tests
    └─ instructions._build_instructions()           → prompt embebido
```

## Estructura del payload resultante

```json
{
  "metadata": {
    "project_name": "...",
    "languages_detected": [...]
  },
  "project_structure": { "directories": {...}, "config_files_found": [...], ... },
  "build_system": { "detected": [...], "scripts": {...} },
  "entry_points": [{ "file": "...", "role": "..." }],
  "env_vars": ["VAR_NAME", ...],
  "changes": [...],
  "full_analysis": [...],
  "existing_agents_md": "...",
  "instructions": "..."
}
```

## Procesamiento por archivo (lógica de negocio central)

Para cada `FileChange` en la lista de cambios:

- **`"deleted"`**: se agrega a `changes` con `impact="high"`. Las eliminaciones son siempre notables.
- **`"new"`**: se formatea con `_format_full`. Va a `full_analysis` (producción) o `test_analysis` según `_is_test_file`.
- **`"modified"` con historial en cache**: se computa diff semántico, se clasifica con `classify_impact`, se filtra por `impact_threshold`. Si ningún cambio supera el threshold → el archivo se omite completamente del payload.
- **`"modified"` sin historial en cache**: se trata como `"new"`.

## Funciones

| Función | Qué hace |
|---|---|
| `build_payload(project_path, config, changes, new_analyses, cache, scan_type)` | Única función pública. Ensambla y retorna el payload completo como dict |

Ver los módulos especializados para el detalle de cada responsabilidad:
- [`build_system.md`](build_system.md) — detección de build tools y scripts
- [`project_scanner.md`](project_scanner.md) — escaneo de estructura, env vars, entry points
- [`aggregator.md`](aggregator.md) — colapso de directorios con patrón común
- [`symbol_utils.md`](symbol_utils.md) — filtrado y formateo de símbolos
- [`instructions.md`](instructions.md) — el prompt embebido en el payload
