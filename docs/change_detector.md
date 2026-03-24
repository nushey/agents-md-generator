# change_detector.py

## Rol

Determina qué archivos del proyecto cambiaron desde el último scan. Es el guardián que decide qué va a ser analizado por AST — si este módulo lo skipea, tree-sitter nunca lo toca. Opera en dos modos: cold start (sin cache) e incremental (con cache).

## Conceptos clave

### git ls-files como fuente de verdad

Para proyectos git, se ejecuta `git ls-files` para obtener la lista de archivos trackeados. Esto tiene tres ventajas sobre un walk del filesystem:
1. Ya respeta `.gitignore` — no hay que parsearlo
2. Excluye archivos en `git/` y otros directorios internos
3. Es más rápido que un `rglob` en proyectos grandes

Si el proyecto NO es un repo git, cae a un filesystem walk con soporte de `.gitignore` vía `pathspec`.

### Pipeline de filtrado en `_filter_paths`

Cada archivo pasa por cuatro filtros en orden:
1. **gitignore** — si está en `.gitignore`, se ignora (solo para non-git repos)
2. **exclude** — si matchea algún patrón de exclusión de la config
3. **include** — si hay lista de include y el archivo no matchea, se ignora
4. **extensión** — si la extensión no está en `EXTENSION_TO_LANGUAGE`, se ignora

Solo los archivos que pasan los cuatro llegan al análisis.

### La lógica de `_is_excluded` y los patrones `**/dir/**`

`fnmatch` por defecto no trata `**` como un wildcard de múltiples segmentos — trata `*` como "cualquier cosa incluido `/`". El problema es con patrones como `**/node_modules/**` cuando el path es `src/node_modules/lodash/index.js`.

La solución tiene dos pasos:
1. `fnmatch.fnmatch(normalized, pattern)` — el path se normaliza primero a forward slashes para que patrones como `**/app/lib/**` funcionen en Windows (donde los paths tienen backslashes)
2. Extracción del token interno: `**/node_modules/**` → `node_modules`, y se verifica si algún componente del path hace match con ese token

Esto cubre el caso donde el directorio excluido está en medio del path, y garantiza comportamiento consistente cross-platform.

### Cold start vs Incremental

**Cold start** (cache = `None`): todos los archivos filtrados se reportan como `"new"`. Se calcula el hash SHA-256 de cada uno. No hay comparación posible.

**Incremental** (cache existe): se comparan los archivos en cache con los actuales:
- Si un archivo de la cache ya no existe en el filesystem → `"deleted"`
- Si el hash del archivo actual difiere del cacheado → `"modified"`
- Si un archivo está en el filesystem pero no en la cache → `"new"`

El hash SHA-256 es el mecanismo de comparación — no se usa `mtime` ni tamaño, que son menos confiables.

### Archivos demasiado grandes

Si un archivo supera `config.max_file_size_bytes` (default 1MB), se skipea con un warning y no aparece en los cambios. Evita que archivos generados enormes (como un bundle JS sin minificar) cuelguen el análisis.

## Funciones

| Función | Qué hace |
|---|---|
| `detect_changes(project_path, config, cache)` | Entry point: devuelve la lista de `FileChange` según el modo de scan |
| `_git_ls_files(project_path)` | Ejecuta `git ls-files`, devuelve lista de paths o `None` |
| `_fs_walk(project_path, gitignore_spec)` | Fallback: walk del filesystem con soporte gitignore |
| `_filter_paths(paths, config, gitignore_spec)` | Aplica todos los filtros en cadena |
| `_is_excluded(path, config)` | Verifica si el path matchea algún patrón de exclusión |
| `_is_included(path, config)` | Verifica si el path matchea la lista de include (vacía = todos incluidos) |
| `_hash_file(path)` | SHA-256 del contenido del archivo |
| `_cold_start(root, filtered_paths, config)` | Genera `FileChange("new")` para todos los archivos |
| `_incremental(root, filtered_paths, config, cache)` | Compara contra cache y genera los diffs |
| `_is_too_large(path, config)` | Verifica si el archivo supera el límite de tamaño |
