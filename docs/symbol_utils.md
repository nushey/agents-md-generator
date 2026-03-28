# symbol_utils.py

## Rol

Concentra todas las utilidades de filtrado, formateo y clasificación de símbolos. También aloja el threshold de impacto y la detección de archivos de test — ambas son operaciones sobre símbolos o paths relacionados con ellos.

## Conceptos clave

### Visibilidad pública (`_is_public`)

Un símbolo es público si:
- Su `visibility` no es `"private"` ni `"protected"`
- Su nombre no empieza con `_`

Esta regla aplica a todos los lenguajes. Para Python, los métodos `_privados` se excluyen por convención de nombre. Para C# y TypeScript, se excluyen por `visibility`.

Solo los símbolos públicos llegan al payload — los privados no son relevantes para AGENTS.md.

### Detección de archivos de test (`_is_test_file`)

Un archivo es de test si su nombre o path cumplen alguna de estas condiciones:
- Nombre empieza con `test_` (Python)
- Nombre termina con `_test.py`, `_test.go` (Go/Python), `.spec.ts`, `.spec.js`, `.test.ts`, `.test.js`
- Path contiene `/tests/`, `/test/`, `/__tests__/`, `/spec/`, `/specs/`

Los archivos de test se procesan por separado y se colapsan en `test_directory_summary` — nunca aparecen como entradas individuales en `full_analysis`.

### Detección de archivos generados (`_is_generated`)

Antes del formateo, se verifica si el archivo es auto-generado. Se excluyen del payload porque tienen cero valor arquitectónico. La detección usa tres criterios:

- **Path**: contiene `Connected Services/`, `Service References/`, `/Generated/`, `/obj/`, `/auto_generated/`, `/auto-generated/`
- **Sufijo**: termina en `.Designer.cs`, `.g.cs`, `.g.i.cs`, `Reference.cs`, `.generated.cs`
- **Decoradores**: los primeros 3 símbolos tienen `GeneratedCodeAttribute` o `System.CodeDom.Compiler` en sus decoradores

### Detección de archivos minificados (`_is_minified`)

Verifica si el archivo es minificado o bundleado. La heurística: si más del 30% de los símbolos públicos de top-level tienen un nombre de 1-2 caracteres, el archivo se trata como minificado y se excluye del payload.

Solo aplica a JS/TS — en C# o Python los nombres cortos son convenciones válidas. Requiere al menos 5 símbolos para evitar falsos positivos en archivos pequeños.

### Filtrado de decoradores de ruido (`_filter_decorators`)

Elimina decoradores que no aportan señal arquitectónica. Se filtran por prefijo:

- `System.Runtime.Serialization.*`
- `System.CodeDom.Compiler.*`
- `System.SerializableAttribute`
- `System.Diagnostics.DebuggerStepThroughAttribute`, `DebuggerNonUserCode`
- `KnownTypeAttribute`, `DataContractAttribute`, `DataMemberAttribute`
- `System.ComponentModel.EditorBrowsable`

### Detección de archivos de baja entropía (`_is_low_entropy`)

Identifica archivos que contienen exclusivamente estructuras de datos (DTOs, Entidades) sin lógica. La heurística:
- El archivo tiene al menos 3 clases/structs públicos.
- El 100% de las clases/structs tienen cero métodos públicos.

Si un archivo cumple esto, se devuelve un resumen minificado en `full_analysis` en lugar de listar cada símbolo individualmente.

### Formateo para el payload

**`_slim_symbol`**: reduce un símbolo a los campos que el modelo necesita para AGENTS.md.

**`_format_full`**: formatea un archivo completo para `full_analysis`. Retorna `None` si:
- El archivo es minificado (`_is_minified`)
- El archivo es auto-generado (`_is_generated`)
- El archivo es de baja entropía (`_is_low_entropy`) — se genera resumen minificado
- **El archivo es trivial**: todos los símbolos tienen 0 métodos, 0 `constructor_deps`, 0 `implements` (o solo `object`), y 0 decoradores. Estos archivos no aportan señal arquitectónica.

Los decoradores se filtran con `_filter_decorators` antes de incluirlos en el output.

**Nota**: el campo `language` se incluye en cada entrada individual durante el procesamiento (el aggregator lo necesita para agrupar), pero se elimina en un paso posterior en `context_builder.py` antes de serializar — ya está en `metadata.languages_detected`.

**Resumen Minificado (DTOs)**: si un archivo es detectado como `low_entropy`, se genera una entrada especial:
```json
{
  "file": "path/to/dto.cs",
  "language": "c_sharp",
  "kind": "dto_container",
  "is_dto": true,
  "symbols_count": 5
}
```
Esto reduce drásticamente el tamaño del payload en capas de datos/contratos.

### Resumen de tests (`_summarize_test_files`)

Agrupa los archivos de test por directorio y por cada directorio produce:
```json
{
  "directory": "tests/",
  "kind": "test_directory_summary",
  "file_count": 12,
  "test_function_count": 87,
  "languages": ["python"],
  "files": ["tests/test_cache.py", ...]
}
```

En vez de listar 200 funciones de test, el modelo recibe cuántos tests hay y dónde. Suficiente para la sección de Testing Instructions sin inflar el payload.

### Threshold de impacto (`_passes_threshold`)

```python
_THRESHOLD_ORDER = {"high": 0, "medium": 1, "low": 2}

def _passes_threshold(impact, threshold):
    return _THRESHOLD_ORDER[impact] <= _THRESHOLD_ORDER[threshold]
```

Un cambio "pasa" el threshold si su impacto es igual o mayor al configurado. Ejemplos:
- threshold=`"medium"`: pasan `"high"` y `"medium"`, se filtra `"low"`
- threshold=`"high"`: solo pasa `"high"`
- threshold=`"low"`: pasa todo

## Funciones

| Función | Qué hace |
|---|---|
| `_is_public(sym)` | Retorna `True` si el símbolo es visible públicamente |
| `_is_test_file(path)` | Retorna `True` si el path corresponde a un archivo de test |
| `_is_generated(path, analysis)` | Retorna `True` si el archivo es auto-generado (por path, sufijo, o decoradores) |
| `_is_minified(analysis)` | Retorna `True` si el archivo JS/TS parece minificado o bundleado |
| `_filter_decorators(decorators)` | Filtra decoradores de ruido (serialización, CodeDom, etc.) |
| `_slim_symbol(sym)` | Reduce un símbolo a los campos necesarios para el payload |
| `_format_full(path, status, analysis)` | Formatea un `FileAnalysis` para `full_analysis`, o `None` si no hay símbolos útiles, es generado, o es trivial |
| `_summarize_test_files(entries)` | Colapsa entradas de test en resúmenes por directorio |
| `_passes_threshold(impact, threshold)` | Verifica si un impacto supera el threshold configurado |
