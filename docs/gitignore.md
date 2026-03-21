# gitignore.py

## Rol

Provee soporte de `.gitignore` para proyectos que no son repositorios git. Cuando `git ls-files` no está disponible, el sistema necesita saber qué archivos ignorar — este módulo carga todos los `.gitignore` del proyecto y crea un spec que puede consultar si un path está ignorado.

## Conceptos clave

### pathspec — la librería correcta para esto

No se usa `fnmatch` ni regex para parsear `.gitignore` — se usa `pathspec`, una librería que implementa exactamente la semántica de gitignore: negaciones (`!pattern`), paths relativos al directorio del `.gitignore`, wildcards de doble `**`, etc. Un parser casero fallaría en edge cases. `pathspec` es la implementación de referencia.

### Múltiples .gitignore anidados

La función `load_gitignore_spec` no lee solo el `.gitignore` raíz — hace `rglob(".gitignore")` y procesa TODOS los archivos `.gitignore` del árbol. Los patrones de subdirectorios se prefijan con el path relativo del directorio donde vive ese `.gitignore`. Esto replica el comportamiento real de git.

```
/project/.gitignore          → patrones sin prefijo
/project/src/.gitignore      → patrones prefijados con "src/"
/project/vendor/.gitignore   → patrones prefijados con "vendor/"
```

### Por qué solo se usa para non-git repos

Para repos git, `git ls-files` ya devuelve solo los archivos trackeados (que por definición no están ignorados). Parsear `.gitignore` manualmente sería redundante y potencialmente inconsistente. `load_gitignore_spec` se llama solo cuando `_git_ls_files` devuelve `None`.

### Caso None

Si no hay ningún `.gitignore` en el proyecto, `load_gitignore_spec` retorna `None`. `is_gitignored(path, None)` retorna `False` — si no hay spec, nada está ignorado. El código que llama siempre puede pasar `None` sin verificar.

## Funciones

| Función | Qué hace |
|---|---|
| `load_gitignore_spec(project_path)` | Lee todos los `.gitignore` del proyecto y retorna un `PathSpec` combinado, o `None` si no hay ninguno |
| `is_gitignored(path, spec)` | Retorna `True` si el path matchea el spec. Acepta `spec=None` de forma segura |
