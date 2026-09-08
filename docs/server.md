# server.py

## Rol

Es el punto de entrada de la aplicación. Define el servidor MCP y expone tres herramientas públicas: `generate_agents_md`, `scan_codebase`, y `read_payload_chunk`. También expone dos prompts MCP: `initialize-agents-md` y `update-agents-md`.

## Conceptos clave

### FastMCP

`FastMCP` es el framework que abstrae el protocolo MCP. Al instanciar `FastMCP("agents_md_mcp")` y decorar una función con `@mcp.tool(...)`, esa función queda registrada como una herramienta que cualquier cliente MCP compatible puede descubrir y llamar. Los prompts se registran con `@mcp.prompt(...)`.

### Por qué los logs van a stderr

El transporte MCP sobre stdio usa stdout para la comunicación binaria del protocolo. Si algo escribe a stdout que no sea el protocolo, el cliente se rompe. Por eso se configura logging explícitamente sobre `sys.stderr`. El nivel de log se controla con la variable de entorno `AGENTS_MD_LOG_LEVEL` (default: `INFO`).

### Separación de responsabilidades entre tools

Los tres tools tienen responsabilidades distintas y no se solapan:

- **`generate_agents_md`**: entry point para generar o actualizar AGENTS.md. Llama `_run_pipeline` internamente con `include_agents_md_context=True` — el payload incluye las reglas de escritura y el contenido existente de AGENTS.md. El agente nunca necesita llamar `scan_codebase` para este flujo.
- **`scan_codebase`**: tool de contexto puro. El agente lo llama cuando necesita entender el codebase para cualquier otra tarea (code review, planning, Q&A). El payload resultante no tiene mandato de AGENTS.md.
- **`read_payload_chunk`**: streaming agnóstico. Lee el payload escrito por cualquiera de los dos tools anteriores.

### El pipeline en `_run_pipeline`

`_run_pipeline` ejecuta `_run_pipeline_sync` en un proceso separado, informa progreso por etapa y termina el worker ante cancelación o al superar cinco minutos. Rechaza otro scan simultáneo del mismo proyecto dentro de la misma instancia del servidor. El pipeline ejecuta estos pasos:

1. **Cargar config** — lee `.agents-config.json` o usa defaults
2. **Cargar cache** — si `force_full_scan=False` y hay cache válida, la usa para el escaneo incremental
3. **Detectar cambios** — compara el estado actual del proyecto contra la cache
4. **Análisis AST** — parsea con tree-sitter solo los archivos que cambiaron
5. **Construir payload** — para generación combina símbolos nuevos y cacheados en un snapshot actual e inyecta `instructions` y `existing_agents_md`
6. **Preparar cache y limitar payload** — prepara el nuevo estado y aplica el presupuesto de tamaño
7. **Persistir payload y cache** — escribe primero el payload y después la cache, cada uno mediante reemplazo atómico
8. **Retornar dict de respuesta** — contiene `status`, `total_chunks`, e instrucciones para el cliente

### Por qué el payload va a disco y no inline

El payload puede tener miles de líneas para proyectos grandes. Si se enviara inline como respuesta del tool, viaja todo por el contexto del cliente de una sola vez — costoso, y puede superar límites de tamaño de respuesta MCP. En cambio, se escribe en `~/.cache/agents-md-generator/<hash>/payload.json` y el cliente lo recupera en chunks via `read_payload_chunk`.

### Serialización adaptativa

El payload siempre usa JSON compacto y tiene un máximo de 300.000 caracteres, incluyendo metadata. Si supera el límite, se aplica el perfil `large`, se quitan firmas de métodos y se reducen las secciones de análisis más grandes. Los recortes quedan registrados en `metadata.degradations` y `metadata.truncated_sections`. No se recortan las instrucciones ni el AGENTS.md existente: si no caben, se retorna un error.

### `read_payload_chunk` — streaming puro MCP

Lee el payload en bloques de 20.000 caracteres (`CHUNK_CHARS`), sin dividir caracteres Unicode.

El cliente llama al tool repetidamente con `chunk_index` empezando en 0 e incrementando hasta que `has_more` es `false`. El archivo se borra automáticamente al leer el último chunk.

### `_build_response`

Construye una respuesta neutra con `status`, `total_chunks`, e instrucciones para llamar `read_payload_chunk`. No incluye mandato de escribir AGENTS.md — ese mandato vive en el payload mismo cuando se llama desde `generate_agents_md`.

### El caso `no_changes`

Solo `scan_codebase` retorna `"status": "no_changes"` cuando no hay cambios. `generate_agents_md` siempre reconstruye el snapshot con símbolos cacheados, porque completar el análisis no implica que el cliente haya escrito AGENTS.md. Los reintentos recuperan tanto creaciones como actualizaciones interrumpidas, sin volver a parsear fuentes sin cambios. Los errores de Git se propagan; nunca se interpretan como ausencia de cambios.

### MCP Prompts

Los prompts son templates user-facing, no herramientas para el agente. Los clientes que soporten prompts MCP los exponen como atajos de UI (slash commands, prompt picker). Ambos prompts aceptan `project_path` como argumento opcional y delegan directamente a `generate_agents_md`.

## Funciones

| Función | Qué hace |
|---|---|
| `generate_agents_md(params, ctx)` | Entry point para AGENTS.md. Llama `_run_pipeline` internamente con `include_agents_md_context=True` y `force_full_scan=False`. Llama `setup_connectors`. Retorna instrucciones para leer chunks |
| `scan_codebase(params, ctx)` | Tool de contexto puro. Usa `force_full_scan=False` por default. Retorna JSON serializado |
| `read_payload_chunk(params)` | Lee un chunk de caracteres. Borra el archivo al leer el último chunk |
| `_run_pipeline(project_path, force_full_scan, include_agents_md_context, ctx)` | Supervisa el worker, su progreso, cancelación y timeout |
| `_run_pipeline_sync(project_path, force_full_scan, include_agents_md_context, progress)` | Ejecuta el análisis dentro del worker |
| `_compute_total_chunks(payload_text)` | Calcula chunks de 20.000 caracteres |
| `_build_response(num_chunks, project_path)` | Construye la respuesta neutra con instrucciones para leer el payload |
| `_get_client_name(ctx)` | Extrae el nombre del cliente del handshake MCP inicial |
| `main()` | Entry point del proceso — llama `mcp.run()` |
