# server.py

## Rol

Es el punto de entrada de la aplicación. Define el servidor MCP y expone dos herramientas públicas: `generate_agents_md` y `get_payload_chunk`. Todo lo que hace el cliente MCP al invocar el servidor pasa por acá.

## Conceptos clave

### FastMCP

`FastMCP` es el framework que abstrae el protocolo MCP. Al instanciar `FastMCP("agents_md_mcp")` y decorar una función con `@mcp.tool(...)`, esa función queda registrada como una herramienta que cualquier cliente MCP compatible puede descubrir y llamar.

### Por qué los logs van a stderr

El transporte MCP sobre stdio usa stdout para la comunicación binaria del protocolo. Si algo escribe a stdout que no sea el protocolo, el cliente se rompe. Por eso se configura logging explícitamente sobre `sys.stderr`.

### El pipeline en `_run_pipeline`

El núcleo del servidor. Ejecuta 8 pasos en orden:

1. **Cargar config** — lee `.agents-config.json` o usa defaults
2. **Cargar cache** — si hay cache válida del run anterior, la usa para el escaneo incremental
3. **Detectar cambios** — compara el estado actual del proyecto contra la cache
4. **Análisis AST** — parsea con tree-sitter solo los archivos que cambiaron
5. **Construir payload** — ensambla el JSON estructurado con toda la info del proyecto
6. **Actualizar cache** — guarda el nuevo estado para el próximo run
7. **Escribir payload a disco** — nunca se envía inline por el wire de MCP
8. **Retornar respuesta pequeña** — un JSON de ~1k chars con instrucciones para el cliente

### Por qué el payload va a disco y no inline

El payload puede tener miles de líneas para proyectos grandes. Si se enviara inline como respuesta del tool, viaja todo por el contexto del cliente de una sola vez — costoso, y puede superar límites de tamaño de respuesta MCP. En cambio, se escribe en `~/.cache/agents-md-generator/<hash>/payload.json` y el cliente lo recupera en chunks via `get_payload_chunk`.

### Serialización adaptativa

El payload se serializa con `json.dumps(indent=2)` por defecto (JSON legible). Pero para payloads >300kb, se usa JSON compacto (`separators=(",",":")`) que elimina ~30% de whitespace. El modo se detecta automáticamente al escribir.

### `get_payload_chunk` — streaming puro MCP

Lee el payload en bloques según el formato:
- **JSON con indent** (multiline): bloques de 500 líneas (`CHUNK_LINES`)
- **JSON compacto** (single-line): bloques de ~50kb (`CHUNK_BYTES`)

La detección del modo es automática: si el payload tiene <5 líneas, se usa byte-based chunking.

El cliente llama al tool repetidamente con `chunk_index` empezando en 0 e incrementando hasta que `has_more` es `false`. El archivo se borra automáticamente al leer el último chunk. Este diseño es agnóstico al cliente — cualquier cliente MCP puede seguir el flujo sin necesitar acceso al filesystem.

### `_build_response`

Recibe el número de chunks pre-calculado y construye instrucciones paso a paso que el cliente debe seguir exactamente:

```
STEP 1 → Llamar get_payload_chunk repetidamente hasta has_more = false
STEP 2 → Concatenar todos los campos "data" y parsear como JSON
STEP 3 → Escribir AGENTS.md usando solo esos datos
STEP 4 → Informar al usuario
```

Estas instrucciones son imperativas a propósito — el campo `instructions` del response le dice al cliente "no hagas nada más, no leas código, no hagas preguntas". Esto previene que el modelo alucine o explore el proyecto por su cuenta.

### El caso `no_changes`

Si `detect_changes` devuelve lista vacía, el server retorna un JSON especial con `"status": "no_changes"` y un mensaje que le dice al cliente que pregunte al usuario si quiere mejorar el AGENTS.md existente de todas formas. Esto evita que el modelo llame al tool en loop con `force_full_scan=True` por su cuenta.

## Funciones

| Función | Qué hace |
|---|---|
| `generate_agents_md(params)` | Entry point del tool MCP. Valida el path y delega a `_run_pipeline` |
| `get_payload_chunk(params)` | Lee un chunk del payload (line-based o byte-based según formato). Borra el archivo al leer el último chunk |
| `_run_pipeline(project_path, force_full_scan)` | Ejecuta los 8 pasos del pipeline de análisis. Usa JSON compacto para payloads >300kb |
| `_compute_total_chunks(payload_text, compact)` | Calcula total de chunks: por líneas (`CHUNK_LINES=500`) para pretty JSON, por bytes (`CHUNK_BYTES=50kb`) para compacto |
| `_build_response(payload_path, num_chunks, agents_md_path, project_path)` | Construye la respuesta pequeña con instrucciones para el cliente |
| `main()` | Entry point del proceso — llama `mcp.run()` |
