# cache.py

## Rol

Gestiona la persistencia del estado entre runs. La cache evita que se re-parsee con tree-sitter todo el proyecto en cada invocación — solo se analizan los archivos que cambiaron. También valida que la cache sea coherente con el estado actual del repositorio git.

## Conceptos clave

### Ubicación de la cache

```
~/.cache/agents-md-generator/<project-hash>/cache.json
```

El `<project-hash>` es un SHA-256 de los primeros 16 caracteres del path absoluto del proyecto. Esto garantiza:
- **Un directorio de cache por proyecto** — dos proyectos en rutas distintas no se mezclan
- **Nada se escribe dentro del repositorio** — la cache vive completamente fuera del proyecto analizado
- **Si el proyecto se mueve de ruta**, el hash cambia y el próximo run hace cold start automáticamente

### Validación con git

`is_cache_valid` ejecuta `git cat-file -t <base_commit>` para verificar que el commit almacenado en cache todavía existe en el repositorio. Esto protege contra dos escenarios problemáticos:
- **Rebase / history rewrite** — el commit cacheado puede no existir después de un `git rebase`
- **Clone limpio** — si alguien copia solo el código sin la cache, el commit no existe en el nuevo repo

Si el commit no existe, se hace cold start aunque haya un archivo de cache.

### Por qué se guarda el commit y no solo los hashes

Los hashes de archivos detectan qué cambió. El `base_commit` responde cuándo fue el último scan — útil para validar la coherencia global. Si el commit desaparece (rebase), es señal de que el historial cambió y la cache podría estar desincronizada.

### make_empty_cache

Crea una cache vacía con el commit actual como `base_commit`. Se usa al inicio de cada run para construir la nueva cache desde cero, copiando solo las entradas que no cambiaron y agregando las nuevas.

### Resiliencia ante corrupción

`load_cache` atrapa cualquier excepción durante la lectura o validación del JSON y retorna `None` en vez de propagar el error. Un `None` hace que el server haga cold start — comportamiento degradado pero funcional.

## Funciones

| Función | Qué hace |
|---|---|
| `get_project_cache_dir(project_path)` | Calcula y crea el directorio de cache del proyecto usando SHA-256 del path |
| `load_cache(project_path)` | Lee `cache.json`, devuelve `CacheData` o `None` si no existe/está corrupta |
| `save_cache(project_path, data)` | Persiste `CacheData` a disco en formato JSON indentado |
| `is_cache_valid(cache, project_path)` | Verifica con git que el `base_commit` de la cache todavía existe |
| `make_empty_cache(base_commit)` | Crea una `CacheData` vacía con timestamp UTC y el commit actual |
| `get_current_commit(project_path)` | Ejecuta `git rev-parse HEAD` y devuelve el SHA, o `None` si no es un repo |
