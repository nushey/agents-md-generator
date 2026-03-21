# ast_analyzer.py

## Rol

Orquesta el análisis de AST. No implementa ningún parser directamente — delega a los analyzers específicos de cada lenguaje. Su responsabilidad es: dado un archivo y su lenguaje, encontrar el analyzer correcto, ejecutarlo, y devolver los símbolos. También implementa el diff semántico entre dos versiones de un archivo y la clasificación de impacto de cada cambio.

## Conceptos clave

### Lazy loading de analyzers

Los analyzers se instancian una sola vez y se cachean en el dict `_ANALYZERS`. La primera vez que se necesita analizar un archivo Python, se instancia `PythonAnalyzer()` y se guarda. Las siguientes llamadas reutilizan esa instancia. Esto evita que tree-sitter cargue las grammars repetidamente — que es costoso.

Si un analyzer falla al cargar (por ejemplo, falta una dependency de tree-sitter), se loguea un warning y se retorna `None`. El archivo se skipea en vez de tirar toda la ejecución.

### Separación de responsabilidades

`ast_analyzer.py` NO sabe cómo parsear Python, TypeScript ni C#. Solo sabe:
1. A qué lenguaje corresponde una clave (`"python"` → `PythonAnalyzer`)
2. Cómo invocar el método `analyze()` del analyzer
3. Cómo hacer diff semántico entre dos listas de símbolos
4. Cómo clasificar el impacto de cada cambio

Esta separación permite agregar un nuevo lenguaje sin tocar nada de la lógica de orquestación.

### diff_analysis — diff semántico, no textual

En vez de hacer un diff línea por línea (como `git diff`), compara listas de símbolos por nombre:
- **added**: symbols en la versión nueva que no estaban en la vieja
- **removed**: symbols de la versión vieja que no están en la nueva
- **modified**: symbols que existen en ambas versiones pero cuya `signature` cambió

Esto significa que si se agrega un parámetro a una función pública, ese cambio se detecta y clasifica — aunque el diff textual muestre muchas líneas.

### classify_impact — la lógica de priorización

Clasifica cada cambio en `"high"`, `"medium"` o `"low"`:

| Condición | Impacto |
|---|---|
| El símbolo tiene un decorator de HTTP endpoint (`@app.route`, `@HttpGet`, `@Get`, etc.) | high |
| Se agrega o elimina una clase, interface o struct | high |
| Se elimina un método público | high |
| Se modifica la firma de un método público | medium |
| Se agrega una función o método público nuevo | medium |
| Cualquier otro cambio público | low |

El `impact_threshold` de la config filtra qué cambios llegan al payload — si es `"high"`, solo los cambios de impacto alto se incluyen. Esto evita regenerar AGENTS.md por cambios menores.

### _HIGH_IMPACT_DECORATORS

Set de nombres de decoradores que indican un HTTP endpoint en cualquier framework soportado:
- .NET: `HttpGet`, `HttpPost`, `Route`, `ApiController`
- Python: `app.route`, `router.get`, `api_view`
- NestJS/Angular: `Controller`, `Get`, `Post`, `Injectable`, `Component`

Si un símbolo tiene cualquiera de estos decoradores, el cambio es automáticamente `"high"` — un endpoint que cambia de firma es una breaking change de API.

## Funciones

| Función | Qué hace |
|---|---|
| `analyze_changes(project_path, changes, config, cache)` | Entry point: analiza los archivos cambiados y devuelve `{path: FileAnalysis}` |
| `build_analyzer(language_key)` | Instancia el analyzer para el lenguaje dado |
| `_get_analyzer(language_key)` | Devuelve el analyzer cacheado o lo instancia |
| `diff_analysis(old_symbols, new_symbols)` | Diff semántico entre dos listas de símbolos |
| `classify_impact(symbol, change_type)` | Clasifica el impacto de un cambio de símbolo |
