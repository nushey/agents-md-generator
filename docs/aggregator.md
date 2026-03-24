# aggregator.py

## Rol

Colapsa directorios con muchos archivos similares en un único resumen estructurado (`directory_summary`), reduciendo el tamaño del payload en proyectos grandes sin perder información arquitectural relevante.

## El problema que resuelve

Un proyecto de 500k líneas puede tener 300+ archivos de producción. Si cada uno genera una entrada en `full_analysis`, el payload explota en tamaño y el modelo recibe ruido en vez de señal. Cuando un directorio tiene 20 repositorios que todos exponen `get`, `save`, `delete` y `findById`, lo que le importa al modelo es el patrón — no los 20 archivos individuales.

## Algoritmo de `_aggregate_by_directory`

Para cada directorio en `full_analysis`:

1. **Agrupar por lenguaje**: identifica el lenguaje dominante (el de mayor cantidad de archivos)
2. **Verificar threshold**: si los archivos del lenguaje dominante son menos que `dir_aggregation_threshold` → se mantienen individuales
3. **Extraer métodos comunes**: via `_extract_common_methods` — métodos que aparecen en ≥ 60% de los archivos
4. **Verificar cobertura**: `len(common_methods) / avg_symbols_per_file`. Si hay menos de 2 métodos comunes o la cobertura es < 40% → patrón demasiado débil, se mantienen individuales
5. **Construir summary**: con `common_methods`, `class_pattern` (si existe), `outliers` (archivos con comportamiento único) y `sample_files` (primero, medio y último)

Los archivos de lenguaje minoritario en el mismo directorio **siempre** se mantienen individuales — solo se agrega el dominante.

## `_extract_class_pattern`

Detecta un prefijo o sufijo común en los nombres de clases del directorio. Itera de mayor a menor longitud (11 → 3 chars) y retorna el primer match — el más largo posible. Esto garantiza que `*Service` aparezca en vez de `*ice`.

Ejemplos:
- `OrderService`, `UserService`, `PaymentService` → `*Service`
- `AbstractOrder`, `AbstractUser`, `AbstractPayment` → `Abstract*`
- `Foo`, `Bar`, `Baz` → `None` (sin patrón)

## Thresholds configurables

| Constante | Valor | Descripción |
|---|---|---|
| `_COMMON_METHOD_FREQUENCY` | 0.6 | Un método debe aparecer en ≥ 60% de los archivos para ser "común" |
| `_PATTERN_COVERAGE_THRESHOLD` | 0.4 | Los métodos comunes deben cubrir ≥ 40% de los símbolos promedio por archivo |
| `_AGGREGATION_SAMPLE_SIZE` | 3 | Número de archivos de muestra en el summary (primero, medio, último) |

El threshold de cantidad de archivos es configurable por proyecto via `dir_aggregation_threshold` en `.agents-config.json` (default: 8).

## Funciones

| Función | Qué hace |
|---|---|
| `_aggregate_by_directory(entries, threshold)` | Entry point. Recibe la lista de `full_analysis` entries y retorna la lista con los directorios elegibles colapsados en `directory_summary` |
| `_extract_common_methods(entries)` | Retorna nombres de métodos/funciones que aparecen en ≥ 60% de los archivos dados |
| `_extract_class_pattern(entries)` | Detecta sufijo o prefijo común en nombres de clases. Retorna el match más largo o `None` |
