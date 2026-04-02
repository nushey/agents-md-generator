# Flujo completo de ejecución

Este documento describe los dos flujos disponibles: `generate_agents_md` para crear o actualizar AGENTS.md, y `scan_codebase` para obtener contexto puro del codebase.

---

## Flujo 1 — generate_agents_md (creación/actualización de AGENTS.md)

```
Cliente MCP
    │
    │  MCP call: generate_agents_md({ project_path })
    ▼
server.py → generate_agents_md()
    │
    ├─ config.py       → load_config()
    ├─ connectors.py   → setup_connectors()   ← actualiza CLAUDE.md, .cursorrules, etc.
    │
    ▼
server.py → _run_pipeline(force_full_scan=False, include_agents_md_context=True)
    │
    ├─ 1. config.py          → load_config()
    ├─ 2. cache.py           → load_cache() + is_cache_valid()
    ├─ 3. change_detector.py → detect_changes()
    ├─ 4. ast_analyzer.py    → analyze_changes()
    ├─ 5. context_builder.py → build_payload(include_agents_md_context=True)
    │       └─ instructions.py → _build_instructions()   ← inyectado en el payload
    │       └─ lee AGENTS.md existente si hay            ← inyectado en el payload
    ├─ 6. cache.py           → save_cache()
    └─ 7. disco              → payload.json (con instrucciones + existing_agents_md)
    │
    ▼
server.py → _build_response()   ← respuesta neutra con total_chunks
    │
    │  MCP response: { status, total_chunks, agents_md_path, instructions }
    ▼
Cliente MCP
    │
    ├─ STEP 1: Llamar read_payload_chunk(chunk_index=0), luego 1, 2… hasta has_more=false
    ├─ STEP 2: Concatenar todos los campos "data" → payload completo
    ├─ STEP 3: Leer campo "instructions" del payload → reglas de escritura
    ├─ STEP 4: Escribir AGENTS.md usando payload + reglas
    └─ STEP 5: Informar al usuario
         (payload.json se borra automáticamente al leer el último chunk)
```

---

## Flujo 2 — scan_codebase (contexto puro)

```
Cliente MCP
    │
    │  MCP call: scan_codebase({ project_path, force_full_scan })
    ▼
server.py → scan_codebase()
    │
    ▼
server.py → _run_pipeline(force_full_scan=True, include_agents_md_context=False)
    │
    ├─ 1. config.py          → load_config()
    ├─ 2. cache.py           → load_cache() + is_cache_valid()
    ├─ 3. change_detector.py → detect_changes()
    ├─ 4. ast_analyzer.py    → analyze_changes()
    ├─ 5. context_builder.py → build_payload(include_agents_md_context=False)
    │       └─ SIN instructions, SIN existing_agents_md
    ├─ 6. cache.py           → save_cache()
    └─ 7. disco              → payload.json (datos puros)
    │
    ▼
server.py → _build_response()
    │
    │  MCP response: { status, total_chunks, instructions }
    ▼
Cliente MCP
    │
    ├─ Llamar read_payload_chunk hasta has_more=false
    └─ Usar el payload para cualquier propósito (code review, planning, Q&A)
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

Si `force_full_scan = True` → se ignora cualquier cache (cold start forzado). `scan_codebase` default es `True`. `generate_agents_md` siempre usa `False` — si no hay cache, `change_detector` hace cold start igual.

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

`build_payload(..., include_agents_md_context)` en `context_builder.py` orquesta los scanners y ensambla el JSON final.

Cuando `include_agents_md_context=True` (solo desde `generate_agents_md`):
- Lee el AGENTS.md existente del disco si lo hay → campo `existing_agents_md`
- Genera las reglas de escritura via `_build_instructions(has_existing)` → campo `instructions`
- Ambos campos se insertan en el payload: `instructions` después de `metadata`, `existing_agents_md` al final

Cuando `include_agents_md_context=False` (desde `scan_codebase`):
- El payload no contiene `instructions` ni `existing_agents_md`
- Datos puros sin mandato de AGENTS.md

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

La respuesta que llega al cliente MCP es un dict pequeño:

```json
{
  "status": "ready",
  "total_chunks": 2,
  "instructions": "Codebase analysis complete. Retrieve the full payload by calling read_payload_chunk..."
}
```

En el caso de `generate_agents_md`, se enriquece con `agents_md_path` e instrucciones específicas para escribir AGENTS.md.

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

### ¿Por qué generate_agents_md llama scan internamente?

La alternativa anterior instruía al agente a llamar `scan_codebase` como primer paso. Eso introduce no-determinismo: el agente puede equivocarse con los parámetros, saltear el paso, o llamarlo en el orden incorrecto. Al mover el scan al interior de `generate_agents_md`, el flujo de AGENTS.md es completamente determinístico — el agente recibe instrucciones para leer chunks y escribir el archivo, nada más.

### ¿Por qué las instrucciones van en el payload y no en la respuesta del tool?

Si las instrucciones de escritura estuvieran en la respuesta de `generate_agents_md`, el agente necesitaría combinar dos fuentes de datos: la respuesta del tool y el payload de los chunks. Al inyectarlas dentro del payload, el agente solo necesita leer los chunks y tiene todo en un único objeto JSON — menor superficie de error.

### ¿Por qué read_payload_chunk en vez de leer el archivo directamente?

La alternativa anterior era instruir al cliente a leer `payload.json` con su tool `Read`. Eso requería que el cliente tuviera acceso al filesystem y conociera la ruta exacta del cache. Con `read_payload_chunk`, el flujo es 100% MCP — cualquier cliente compatible puede seguirlo sin acceso al filesystem.

### ¿Por qué 500 líneas por chunk?

Es un balance entre número de llamadas MCP y tamaño de cada respuesta. Chunks más grandes reducen las llamadas pero aumentan el riesgo de superar límites. Chunks más chicos generan overhead en proyectos grandes.

### ¿Por qué cache basada en SHA-256 y no en mtime?

`mtime` es poco confiable: `git checkout`, copias de archivos, y algunas operaciones de build lo alteran sin cambiar el contenido. SHA-256 detecta cambios reales de contenido.

### ¿Por qué el diff es semántico y no textual?

Un `git diff` de un archivo refactorizado puede tener 200 líneas modificadas aunque la API pública no cambió. El diff semántico sobre los símbolos detecta exactamente lo que le importa a AGENTS.md: qué cambió en la superficie pública.
