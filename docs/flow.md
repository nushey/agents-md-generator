# Flujo completo de ejecución

Este documento describe qué pasa desde que Claude Code invoca `generate_agents_md` hasta que AGENTS.md queda escrito en el disco.

---

## Visión general

```
Claude Code
    │
    │  MCP call: generate_agents_md({ project_path, force_full_scan })
    ▼
server.py → generate_agents_md()
    │
    ▼
server.py → _run_pipeline()
    │
    ├─ 1. config.py      → load_config()
    ├─ 2. cache.py       → load_cache() + is_cache_valid()
    ├─ 3. change_detector.py → detect_changes()
    ├─ 4. ast_analyzer.py   → analyze_changes()
    ├─ 5. context_builder.py → build_payload()
    ├─ 6. cache.py       → save_cache()
    └─ 7. disk           → payload.json
    │
    ▼
server.py → _build_response()
    │
    │  MCP response: JSON pequeño (~1k) con instrucciones + path al payload
    ▼
Claude Code
    │
    ├─ STEP 1: Read payload.json (en chunks si es largo)
    ├─ STEP 2: Parsear JSON y usar SOLO esos datos
    ├─ STEP 3: Write AGENTS.md
    ├─ STEP 4: Delete payload.json
    └─ STEP 5: Informar al usuario
```

---

## Paso 1 — Carga de configuración

`load_config(project_path)` busca `.agents-config.json` en la raíz del proyecto. Si lo encuentra, mergea sus valores sobre los defaults. Si no, usa defaults puros.

El resultado es un `ProjectConfig` con:
- Patrones de exclusión/inclusión
- Threshold de impacto (`low`, `medium`, `high`)
- Lenguajes habilitados
- Tamaño máximo de archivo

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

`build_payload(...)` ensambla el JSON final. Es el paso más extenso.

### Análisis del filesystem (independiente del AST)

Mientras se ensambla el payload, se hacen tres análisis adicionales del filesystem que no requieren AST:

**`_scan_project_structure`**: lista directorios, cuenta archivos, detecta el lenguaje dominante por directorio. También detecta config files (`.eslintrc`, `tsconfig.json`, etc.) y archivos de CI (`.github/workflows/*.yml`, etc.).

**`_detect_build_systems`**: busca `package.json`, `pyproject.toml`, `go.mod`, `Makefile`, etc. Para cada uno extrae los scripts ejecutables.

**`_detect_env_vars`**: escanea código fuente con regex por lenguaje y archivos `.env.example`.

**`_detect_entry_points`**: busca archivos cuyo stem es `main`, `index`, `app`, `server`, etc., e infiere su rol.

### Procesamiento por archivo

Para cada `FileChange`:

- **`"deleted"`**: se agrega al `changes_payload` con `impact="high"`
- **`"new"`**: se formatea con todos sus símbolos públicos en `full_analysis_payload`
- **`"modified"` con historial en cache**: se computa diff semántico, se clasifica cada cambio, se filtra por threshold. Si nada supera el threshold → el archivo se omite del payload
- **`"modified"` sin historial**: se trata como `"new"`

Los archivos de test se colapsan en resúmenes por directorio.

### El payload final

```json
{
  "metadata": {...},
  "project_structure": {...},
  "build_system": {...},
  "entry_points": [...],
  "env_vars": [...],
  "changes": [...],
  "full_analysis": [...],
  "existing_agents_md": "...",
  "instructions": "..."
}
```

El campo `instructions` es el prompt que guía a Claude en cómo usar cada campo y qué escribir en cada sección de AGENTS.md.

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

El payload JSON se escribe en `~/.cache/agents-md-generator/<hash>/payload.json`.

Se calcula cuántas líneas tiene. Si supera 2000 líneas, se incluyen instrucciones de chunking en la respuesta. Si no, se lee de una sola vez.

La respuesta que llega a Claude Code es un JSON pequeño:

```json
{
  "status": "ready",
  "payload_file": "/home/user/.cache/agents-md-generator/abc123/payload.json",
  "payload_lines": 847,
  "agents_md_path": "/code/mi-proyecto/AGENTS.md",
  "instructions": "STEP 1 — Read the payload file at: ..."
}
```

---

## Por qué este diseño y no otro

### ¿Por qué no enviar el payload inline en la respuesta MCP?

El payload puede tener miles de líneas para proyectos grandes. Si se enviara inline, todo ese contenido viaja en el contexto de un solo tool call — costoso en tokens, y puede superar límites de tamaño de respuesta. Al escribirlo a disco y que Claude lo lea con `Read`, el consumo de contexto se distribuye en múltiples llamadas y Claude puede procesar en chunks.

### ¿Por qué cache basada en SHA-256 y no en mtime?

`mtime` (tiempo de modificación) es poco confiable: `git checkout`, copias de archivos, y algunas operaciones de build lo alteran sin cambiar el contenido. SHA-256 detecta cambios reales de contenido.

### ¿Por qué el diff es semántico y no textual?

Un `git diff` de un archivo refactorizado puede tener 200 líneas modificadas aunque la API pública no cambió. El diff semántico sobre los símbolos detecta exactamente lo que le importa a AGENTS.md: qué cambió en la superficie pública. Esto también permite el filtrado por `impact_threshold`.

### ¿Por qué las instrucciones para Claude van embebidas en el payload?

Para garantizar consistencia. Si las instrucciones estuvieran hardcodeadas en el prompt del usuario o en el system prompt de Claude Code, podrían variar entre versiones, contextos, o configuraciones. Al estar en el payload que genera el server, el mismo código controla tanto el dato como cómo debe usarlo Claude.
