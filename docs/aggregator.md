# aggregator.py

## Rol

Colapsa directorios con muchos archivos similares en un único resumen estructurado (`directory_summary`), reduciendo el tamaño del payload en proyectos grandes sin perder información arquitectural relevante.

## El problema que resuelve

Un proyecto de 500k líneas puede tener 300+ archivos de producción. Si cada uno genera una entrada en `full_analysis`, el payload explota en tamaño y el modelo recibe ruido en vez de señal. Cuando un directorio tiene 20 repositorios que todos exponen `get`, `save`, `delete` y `findById`, lo que le importa al modelo es el patrón — no los 20 archivos individuales.

## Algoritmo de `_aggregate_by_directory`

Para cada directorio en `full_analysis`:

1. **Agrupar por lenguaje**: identifica el lenguaje dominante (el de mayor cantidad de archivos)
2. **Verificar threshold**: si los archivos del lenguaje dominante son menos que `profile.dir_aggregation_threshold` → se mantienen individuales (capeados a `profile.max_files_per_layer` si exceden ese límite)
3. **Caso especial — DTO containers**: si todos los archivos dominantes fueron minificados como `dto_container` por `_is_low_entropy` → se genera un resumen semántico directamente
4. **Extraer métodos comunes**: via `_extract_common_methods` — firmas de métodos (de las listas `methods` dentro de cada símbolo) que aparecen en ≥ 60% de los archivos
5. **Verificar cobertura**: `len(common_methods) / avg_methods_per_file`. Si hay menos de 2 métodos comunes o la cobertura es < 40%:
   - **¿Es un directorio de DTOs?** (≥ 80% de archivos son clases sin métodos) → se genera un resumen DTO con `naming_pattern` si existe
   - **Si no es DTO** → se genera un **fallback genérico** (`"No common method pattern detected"`) con `sample_files` y `naming_pattern` si existe. Esto evita que directorios grandes sin patrón detectable inflen el payload con cientos de entradas individuales.
6. **Construir summary con patrón**: con `common_methods`, `class_pattern` (si existe), `outliers` (archivos con métodos únicos fuera del patrón común) y `sample_files` (primero, medio y último)

Los archivos de lenguaje minoritario en el mismo directorio **siempre** se mantienen individuales — solo se agrega el dominante.

### Flujo de decisión resumido

```
Dir con N archivos del lenguaje dominante
  │
  ├─ N < threshold → individuales (capeados a profile.max_files_per_layer)
  │
  ├─ Todos dto_container → summary DTO especial
  │
  ├─ Tiene ≥2 métodos comunes con cobertura ≥40% → summary con common_methods + outliers
  │
  ├─ Es directorio DTO (≥80% clases sin métodos) → summary DTO
  │
  └─ Fallback genérico → summary sin common_methods (sample_files + naming_pattern)
```

En ningún caso un directorio que supera el threshold produce entradas individuales sin acotar — siempre se colapsa en algún tipo de `directory_summary`.

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

### Fallback genérico (sin patrón detectado)

Si un directorio supera el threshold pero no tiene métodos comunes suficientes y no es un directorio DTO, se genera un summary genérico:
```json
{
  "directory": "MyApp.Services/",
  "kind": "directory_summary",
  "file_count": 42,
  "language": "c_sharp",
  "note": "No common method pattern detected",
  "sample_files": ["MyApp.Services/OrderService.cs", "MyApp.Services/InvoiceService.cs", "MyApp.Services/PaymentService.cs"],
  "naming_pattern": { "pattern": "*Service", "examples": ["OrderService", "InvoiceService", "PaymentService"], "total": 42 }
}
```
Esto garantiza que directorios grandes siempre se colapsen, incluso cuando sus archivos no comparten un patrón de métodos. Sin este fallback, un directorio con 42 archivos únicos produciría 42 entradas individuales en el payload.

## Funciones

| Función | Qué hace |
|---|---|
| `_aggregate_by_directory(entries, threshold, profile)` | Entry point. Recibe la lista de `full_analysis` entries y el `SizeProfile`, y retorna la lista con los directorios elegibles colapsados en `directory_summary` |
| `_extract_common_methods(entries)` | Retorna firmas de métodos (extraídas de las listas `methods` de cada símbolo) que aparecen en ≥ 60% de los archivos dados |
| `_extract_class_pattern(entries)` | Detecta sufijo o prefijo común en nombres de clases. Retorna el match más largo o `None` |
