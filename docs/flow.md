# Flujo completo de ejecución

Este documento describe qué pasa desde que el cliente MCP invoca `scan_codebase` hasta que AGENTS.md queda escrito en el disco.

---

## Visión general

```
Cliente MCP
    │
    │  MCP call: scan_codebase({ project_path, force_full_scan })
    ▼
server.py → scan_codebase()
    │
    ▼
server.py → _run_pipeline()
    │
    ├─ 1. config.py          → load_config()
    ├─ 2. cache.py           → load_cache() + is_cache_valid()
    ├─ 3. change_detector.py → detect_changes()
    ├─ 4. ast_analyzer.py    → analyze_changes()
    ├─ 5. context_builder.py → build_payload()
    ├─ 6. cache.py           → save_cache()
    └─ 7. disco              → payload.json
    │
    ▼
server.py → _build_response()
    │
    │  MCP response: JSON pequeño (~1k) con total_chunks e instrucciones
    ▼
Cliente MCP
    │
    ├─ STEP 1: Llamar read_payload_chunk(chunk_index=0), luego 1, 2… hasta has_more=false
    ├─ STEP 2: Concatenar todos los campos "data" y parsear como JSON
    ├─ STEP 3: Escribir AGENTS.md usando solo esos datos
    └─ STEP 4: Informar al usuario
         (payload.json se borra automáticamente al leer el último chunk)
```

---

## Paso 1 — Carga de configuración

`load_config(project_path)` busca `.agents-config.json` en la raíz del proyecto. Si lo encuentra, mergea sus valores sobre los defaults. Si no, usa defaults puros.

El resultado es un `ProjectConfig` con:
- Patrones de exclusión/inclusión
- Lenguajes habilitados
- Tamaño máximo de archivo
- `SizeProfile` resuelto desde `project_size` — contiene todos los caps y thresholds de compresión (métodos por clase, símbolos por archivo, agregación de directorios, caps de rutas, profundidad de árbol, y filtro de impacto)

---

## Paso 2 — Cache

### ¿Hay cache?

Si `force_full_scan = True` → se ignora cualquier cache (cold start forzado).

Si no → `load_cache(project_path)` intenta leer `~/.cache/agents-md-generator/<project-hash>/cache.json`.

### ¿Es válida?

Si la cache existe, `is_cache_valid()` ejecuta `git cat-file -t <base_commit>`. Si el commit ya no existe en el repo (rebase, clone limpio), la cache se descarta y se hace cold start.

---

## Paso 3 — Detección de cambios

`detect_changes(project_path, config, cache)` determina qué archivos analizar.

### Obtener lista de archivos

- **Git repo**: `git ls-files` → lista de archivos trackeados (ya respeta .gitignore)
- **Non-git**: filesystem walk + parseo de `.gitignore` con pathspec

### Filtrar

Cada archivo pasa por: gitignore → exclude patterns → include patterns → extensión soportada. Los que no pasan se ignoran completamente.

### Clasificar cambios

- **Sin cache (cold start)**: todos los archivos filtrados → `status="new"` con SHA-256
- **Con cache (incremental)**:
  - Archivos en cache que ya no existen → `status="deleted"`
  - Archivos en cache cuyo SHA-256 cambió → `status="modified"`
  - Archivos nuevos no en cache → `status="new"`
  - Archivos en cache con mismo hash → **no aparecen, no se tocan**

Si la lista de cambios está vacía → se retorna `{ "status": "no_changes" }` y el pipeline termina acá.

---

## Paso 4 — Análisis AST

`analyze_changes(project_path, changes, config, cache)` parsea los archivos cambiados con tree-sitter.

Para cada `FileChange` que no sea `"deleted"`:
1. Se determina el lenguaje por extensión (`config.language_for_extension`)
2. Se obtiene (o instancia) el analyzer correcto vía `_get_analyzer`
3. Se leen los bytes del archivo
4. `analyzer.analyze(path, source)` ejecuta el parser tree-sitter y extrae símbolos

El resultado es `{ path → FileAnalysis }` con todos los símbolos públicos + privados del archivo.

---

## Paso 5 — Construcción del payload

`build_payload(...)` en `context_builder.py` orquesta los scanners y ensambla el JSON final.

### Scanners del filesystem (independientes del AST)

Cuatro módulos especializados hacen análisis estático del filesystem en paralelo conceptual:

- **`project_scanner._scan_project_structure`**: lista directorios, cuenta archivos, detecta el lenguaje dominante por directorio. Detecta y marca directorios de boilerplate (e.g., `Migrations`, `bin`, `obj`) con `"kind": "boilerplate"`. También detecta config files (`.eslintrc`, `tsconfig.json`, etc.) y archivos de CI.
- **`build_system._detect_build_systems`**: busca `package.json`, `pyproject.toml`, `go.mod`, `Makefile`, etc. Para cada uno extrae los scripts ejecutables.
- **`project_scanner._detect_env_vars`**: escanea código fuente con regex por lenguaje y archivos `.env.example`.
- **`project_scanner._detect_entry_points`**: busca archivos cuyo stem es `main`, `index`, `app`, `server`, etc., e infiere su rol.

### Procesamiento por archivo

Para cada `FileChange`:

- **`"deleted"`**: se agrega al `changes_payload` con `impact="high"`
- **`"new"`**: se formatea con sus símbolos públicos. Si el archivo es detectado como de "baja entropía" (e.g., DTOs/Entidades sin lógica), se devuelve un resumen minificado (`kind: "dto_container"`) en lugar de listar todos sus símbolos.
- **`"modified"` con historial en cache**: se computa diff semántico, se clasifica cada cambio con `classify_impact`, se filtra por threshold. Si nada supera el threshold → el archivo se omite del payload
- **`"modified"` sin historial**: se trata como `"new"`

### Agregación de directorios

Los archivos de producción pasan por `aggregator._aggregate_by_directory`. Todo directorio que supera el threshold de agregación se colapsa en algún tipo de `directory_summary` — nunca queda como entradas individuales sin acotar:

- **Patrón de métodos comunes**: si ≥ 2 firmas de métodos aparecen en ≥ 60% de los archivos con cobertura ≥ 40%, se genera un summary con `common_methods`, `outliers` y `naming_pattern`.
- **Directorio DTO**: si ≥ 80% de los archivos son clases sin métodos (o todos fueron minificados como `dto_container`), se genera un resumen semántico DTO.
- **Fallback genérico**: directorios que no matchean ningún patrón se colapsan igualmente con `sample_files` y `naming_pattern` si existe. Esto evita que directorios grandes sin patrón detectable inflen el payload.

### El payload final

```json
{
  "metadata": {...},
  "instructions": "...",
  "project_structure": {...},
  "build_system": {...},
  "entry_points": [...],
  "env_vars": [...],
  "changes": [...],
  "full_analysis": [...],
  "existing_agents_md": "..."
}
```

El campo `instructions` (generado por `instructions._build_instructions`) ahora se ubica al inicio del payload para establecer las reglas fundamentales antes de que el modelo procese el resto del contexto.

---

## Paso 6 — Actualización de cache

Se construye una nueva cache desde cero:

1. Se crea una `CacheData` vacía con el HEAD commit actual
2. Se copian desde la cache anterior todas las entradas que **no** cambiaron (paths no en la lista de cambios)
3. Para cada archivo analizado en este run, se agrega la nueva entrada con el nuevo hash y los símbolos públicos
4. Para archivos de test, se guarda solo el hash (sin símbolos — no se necesitan para diff futuro)
5. Se persiste en disco

---

## Paso 7 — Escritura del payload y respuesta

El payload JSON se escribe en `~/.cache/agents-md-generator/<project-hash>/payload.json`.

Se calcula cuántas líneas tiene y cuántos chunks de 500 líneas eso representa. La respuesta que llega al cliente MCP es un JSON pequeño:

```json
{
  "status": "ready",
  "payload_lines": 847,
  "total_chunks": 2,
  "agents_md_path": "/code/mi-proyecto/AGENTS.md",
  "instructions": "STEP 1 — Retrieve the full payload by calling read_payload_chunk..."
}
```

---

## Paso 8 — Streaming del payload (read_payload_chunk)

El cliente llama `read_payload_chunk` repetidamente con `chunk_index` empezando en 0. Cada respuesta incluye:

```json
{
  "chunk_index": 0,
  "total_chunks": 2,
  "has_more": true,
  "data": "...500 líneas del payload..."
}
```

Al leer el último chunk (`has_more: false`), el archivo `payload.json` se borra automáticamente del disco. El cliente concatena todos los campos `data` en orden y parsea el resultado como JSON.

---

## Por qué este diseño y no otro

### ¿Por qué read_payload_chunk en vez de leer el archivo directamente?

La alternativa anterior era instruir al cliente a leer `payload.json` con su tool `Read`. Eso requería que el cliente tuviera acceso al filesystem y conociera la ruta exacta del cache. Con `read_payload_chunk`, el flujo es 100% MCP — cualquier cliente compatible (Claude Code, Cursor, Gemini CLI, Windsurf) puede seguirlo sin necesidad de acceso al filesystem. El server gestiona completamente el ciclo de vida del archivo.

### ¿Por qué 500 líneas por chunk?

Es un balance entre número de llamadas MCP y tamaño de cada respuesta. Chunks más grandes reducen las llamadas pero aumentan el riesgo de superar límites de respuesta. Chunks más chicos generan demasiado overhead de llamadas en proyectos grandes.

### ¿Por qué cache basada en SHA-256 y no en mtime?

`mtime` (tiempo de modificación) es poco confiable: `git checkout`, copias de archivos, y algunas operaciones de build lo alteran sin cambiar el contenido. SHA-256 detecta cambios reales de contenido.

### ¿Por qué el diff es semántico y no textual?

Un `git diff` de un archivo refactorizado puede tener 200 líneas modificadas aunque la API pública no cambió. El diff semántico sobre los símbolos detecta exactamente lo que le importa a AGENTS.md: qué cambió en la superficie pública. El filtrado de impacto se deriva del `SizeProfile` — medium para proyectos small/medium, high para large.

### ¿Por qué las instrucciones para el cliente van embebidas en el payload?

Para garantizar consistencia. Si las instrucciones estuvieran hardcodeadas en el prompt del usuario o en el system prompt del cliente, podrían variar entre versiones, contextos, o configuraciones. Al estar en el payload que genera el server, el mismo código controla tanto el dato como cómo debe usarlo el modelo.
