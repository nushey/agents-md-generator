# instructions.py

## Rol

Genera el campo `instructions` que va embebido en el payload. Este campo es un prompt completo que le dice al cliente MCP exactamente cómo transformar el payload en un AGENTS.md de calidad.

## Por qué existe como módulo separado

El prompt es el componente más volátil del sistema — se ajusta con frecuencia a medida que se descubren casos donde el output del modelo no cumple las expectativas. Al tener su propio módulo, los cambios al prompt no tocan ninguna lógica de análisis, y viceversa.

## Estructura del prompt (`_build_instructions`)

El prompt se adapta según si el proyecto ya tiene un AGENTS.md:
- **Sin AGENTS.md existente**: `"CREATE a new AGENTS.md"` + instrucción de escribir desde cero
- **Con AGENTS.md existente**: `"UPDATE the existing AGENTS.md"` + instrucción de preservar secciones no afectadas por los cambios

El cuerpo del prompt tiene cuatro secciones:

### ABSOLUTE RULES

Prohibiciones absolutas escritas en imperativo:
1. No leer archivos del proyecto (ni con Read, Glob, Grep, ni Bash)
2. No llamar a `generate_agents_md` de nuevo
3. No enumerar archivos en tablas o listas
4. No enumerar clases, interfaces ni funciones por nombre — sintetizar patrones
5. No inventar comandos o herramientas ausentes del payload
6. Usar solo los datos del payload

### WHAT AGENTS.MD IS

Define qué ES y qué NO ES AGENTS.md. Es un "README para agentes de IA" que responde preguntas operativas (cómo agregar un archivo, qué comando ejecutar, qué no romper). No es documentación, ni changelog, ni índice de archivos.

### HOW TO USE THE PAYLOAD DATA

Instrucciones específicas por campo del payload:
- `full_analysis`: sintetizar patrones, no listar archivos ni símbolos
- `method_patterns`: tabla de lookup para firmas de métodos deduplicadas — cuando un método en `full_analysis` es una clave corta como `"m0"`, resolver via esta tabla
- `project_structure.directories`: describir qué hace cada capa, no listar paths
- `build_system.scripts`: copiar verbatim en bloques de código

Incluye ejemplos concretos de síntesis correcta vs incorrecta.

### FORMAT

Define las secciones de AGENTS.md y qué debe contener cada una:
- Project Overview
- Architecture & Data Flow (con módulo inventory obligatorio)
- Conventions & Patterns
- Environment Variables
- Setup Commands
- Development Workflow
- Testing Instructions
- Code Style
- Build and Deployment
- Keeping AGENTS.md Up to Date (siempre presente, verbatim)

Termina con un Quality Bar que define el estándar mínimo aceptable.

## Funciones

| Función | Qué hace |
|---|---|
| `_build_instructions(has_existing)` | Retorna el prompt completo como string. `has_existing=True` genera instrucciones de actualización, `False` de creación desde cero |
