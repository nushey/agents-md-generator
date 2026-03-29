# config.py

## Rol

Carga y resuelve la configuración del proyecto analizado. Si el proyecto tiene `.agents-config.json`, lo lee. Si no, usa defaults. El resultado es un objeto `ProjectConfig` que todos los módulos usan para saber qué archivos incluir, qué excluir, y qué lenguajes analizar.

## Conceptos clave

### Merge con defaults

Cuando se encuentra un `.agents-config.json` parcial, se hace `{**DEFAULT_CONFIG, **raw}` — los campos del usuario sobreescriben los defaults, pero los campos no especificados se completan automáticamente. Así un usuario puede poner solo `{ "project_size": "large" }` y todo lo demás funciona.

### SizeProfile

Dataclass inmutable (`frozen=True, slots=True`) que contiene todos los knobs de compresión del payload derivados de `project_size`. Los tres perfiles (`small`, `medium`, `large`) están definidos en `SIZE_PROFILES` y cada uno ajusta: caps de métodos/símbolos/archivos, thresholds de agregación, profundidad de directorios, caps de rutas, y filtro de impacto.

`ProjectConfig` resuelve el perfil en `__init__` y lo expone como `config.profile`. Todos los módulos downstream reciben este `SizeProfile` en vez de leer constantes globales.

### EXTENSION_TO_LANGUAGE

Mapa estático de extensión de archivo → clave de lenguaje tree-sitter. Este mapa es el contrato entre el sistema de archivos y los analyzers de AST:

```python
".py"  → "python"
".cs"  → "c_sharp"
".ts"  → "typescript"
".tsx" → "typescript"   # tsx usa el mismo analyzer con grammar diferente
".js"  → "javascript"
".jsx" → "javascript"
".go"  → "go"
".java"→ "java"
".rs"  → "rust"
".rb"  → "ruby"
```

Cualquier extensión que no esté acá es ignorada automáticamente — incluyendo `.png`, `.json`, `.md`, etc.

### language_for_extension

Recibe una extensión y devuelve la clave de lenguaje, o `None` si no está soportada. Si `languages` es `"auto"` (default), acepta todos los lenguajes del mapa. Si es una lista explícita como `["typescript", "python"]`, filtra — un archivo `.go` sería ignorado en ese caso.

### Los patrones de exclusión por default

Los defaults excluyen directorios que nunca tienen código relevante para AGENTS.md:
- Dependencias: `node_modules`, `vendor`, `packages`
- Outputs: `dist`, `build`, `bin`, `obj`
- Entornos virtuales: `.venv`, `venv`
- Cache de Python: `__pycache__`
- Assets minificados: `*.min.js`, `*.min.css`, `*.bundle.js`
- Vendor frontend: `bower_components`, `app/lib` (AngularJS), `wwwroot/lib`, `wwwroot/libs` (ASP.NET), `static/vendor`, `public/vendor`, `assets/vendor`
- Dependencias Python instaladas en el repo: `site-packages`

Los proyectos pueden extender o reemplazar esta lista vía `.agents-config.json`.

### max_file_size_bytes

Límite de 1MB por archivo. Archivos más grandes se skipean con un warning. Esto evita que archivos generados o binarios renombrados con extensión `.js` tiren abajo el proceso.

## Funciones y clase

| Símbolo | Qué hace |
|---|---|
| `SizeProfile` | Dataclass inmutable con todos los knobs de compresión derivados de `project_size` |
| `SIZE_PROFILES` | Dict `{"small": ..., "medium": ..., "large": ...}` con los tres perfiles predefinidos |
| `DEFAULT_CONFIG` | Configuración base, usada cuando no hay `.agents-config.json` |
| `EXTENSION_TO_LANGUAGE` | Mapa estático extensión → clave de lenguaje |
| `ProjectConfig` | Clase que encapsula la configuración resuelta. Resuelve `project_size` → `SizeProfile` en `__init__` y lo expone como `config.profile` |
| `ProjectConfig.language_for_extension(ext)` | Devuelve el lenguaje para una extensión, respetando el filtro de lenguajes |
| `ProjectConfig.is_extension_supported(ext)` | Booleano, wrapper de `language_for_extension` |
| `load_config(project_path)` | Lee y mergea la config del proyecto, siempre devuelve un `ProjectConfig` válido |
