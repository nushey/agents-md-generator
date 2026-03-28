# build_system.py

## Rol

Detecta las herramientas de build presentes en el proyecto y extrae los comandos ejecutables de cada una. Opera puramente sobre el filesystem — sin AST, sin cache.

## Conceptos clave

### Detección por archivos marcadores

`_BUILD_MARKERS` mapea cada sistema de build a los archivos que lo identifican:

| Sistema | Archivos marcadores |
|---|---|
| dotnet | `*.sln`, `**/*.csproj`, `global.json` |
| npm | `package.json` |
| go | `go.mod` |
| make | `Makefile`, `makefile`, `GNUmakefile` |
| python | `pyproject.toml`, `setup.py`, `Pipfile` |
| rust | `Cargo.toml` |
| maven | `pom.xml` |
| gradle | `build.gradle` |
| ruby | `Gemfile` |

Un solo match por sistema es suficiente para marcarlo como detectado.

### Extracción de scripts por sistema

Cada sistema tiene su propia lógica de extracción:

**npm**: lee `package.json["scripts"]` directamente. También detecta el package manager via el campo `packageManager` (ej. `"pnpm@9.0.0"` → detecta `pnpm`).

**Python/uv/poetry**: lee `pyproject.toml` y:
1. Detecta el runner por presencia de lock files (`uv.lock` → `uv run`, `poetry.lock` → `poetry run`)
2. Construye el comando de install (`uv sync`, `poetry install`)
3. Lee `[project.scripts]` para entry points CLI
4. Detecta el test runner en las dependencias (`pytest` → `uv run pytest`)

**Make**: parsea el Makefile línea a línea buscando targets (líneas no indentadas que terminan en `:`). Ignora targets que empiezan con `.` o contienen espacios.

**dotnet**: parsea cada `.csproj` encontrado con `xml.etree.ElementTree` (stdlib) y extrae:
- `target_framework` — valor de `<TargetFramework>` o `<TargetFrameworks>`
- `output_type` — valor de `<OutputType>` (`Exe`, `Library`, `WinExe`, etc.)
- `packages` — lista de `<PackageReference>` en formato `"Name@Version"`, capeada en 15
- `project_references` — lista de paths de `<ProjectReference>` (backslashes normalizados a forward slash)

El campo `dotnet_projects` se omite del output si no hay `.csproj` en el proyecto. La detección usa `**/*.csproj` para encontrar proyectos en subdirectorios.

**Deduplicación de paquetes comunes**: cuando hay más de un `.csproj`, se cuentan las ocurrencias de cada paquete. Los que aparecen en >50% de los proyectos se extraen a una lista `dotnet_common_packages` en el output, y se eliminan de la lista `packages` de cada proyecto individual. Esto evita repetir los mismos paquetes 58 veces en proyectos grandes.

### Extensibilidad (OCP implícito)

Para agregar soporte a un nuevo sistema de build, basta con:
1. Agregar una entrada a `_BUILD_MARKERS`
2. Agregar la lógica de extracción de scripts dentro de `_detect_build_systems`

No hay que modificar ningún otro módulo.

## Funciones

| Función | Qué hace |
|---|---|
| `_detect_build_systems(root)` | Detecta build tools presentes y extrae sus scripts y metadatos. Retorna `{"detected": [...], "package_files": [...], "scripts": {...}, "dotnet_projects": [...]}` (dotnet_projects solo si hay .csproj) |
