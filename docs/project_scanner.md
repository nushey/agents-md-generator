# project_scanner.py

## Rol

Agrupa tres scanners de filesystem que no requieren AST: estructura del proyecto, variables de entorno, y entry points. Los tres comparten el mismo contexto (gitignore, exclusiones, config) y operan con filesystem traversal — de ahí su cohesión en un único módulo.

## Scanners

### `_scan_project_structure`

Produce un mapa de la organización del proyecto:

- **`root_files`**: archivos visibles en la raíz (hasta 30, sin dotfiles)
- **`top_level_dirs`**: subconjunto de `directories` con solo los directorios inmediatos a la raíz (sin `/` en el key)
- **`directories`**: por cada directorio (hasta profundidad 3), `file_count` y `languages` (lista de lenguajes detectados por extensión, en texto plano ordenado: `"css, html, javascript"`). Directorios más profundos se agregan al ancestro de profundidad 3 acumulando su `file_count`
- **`config_files_found`**: archivos de configuración de herramientas presentes (`tsconfig.json`, `.eslintrc*`, `pyproject.toml`, `mypy.ini`, etc.)
- **`ci_files_found`**: archivos de CI detectados (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, etc.)
- **`test_directories`**: directorios de test detectados por nombre (`tests/`, `spec/`, `__tests__/`, `*.Tests/`, etc.)

Todos los archivos pasan por gitignore + exclusiones de config antes de ser contados.

#### Depth cap en `directories`

La constante `_MAX_DIR_DEPTH = 3` limita la profundidad. Un archivo en `src/modules/auth/handlers/middleware/` se acumula en `src/modules/auth/`. Esto evita explosión de entradas en proyectos con jerarquías profundas (de ~10k líneas a ~200–400 entradas útiles).

### `_detect_env_vars`

Detecta nombres de variables de entorno referenciadas en el proyecto mediante dos fuentes:

1. **Código fuente**: regex por lenguaje que detecta los patrones de acceso a env:
   - JS/TS: `process.env.VAR_NAME`
   - Python: `os.environ['VAR']`, `os.getenv('VAR')`
   - Go: `os.Getenv("VAR")`
   - Ruby: `ENV['VAR']`
   - Rust: `env!("VAR")`

2. **Archivos `.env.*`**: `.env.example`, `.env.template`, `.env.sample`, `.env.test` — se parsean línea a línea buscando `VAR_NAME=`

Retorna una lista ordenada de nombres únicos en mayúsculas. Si el proyecto no referencia variables de entorno, retorna lista vacía y el campo se omite de AGENTS.md.

### `_detect_entry_points`

Detecta archivos de bootstrap e infiere su rol. Un archivo es candidato si su stem (nombre sin extensión) es uno de: `index`, `main`, `app`, `server`, `program`, `bootstrap`, `startup`.

Para evitar duplicados (`index.js` + `index.ts` en el mismo directorio), se guarda un `dir_key = "parent/stem"` y se skipea si ya fue visto.

El rol se infiere del path completo:

| Condición en el path | Rol asignado |
|---|---|
| contiene `electron` | Electron main process |
| contiene `preload` | Electron preload script |
| contiene `routes` | Route definitions |
| contiene `api` | API module index |
| contiene `server` | HTTP server bootstrap |
| stem es `main` | Application entry point |
| stem es `app` | Application setup |
| stem es `server` | HTTP server bootstrap |
| ninguna de las anteriores | Module index |

Los archivos de test se excluyen vía `_is_test_file`.

## Extensibilidad (OCP implícito)

- Nuevos patrones de CI: agregar a `_CI_PATTERNS`
- Nuevas herramientas de config: agregar a `_CONFIG_FILES`
- Nuevos lenguajes de env var: agregar a `_ENV_PATTERNS`
- Nuevos stems de entry point: agregar a `_ENTRY_STEMS`
- Nuevas inferencias de rol: agregar a `_ROLE_HINTS`

Ningún cambio requiere modificar los algoritmos de traversal.

## Funciones

| Función | Qué hace |
|---|---|
| `_scan_project_structure(root, config)` | Escanea directorios, config files, CI files y test dirs. Retorna dict con la estructura del proyecto |
| `_detect_env_vars(root, config)` | Detecta variables de entorno en código fuente y archivos `.env.*`. Retorna lista ordenada de nombres |
| `_detect_entry_points(root, config)` | Detecta archivos de bootstrap e infiere su rol. Retorna lista de `{"file": ..., "role": ...}` |
| `_infer_entry_role(rel, stem)` | Determina el rol de un entry point a partir de su path y stem |
