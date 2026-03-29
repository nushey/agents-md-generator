# models.py

## Rol

Define todos los tipos de datos del sistema usando Pydantic. Es el "lenguaje común" entre todos los módulos — ningún módulo inventa sus propias estructuras, todos hablan en términos de estos modelos.

## Conceptos clave

### Pydantic y validación automática

Todos los modelos heredan de `BaseModel`. Pydantic valida automáticamente los tipos en tiempo de construcción — si alguien intenta crear un `FileChange` con un `status` inválido, falla inmediatamente con un error claro en vez de propagar datos corruptos.

`str_strip_whitespace=True` en `model_config` asegura que ningún string entre con espacios accidentales.

### Jerarquía de modelos

```
ScanCodebaseInput        ← entrada de scan_codebase
ReadPayloadChunkInput         ← entrada de read_payload_chunk
    │
    ▼
FileChange                   ← qué archivos cambiaron y cómo
    │
    ▼
FileAnalysis                 ← qué tiene adentro cada archivo (AST)
    │  └─ SymbolInfo[]       ← clases, funciones, métodos detectados
    │
    ▼
AnalysisDiff                 ← diff semántico entre dos versiones de un archivo
    │  └─ SymbolInfo[]       ← qué symbols se agregaron, borraron, modificaron
    │
    ▼
CacheData                    ← estado persistido en disco
    └─ CachedFile{}          ← hash + symbols por archivo
         └─ CachedSymbol[]   ← versión reducida de SymbolInfo para la cache
```

### SymbolInfo vs CachedSymbol

`SymbolInfo` tiene todos los campos incluyendo `parent`, `line_start`, `line_end` — útiles durante el análisis en vivo. `CachedSymbol` es una versión reducida que persiste solo lo necesario para el diff semántico (`name`, `kind`, `visibility`, `signature`, `decorators`). Guardar menos en cache = archivos más chicos, carga más rápida.

### CacheData

Tiene tres campos clave:
- `version` — para migración futura de formato
- `base_commit` — el SHA del commit de git cuando se hizo el último scan (usado para validar que la cache es coherente con el repo)
- `files` — mapa de `path → CachedFile`

### ScanCodebaseInput y ReadPayloadChunkInput

Los dos modelos que llegan del exterior (desde el cliente MCP). `ScanCodebaseInput` tiene `project_path` y `force_full_scan`. `ReadPayloadChunkInput` tiene `project_path` y `chunk_index`. Los docstrings de los campos están escritos en segunda persona dirigidos al modelo que los llama — son instrucciones para el cliente MCP, no para el desarrollador.

## Modelos

| Modelo | Propósito |
|---|---|
| `FileChange` | Un archivo que cambió: path, status (new/modified/deleted), hashes |
| `SymbolInfo` | Un símbolo de código extraído por AST: nombre, tipo, visibilidad, firma, decoradores |
| `FileAnalysis` | Resultado del análisis AST de un archivo: imports, symbols, exports |
| `AnalysisDiff` | Diff semántico: qué symbols se agregaron, borraron o modificaron |
| `CachedSymbol` | Versión reducida de SymbolInfo para persistir en cache |
| `CachedFile` | Entrada de cache para un archivo: hash + symbols cacheados |
| `CacheData` | Raíz del archivo de cache: versión, commit, mapa de archivos |
| `ScanCodebaseInput` | Input de scan_codebase: project_path y force_full_scan |
| `ReadPayloadChunkInput` | Input de read_payload_chunk: project_path y chunk_index |
