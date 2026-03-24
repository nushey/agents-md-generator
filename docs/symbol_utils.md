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

### Formateo para el payload

**`_slim_symbol`**: reduce un símbolo a los campos que el modelo necesita para AGENTS.md:
- `name`, `kind`, `visibility`, `signature`, `decorators`
- Omite `line_start`, `line_end`, `parent` — útiles para análisis interno pero ruido para el output

**`_format_full`**: formatea un archivo completo para `full_analysis`. Para clases, incluye la lista de métodos públicos directos. Para funciones/símbolos de top level, incluye solo los que no tienen `parent`. Esto evita duplicar métodos que ya aparecen bajo su clase.

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
| `_slim_symbol(sym)` | Reduce un símbolo a los campos necesarios para el payload |
| `_format_full(path, status, analysis)` | Formatea un `FileAnalysis` completo para `full_analysis` |
| `_summarize_test_files(entries)` | Colapsa entradas de test en resúmenes por directorio |
| `_passes_threshold(impact, threshold)` | Verifica si un impacto supera el threshold configurado |
