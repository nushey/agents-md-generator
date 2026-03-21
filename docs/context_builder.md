# context_builder.py

## Rol

Es el módulo más complejo del sistema. Toma todos los resultados del análisis y los ensambla en el JSON payload que Claude Code va a leer para generar AGENTS.md. También detecta build systems, variables de entorno, entry points, y estructura del proyecto mediante análisis estático del filesystem — sin AST.

## Conceptos clave

### build_payload — el ensamblador central

Recibe todo lo que saben los otros módulos y produce un único dict JSON con esta estructura:

```json
{
  "metadata": { "project_name": "...", "languages_detected": [...] },
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

Cada campo de este JSON tiene una instrucción correspondiente en el campo `instructions` que le dice a Claude cómo usarlo.

### Detección de build systems sin AST

`_detect_build_systems` busca archivos marcadores en el filesystem:
- `*.sln` → dotnet
- `package.json` → npm
- `go.mod` → go
- `pyproject.toml` → python/uv/poetry
- `Cargo.toml` → rust
- etc.

Luego extrae los scripts ejecutables de cada uno:
- **npm**: lee `package.json["scripts"]`
- **Python/uv**: lee `pyproject.toml`, detecta el runner (uv, poetry, pip) por la presencia de lock files, y construye los comandos de install/test
- **Make**: parsea las líneas del Makefile que terminan en `:` (targets)

### Variables de entorno — dos fuentes

1. **Archivos de código fuente**: regex por lenguaje que detecta `process.env.VAR`, `os.environ['VAR']`, `os.Getenv("VAR")`, `ENV['VAR']`, etc.
2. **Archivos `.env.example`**, `.env.template`, `.env.sample`: se parsean línea a línea buscando `VAR_NAME=`

Resultado: lista ordenada de nombres de variables únicas. Si el proyecto no tiene variables de entorno referencidas en código, el campo queda vacío y se omite de AGENTS.md.

### Entry points — inferencia de rol

Archivos cuyo stem (nombre sin extensión) es `index`, `main`, `app`, `server`, `program`, `bootstrap` o `startup` se detectan como entry points. Para cada uno se infiere un rol basado en el path completo:
- Si el path contiene `server` → "HTTP server bootstrap"
- Si contiene `electron` → "Electron main process"
- Si el stem es `main` → "Application entry point"
- etc.

Se evitan duplicados por directorio (si hay `index.js` e `index.ts` en el mismo dir, solo aparece uno).

### Diff semántico en el payload

Para archivos `"modified"` con historial en cache, se computa el diff semántico:
- Se llama a `diff_analysis(old_symbols, new_symbols)`
- Cada símbolo del diff se clasifica con `classify_impact`
- Se filtra por `impact_threshold`
- Si después del filtro no queda nada → el archivo se omite del payload (por debajo del threshold)

Esto es clave: no todo cambio de archivo produce entrada en el payload.

### Archivos de test — tratamiento especial

`_is_test_file` detecta archivos de test por nombre y path (`test_`, `_test.py`, `.spec.ts`, `/tests/`, `/__tests__/`, etc.). Estos archivos se procesan por separado y al final se colapsan en un resumen por directorio via `_summarize_test_files`. En vez de listar 200 tests con sus funciones, el payload dice: "en `TPark.Service.Tests/` hay 47 archivos con 312 funciones de test". Claude usa esto para la sección de Testing Instructions sin que el payload explote de tamaño.

### _build_instructions — el prompt embebido

El campo `instructions` del payload ES un prompt para Claude. Define:
- Qué debe hacer (CREATE o UPDATE)
- Reglas absolutas (no leer archivos, no llamar al tool de nuevo, no inventar comandos)
- Cómo usar cada campo del payload (qué sintetizar, qué copiar verbatim)
- El formato exacto de cada sección de AGENTS.md

Es el documento que hace que el output de Claude sea consistente independientemente del modelo.

### _is_public / _slim_symbol

- `_is_public(sym)`: filtra symbols privados (visibility `private`/`protected` o nombres que empiezan con `_`)
- `_slim_symbol(sym)`: reduce un símbolo a solo los campos que Claude necesita para AGENTS.md — elimina `line_start`, `line_end`, `parent` que no son útiles para el output

## Funciones principales

| Función | Qué hace |
|---|---|
| `build_payload(...)` | Ensambla el JSON payload completo |
| `_detect_build_systems(root)` | Detecta herramientas de build y extrae scripts ejecutables |
| `_scan_project_structure(root, config)` | Escanea directorios, config files, CI files, test dirs |
| `_detect_env_vars(root, config)` | Detecta variables de entorno en código y archivos `.env.*` |
| `_detect_entry_points(root, config)` | Detecta archivos de bootstrap e infiere su rol |
| `_build_instructions(has_existing)` | Construye el prompt embebido en el payload |
| `_is_test_file(path)` | Detecta si un archivo es de test por nombre/path |
| `_summarize_test_files(entries)` | Colapsa archivos de test en resúmenes por directorio |
| `_format_full(path, status, analysis)` | Formatea un archivo para `full_analysis` con símbolos públicos |
| `_is_public(sym)` | Filtra símbolos privados |
| `_slim_symbol(sym)` | Reduce símbolo a los campos necesarios para el payload |
| `_passes_threshold(impact, threshold)` | Verifica si un impacto supera el threshold configurado |
