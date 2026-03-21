# server.py

## Rol

Es el punto de entrada de la aplicación. Define el servidor MCP y expone la única herramienta pública: `generate_agents_md`. Todo lo que hace Claude Code al invocar el MCP pasa por acá.

## Conceptos clave

### FastMCP

`FastMCP` es el framework que abstrae el protocolo MCP. Al instanciar `FastMCP("agents_md_mcp")` y decorar una función con `@mcp.tool(...)`, esa función queda registrada como una herramienta que cualquier cliente MCP (Claude Code) puede descubrir y llamar.

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
8. **Retornar respuesta pequeña** — un JSON de ~1k chars con instrucciones para Claude

### Por qué el payload va a disco y no inline

El payload puede tener miles de líneas. Si se enviara inline como respuesta del tool, viaja todo por el contexto de Claude de una sola vez — caro, lento, y puede superar límites. En cambio, se escribe en `~/.cache/agents-md-generator/<hash>/payload.json` y se le dice a Claude la ruta exacta para que lo lea en chunks con su tool `Read`.

### `_build_response`

Calcula cuántos chunks necesita Claude para leer el payload (basado en 2000 líneas por chunk) y construye instrucciones paso a paso que Claude debe seguir exactamente:

```
STEP 1 → Read payload
STEP 2 → Parse JSON, usar solo esos datos
STEP 3 → Escribir AGENTS.md
STEP 4 → Borrar el payload temporal
STEP 5 → Informar al usuario
```

Estas instrucciones son imperativas a propósito — el campo `instructions` del response le dice a Claude "no hagas nada más, no leas código, no hagas preguntas". Esto previene que el modelo alucine o explore el proyecto por su cuenta.

### El caso `no_changes`

Si `detect_changes` devuelve lista vacía, el server retorna un JSON especial con `"status": "no_changes"` y un mensaje que le dice a Claude que pregunte al usuario si quiere mejorar el AGENTS.md existente de todas formas. Esto evita que Claude llame al tool en loop con `force_full_scan=True` por su cuenta.

## Funciones

| Función | Qué hace |
|---|---|
| `generate_agents_md(params)` | Entry point del tool MCP. Valida el path y delega a `_run_pipeline` |
| `_run_pipeline(project_path, force_full_scan)` | Ejecuta los 8 pasos del pipeline de análisis |
| `_build_response(payload_path, payload_lines, agents_md_path)` | Construye la respuesta pequeña con instrucciones para Claude |
| `main()` | Entry point del proceso — llama `mcp.run()` |
