# Plan: agents-md-generator MCP Server

## Créditos

Formato AGENTS.md basado en la skill `create-agentsmd` de [github/awesome-copilot](https://skills.sh/github/awesome-copilot/create-agentsmd), que sigue el estándar abierto de [agents.md](https://agents.md/).

---

## Visión General

MCP Server en Python (FastMCP + stdio) que expone una sola tool: `generate_agents_md`. Esta tool analiza un codebase de forma incremental usando preprocesamiento local pesado (tree-sitter) y solo delega al LLM un payload mínimo y compacto para generar o actualizar el `AGENTS.md`.

**Diferencial:** El 90% del trabajo lo hace el preprocesamiento local. El LLM recibe un JSON estructurado y compacto, no archivos crudos.

---

## Arquitectura

```
Claude Code ──stdio──▶ agents_md_mcp (Python)
                            │
                    ┌───────┼───────┐
                    ▼       ▼       ▼
              ConfigLoader  ChangeDetector  ASTAnalyzer
                                    │           │
                                    ▼           ▼
                              .agents-cache.json
                                    │
                                    ▼
                              ContextBuilder
                                    │
                                    ▼
                          Payload JSON compacto
                                    │
                                    ▼
                        Return al LLM (Claude Code)
```

**Nota importante:** El MCP server NO llama a la API de Claude. El server hace todo el preprocesamiento y devuelve el payload estructurado a Claude Code. Claude Code (que ya ES Claude) recibe ese payload y genera/actualiza el AGENTS.md directamente.

---

## Estructura del Proyecto

```
agents-md-generator/
├── pyproject.toml              # Dependencias y metadata del paquete
├── README.md
├── LICENSE
├── src/
│   └── agents_md_mcp/
│       ├── __init__.py
│       ├── server.py           # FastMCP server + tool registration
│       ├── config.py           # ConfigLoader
│       ├── change_detector.py  # ChangeDetector (git + hash cache)
│       ├── ast_analyzer.py     # ASTAnalyzer (tree-sitter)
│       ├── context_builder.py  # ContextBuilder (arma el payload)
│       ├── cache.py            # Lectura/escritura de .agents-cache.json
│       ├── models.py           # Pydantic models (FileChange, Symbol, etc.)
│       └── languages/          # Queries tree-sitter por lenguaje
│           ├── __init__.py
│           ├── base.py         # Interfaz base LanguageAnalyzer
│           ├── python.py
│           ├── csharp.py
│           ├── typescript.py
│           └── go.py
└── tests/
    ├── test_change_detector.py
    ├── test_ast_analyzer.py
    ├── test_context_builder.py
    └── fixtures/               # Archivos de ejemplo para tests
```

---

## Componentes Detallados

### 1. `server.py` — MCP Server (FastMCP + stdio)

Expone **una sola tool**:

```python
@mcp.tool(
    name="generate_agents_md",
    annotations={
        "readOnlyHint": False,     # Escribe/modifica AGENTS.md
        "destructiveHint": False,
        "idempotentHint": True,    # Correrlo 2 veces sin cambios = mismo resultado
        "openWorldHint": False
    }
)
async def generate_agents_md(params: GenerateAgentsMdInput) -> str:
    """Analiza el codebase y genera/actualiza el AGENTS.md.

    Realiza análisis incremental del código fuente usando tree-sitter,
    detecta cambios desde la última ejecución, y devuelve un payload
    estructurado con la información necesaria para generar el AGENTS.md.
    """
```

**Input (Pydantic):**

```python
class GenerateAgentsMdInput(BaseModel):
    project_path: str = Field(
        default=".",
        description="Ruta al proyecto. Default: directorio actual."
    )
    force_full_scan: bool = Field(
        default=False,
        description="Forzar análisis completo ignorando cache."
    )
```

**Output:** JSON string con el payload estructurado que Claude Code interpreta para generar el AGENTS.md.

---

### 2. `config.py` — ConfigLoader

Lee `.agents-config.json` desde la raíz del proyecto. Si no existe, usa defaults.

```python
# Defaults
DEFAULT_CONFIG = {
    "exclude": [
        "**/node_modules/**",
        "**/bin/**",
        "**/obj/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/__pycache__/**",
        "**/*.min.js",
        "**/*.min.css",
        "**/vendor/**",
        "**/packages/**",          # NuGet
        "**/.venv/**",
        "**/venv/**"
    ],
    "include": [],                  # Si no vacío, SOLO estos patterns
    "languages": "auto",            # "auto" detecta por extensión
    "impact_threshold": "medium",   # "high", "medium", "low"
    "agents_md_path": "./AGENTS.md",
    "base_ref": null                # Rama base para diff, null = usa cache
}
```

**Detección automática de lenguajes** (mode `"auto"`):
Mapeo de extensiones → grammars tree-sitter:

| Extensión        | Language key   |
|------------------|----------------|
| .py              | python         |
| .cs              | c_sharp        |
| .ts, .tsx        | typescript     |
| .js, .jsx        | javascript     |
| .go              | go             |
| .java            | java           |
| .rs              | rust           |
| .rb              | ruby           |

---

### 3. `change_detector.py` — ChangeDetector

Dos modos de operación:

#### Modo A: Cold Start (no existe `.agents-cache.json`)

```
1. git ls-files  →  lista todos los archivos trackeados
2. Filtrar según config (exclude/include patterns)
3. Filtrar por extensiones soportadas
4. Marcar TODOS como status: "new"
5. Retornar lista de FileChange(path, status="new")
```

#### Modo B: Incremental (existe cache)

```
1. Validar que base_commit del cache existe en el repo
   - Si no existe → fallback a Cold Start
2. Para cada archivo en cache:
   - Calcular hash actual (SHA-256 del contenido)
   - Comparar con hash almacenado
   - Si difiere → status: "modified"
   - Si archivo no existe → status: "deleted"
3. Detectar archivos nuevos:
   - git ls-files filtrado - archivos en cache = nuevos
   - Marcar como status: "new"
4. Retornar lista de FileChange
```

**Modelo:**

```python
class FileChange(BaseModel):
    path: str
    status: Literal["new", "modified", "deleted"]
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
```

**¿Por qué hash y no solo git diff?**
- `git diff` requiere un commit de referencia que puede no existir
- Los hashes nos dan independencia de la estrategia de branching
- Funciona igual para archivos untracked (si el config los incluye)
- git diff como optimización adicional: si `base_ref` está configurado,
  usar `git diff --name-only base_ref` como fast-path antes de hashear

---

### 4. `ast_analyzer.py` — ASTAnalyzer (el corazón)

Usa `py-tree-sitter` para parsear cada archivo y extraer un modelo semántico.

**Dependencias:**

```
tree-sitter>=0.24.0
tree-sitter-python
tree-sitter-c-sharp
tree-sitter-typescript
tree-sitter-javascript
tree-sitter-go
tree-sitter-java
tree-sitter-rust
tree-sitter-ruby
```

**Extracción por archivo:**

```python
class SymbolInfo(BaseModel):
    name: str
    kind: Literal["class", "method", "function", "interface",
                   "enum", "struct", "property", "field"]
    visibility: Optional[str] = None   # public, private, internal, protected
    signature: Optional[str] = None    # firma completa
    decorators: list[str] = []         # atributos/decoradores
    parent: Optional[str] = None       # clase contenedora si es método
    line_start: int = 0
    line_end: int = 0

class FileAnalysis(BaseModel):
    path: str
    language: str
    imports: list[str] = []
    symbols: list[SymbolInfo] = []
    exports: list[str] = []           # para JS/TS
```

**Queries tree-sitter por lenguaje:**
Cada archivo en `languages/` define las queries SCM (S-expression) para extraer nodos relevantes de ese lenguaje. Ejemplo para Python:

```scheme
;; Funciones top-level
(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  return_type: (type)? @function.return_type) @function.def

;; Clases
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list)? @class.bases) @class.def

;; Métodos dentro de clases
(class_definition
  body: (block
    (function_definition
      name: (identifier) @method.name
      parameters: (parameters) @method.params) @method.def))

;; Imports
(import_statement) @import
(import_from_statement) @import
```

**Análisis diferencial (archivos "modified"):**
Cuando un archivo tiene status "modified":

```python
def diff_analysis(old: FileAnalysis, new: FileAnalysis) -> AnalysisDiff:
    """Compara dos FileAnalysis y retorna solo lo que cambió."""

    old_symbols = {s.name: s for s in old.symbols}
    new_symbols = {s.name: s for s in new.symbols}

    added = [s for name, s in new_symbols.items() if name not in old_symbols]
    removed = [s for name, s in old_symbols.items() if name not in new_symbols]
    modified = [
        new_symbols[name] for name in old_symbols
        if name in new_symbols
        and old_symbols[name].signature != new_symbols[name].signature
    ]

    return AnalysisDiff(added=added, removed=removed, modified=modified)
```

**Clasificación de impacto:**

```python
def classify_impact(change: SymbolInfo, change_type: str) -> str:
    """Clasifica el impacto de un cambio en high/medium/low."""

    # HIGH: Cambios que afectan la estructura pública del proyecto
    if change_type in ("added", "removed") and change.kind in ("class", "interface", "struct"):
        return "high"
    if change.kind == "method" and change.visibility == "public" and change_type == "removed":
        return "high"
    if any(d in str(change.decorators) for d in ["HttpGet", "HttpPost", "app.route", "api_view"]):
        return "high"  # Endpoints

    # MEDIUM: Cambios en firmas públicas
    if change.visibility == "public" and change_type == "modified":
        return "medium"
    if change.kind == "function" and change_type == "added":
        return "medium"

    # LOW: Cambios internos
    return "low"
```

---

### 5. `context_builder.py` — ContextBuilder

Toma los resultados del análisis y construye el payload para Claude Code.

**Estructura del payload (lo que retorna la tool):**

```json
{
  "metadata": {
    "project_name": "MyApp",
    "scan_type": "incremental",
    "files_analyzed": 12,
    "files_total": 156,
    "languages_detected": ["c_sharp", "typescript"],
    "timestamp": "2026-03-20T14:30:00Z"
  },

  "project_structure": {
    "root_files": ["Program.cs", "package.json", "Dockerfile"],
    "directories": {
      "src/Domain/": { "file_count": 8, "primary_language": "c_sharp" },
      "src/Services/": { "file_count": 12, "primary_language": "c_sharp" },
      "src/Web/Controllers/": { "file_count": 5, "primary_language": "c_sharp" },
      "frontend/src/": { "file_count": 20, "primary_language": "typescript" }
    },
    "config_files_found": [
      ".editorconfig", ".eslintrc.json", "tsconfig.json",
      "Directory.Build.props", "Makefile"
    ],
    "ci_files_found": [".github/workflows/ci.yml"],
    "test_directories": ["tests/", "src/*.Tests/"]
  },

  "build_system": {
    "detected": ["dotnet", "npm"],
    "package_files": ["MyApp.sln", "package.json"],
    "scripts": {
      "npm": { "build": "vite build", "test": "vitest", "dev": "vite" }
    }
  },

  "changes": [
    {
      "file": "src/Services/OrderService.cs",
      "status": "modified",
      "language": "c_sharp",
      "impact": "high",
      "diff": {
        "added_symbols": [
          {
            "kind": "method",
            "name": "CancelOrder",
            "parent": "OrderService",
            "visibility": "public",
            "signature": "public async Task<bool> CancelOrder(int orderId)",
            "decorators": ["HttpPost"]
          }
        ],
        "removed_symbols": [],
        "modified_symbols": []
      }
    }
  ],

  "full_analysis": [
    {
      "file": "src/Domain/Order.cs",
      "status": "new",
      "language": "c_sharp",
      "symbols": [
        {
          "kind": "class",
          "name": "Order",
          "visibility": "public",
          "signature": "public class Order",
          "methods": ["GetTotal", "Cancel", "Ship"]
        }
      ],
      "imports": ["System", "System.Collections.Generic"]
    }
  ],

  "existing_agents_md": "... contenido actual si existe ...",

  "instructions": "Basándote en este análisis, genera (o actualiza) el AGENTS.md siguiendo el estándar agents.md. El archivo debe incluir: Project Overview, Setup Commands, Development Workflow, Testing Instructions, Code Style, Build and Deployment, y cualquier sección adicional que el análisis justifique. Si ya existe un AGENTS.md, preserva la estructura existente y solo actualiza las secciones afectadas por los cambios detectados. Priorizá comandos exactos y accionables."
}
```

**Lógica del ContextBuilder:**

```
1. Leer project_structure escaneando directorios (sin tree-sitter, solo fs)
2. Detectar build_system buscando archivos conocidos:
   - *.sln, *.csproj → dotnet
   - package.json → npm/yarn/pnpm (leer packageManager field)
   - go.mod → go
   - Makefile → make
   - pyproject.toml / setup.py → python
   - Cargo.toml → rust
3. Parsear scripts de package.json, Makefile targets, etc.
4. Buscar CI/CD configs (.github/workflows/, .gitlab-ci.yml, Jenkinsfile)
5. Buscar config files relevantes (.editorconfig, linters, formatters)
6. Buscar test patterns (directorios *test*, *spec*, frameworks)
7. Combinar con resultados del ASTAnalyzer
8. Si existe AGENTS.md actual, incluir su contenido
9. Aplicar filtro de impacto según config.impact_threshold
10. Armar JSON final
```

---

### 6. `cache.py` — Cache Manager

```python
CACHE_FILE = ".agents-cache.json"

class CacheData(BaseModel):
    version: str = "1.0"
    last_run: str                    # ISO timestamp
    base_commit: Optional[str]       # SHA del commit al momento del scan
    files: dict[str, CachedFile]     # path → CachedFile

class CachedFile(BaseModel):
    hash: str                        # SHA-256 del contenido
    analysis: FileAnalysis           # Resultado del tree-sitter parse
```

**Operaciones:**

- `load_cache(project_path) → CacheData | None`
- `save_cache(project_path, data: CacheData)`
- `is_cache_valid(cache: CacheData, project_path) → bool` — verifica que base_commit existe

---

## Pipeline Completo (flujo de ejecución)

```
generate_agents_md(project_path=".", force_full_scan=False)
│
├─ 1. config = ConfigLoader.load(project_path)
│     → Lee .agents-config.json o usa defaults
│
├─ 2. cache = CacheManager.load(project_path)
│     → None si no existe o si force_full_scan=True
│
├─ 3. changes = ChangeDetector.detect(project_path, config, cache)
│     │
│     ├─ Si cache is None → COLD START
│     │   → git ls-files → filtrar → todo es "new"
│     │
│     └─ Si cache exists → INCREMENTAL
│         → hash compare → lista de FileChange
│
├─ 4. Si changes está vacía → retornar "No changes detected"
│
├─ 5. analysis = ASTAnalyzer.analyze(changes, config, cache)
│     │
│     ├─ Para cada "new" → full parse con tree-sitter
│     ├─ Para cada "modified" → parse + diff contra cache
│     └─ Para cada "deleted" → marcar símbolos removidos
│
├─ 6. payload = ContextBuilder.build(project_path, config, analysis, cache)
│     → Estructura el JSON compacto descrito arriba
│
├─ 7. CacheManager.save(project_path, updated_cache)
│     → Guarda hashes + análisis para próxima ejecución
│
└─ 8. return payload (JSON string)
        → Claude Code recibe esto y genera el AGENTS.md
```

---

## Configuración en Claude Code

El usuario agrega al `claude_desktop_config.json` o `.claude.json`:

```json
{
  "mcpServers": {
    "agents-md-generator": {
      "command": "uvx",
      "args": ["agents-md-generator"],
      "env": {}
    }
  }
}
```

Alternativa con pip install local:

```json
{
  "mcpServers": {
    "agents-md-generator": {
      "command": "python",
      "args": ["-m", "agents_md_mcp.server"],
      "env": {}
    }
  }
}
```

---

## Dependencias (pyproject.toml)

```toml
[project]
name = "agents-md-generator"
version = "0.1.0"
description = "MCP server that analyzes codebases and generates AGENTS.md files"
requires-python = ">=3.11"

dependencies = [
    "mcp>=1.0.0",
    "pydantic>=2.0.0",
    "tree-sitter>=0.24.0",
    "tree-sitter-python>=0.23.0",
    "tree-sitter-c-sharp>=0.23.0",
    "tree-sitter-typescript>=0.23.0",
    "tree-sitter-javascript>=0.23.0",
    "tree-sitter-go>=0.23.0",
    "tree-sitter-java>=0.23.0",
    "tree-sitter-rust>=0.23.0",
    "tree-sitter-ruby>=0.23.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[project.scripts]
agents-md-generator = "agents_md_mcp.server:main"
```

---

## Orden de Implementación (para Claude Code)

### Fase 1: Scaffolding y Config
1. Crear estructura de directorios
2. `pyproject.toml` con dependencias
3. `models.py` — todos los Pydantic models
4. `config.py` — ConfigLoader con defaults
5. `cache.py` — lectura/escritura del cache
6. Tests básicos para config y cache

### Fase 2: Change Detection
7. `change_detector.py` — Cold Start (git ls-files + filtrado)
8. `change_detector.py` — Incremental (hash compare)
9. `change_detector.py` — Validación de cache (base_commit check)
10. Tests con fixtures (repos git de ejemplo)

### Fase 3: AST Analysis (el core)
11. `languages/base.py` — interfaz LanguageAnalyzer
12. `languages/python.py` — primer lenguaje (más fácil de testear)
13. `ast_analyzer.py` — orquestador que delega al analyzer correcto
14. Tests con archivos Python de fixture
15. `languages/csharp.py` + tests
16. `languages/typescript.py` + tests
17. Demás lenguajes según prioridad
18. Diff semántico + clasificación de impacto

### Fase 4: Context Building
19. `context_builder.py` — detección de build system
20. `context_builder.py` — escaneo de estructura
21. `context_builder.py` — armado del payload JSON
22. Tests end-to-end con proyecto fixture completo

### Fase 5: MCP Server
23. `server.py` — FastMCP + tool registration
24. Integración del pipeline completo
25. Test manual con Claude Code
26. Manejo de errores y edge cases

### Fase 6: Polish
27. README.md con instrucciones de instalación
28. Ejemplo de `.agents-config.json`
29. Logging (stderr, nunca stdout por stdio transport)
30. Optimización de performance para repos grandes

---

## Edge Cases a Manejar

| Caso | Solución |
|------|----------|
| Repo sin git | Fallback a full scan basado en fs walk, sin commit tracking |
| Archivo binario en el scan | Filtrar por extensión ANTES de hashear/parsear |
| Archivo muy grande (>1MB) | Configurar límite en config, loggear warning, skip o sample |
| tree-sitter grammar no instalada | Loggear warning, skip ese archivo, reportar en payload |
| AGENTS.md corrupto o no-parseable | Tratarlo como si no existiera, generar de cero |
| Cache corrupto | Fallback a cold start, re-generar cache |
| Permisos insuficientes en archivos | Catch exception, loggear, continuar con los demás |
| Monorepo con múltiples AGENTS.md | v1: solo raíz. Futuro: soportar subproyectos |
| Sin cambios detectados | Retornar mensaje claro, no regenerar innecesariamente |
| Repo enorme (>10k archivos) | Respetar excludes agresivamente, reportar progreso |
