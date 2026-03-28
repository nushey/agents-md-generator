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

## Casos especiales

### Directorios de DTOs (Minificados)

Si todos los archivos de un directorio fueron minificados como `dto_container` por `symbol_utils._is_low_entropy`, el agregador genera un resumen semántico:
```json
{
  "directory": "Contracts/Requests/",
  "kind": "directory_summary",
  "file_count": 25,
  "language": "c_sharp",
  "note": "Contains 25 DTO/Entity classes with no logic methods",
  "sample_files": [...]
}
```
Esto permite colapsar capas enteras de datos en una sola línea de señal.

## Funciones

| Función | Qué hace |
|---|---|
| `_aggregate_by_directory(entries, threshold)` | Entry point. Recibe la lista de `full_analysis` entries y retorna la lista con los directorios elegibles colapsados en `directory_summary` |
| `_extract_common_methods(entries)` | Retorna nombres de métodos/funciones que aparecen en ≥ 60% de los archivos dados |
| `_extract_class_pattern(entries)` | Detecta sufijo o prefijo común en nombres de clases. Retorna el match más largo o `None` |
