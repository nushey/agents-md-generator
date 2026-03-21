# languages/ — Analyzers de AST

## Estructura

```
languages/
├── base.py        ← interfaz abstracta
├── python.py      ← PythonAnalyzer
├── typescript.py  ← TypeScriptAnalyzer + JavaScriptAnalyzer
├── csharp.py      ← CSharpAnalyzer
└── go.py          ← GoAnalyzer
```

---

## base.py — La interfaz

`LanguageAnalyzer` es una clase abstracta con dos miembros obligatorios:

- `language_key` (property abstracta): devuelve el identificador del lenguaje, ej. `"python"`, `"c_sharp"`, `"go"`
- `analyze(path, source)` (método abstracto): recibe el path relativo y el contenido del archivo en bytes, devuelve un `FileAnalysis`

Todo analyzer concreto que implemente esta interfaz puede ser registrado en `ast_analyzer.py` sin tocar nada más. Es el patrón Strategy.

---

## ¿Qué es tree-sitter?

tree-sitter es un parser incremental que convierte código fuente en un Concrete Syntax Tree (CST). A diferencia de los parsers de compiladores, tree-sitter:
- Soporta muchos lenguajes con el mismo API
- Es tolerante a errores — parsea código parcialmente inválido
- Trabaja con bytes, no strings

Cada lenguaje tiene una "grammar" — una biblioteca nativa (`.so`) que describe la sintaxis del lenguaje. El paquete `tree-sitter-python` contiene la grammar de Python, `tree-sitter-c-sharp` la de C#, etc.

El flujo es siempre:
1. `Language(grammar_module.language())` — carga la grammar
2. `Parser(language)` — crea el parser
3. `parser.parse(source_bytes)` — genera el árbol
4. Walk del árbol con `root_node` para extraer símbolos

---

## python.py — PythonAnalyzer

### Visibilidad

Python no tiene modificadores de acceso explícitos. La visibilidad se infiere del nombre:
- `__name` (doble underscore sin trailing) → `"private"`
- `_name` (single underscore) → `"protected"`
- `name` → `"public"`

### Walk recursivo

El método `_walk` recorre el árbol de forma recursiva. La clave del diseño:
- Al encontrar una `class_definition`, recurre en su `body` pasando el nombre de la clase como `parent_class`
- Al encontrar una `function_definition`, si `parent_class != None` → es un método, sino → es una función
- **No recursa en el body de las funciones** — esto evita extraer funciones anidadas que no son parte de la API pública
- `decorated_definition` es un nodo envolvente — se recursa en él para llegar a la `function_definition` o `class_definition` que wrappea

### Decoradores

Python tiene los decoradores en el nodo padre (`decorated_definition`), no en el nodo de la función. `_get_decorators` sube al nodo padre y extrae los textos de los hijos de tipo `"decorator"`.

---

## typescript.py — TypeScriptAnalyzer y JavaScriptAnalyzer

### Dos grammars, un analyzer

TypeScript tiene dos grammars: `language_typescript()` (para `.ts`) y `language_tsx()` (para `.tsx`, que agrega soporte de JSX). Se pasan al constructor como `lang_key`.

`JavaScriptAnalyzer` hereda de `TypeScriptAnalyzer` pero con la grammar de JavaScript. El AST de JS y TS es suficientemente similar para que el mismo walker funcione.

### Arrow functions

TypeScript/JavaScript permite funciones como `const handler = (x) => x + 1`. El nodo en el AST es `variable_declarator` con un hijo `value` de tipo `arrow_function`. El analyzer detecta este caso específicamente y registra la variable como un símbolo de tipo `"function"`.

### Exports

TypeScript tiene un sistema de exports explícito. Al encontrar un nodo `export_statement`, se extrae el nombre de la declaración exportada y se agrega a la lista `exports` del `FileAnalysis`. Esto ayuda a identificar la API pública del módulo.

### Visibilidad

TypeScript tiene modificadores explícitos (`private`, `protected`, `public`). `_infer_visibility` escanea los hijos del nodo buscando esos tokens. Si no encuentra ninguno, asume `"public"` (que es el default en TS).

---

## csharp.py — CSharpAnalyzer

### _KIND_MAP

C# tiene muchos tipos de declaraciones. El mapa `_KIND_MAP` traduce los tipos de nodo de tree-sitter al vocabulario interno del sistema:

```python
"class_declaration"       → "class"
"interface_declaration"   → "interface"
"struct_declaration"      → "struct"
"enum_declaration"        → "enum"
"method_declaration"      → "method"
"constructor_declaration" → "method"   # constructores tratados como métodos
"property_declaration"    → "property"
"field_declaration"       → "field"
```

### Visibilidad default en C#

En C#, el default de visibilidad para miembros de clase es `private` (no `public` como en Python o TypeScript). `_extract_visibility` retorna `"private"` cuando no encuentra ningún modificador explícito.

### Atributos en vez de decoradores

C# usa `[Attribute]` en vez de decoradores. `_extract_attributes` busca nodos `attribute_list` y extrae los nombres de los atributos — `[HttpGet]`, `[Route("api/")]`, etc. Estos se mapean al campo `decorators` de `SymbolInfo` para que `classify_impact` pueda detectar endpoints HTTP.

### field_declaration

Los campos (`public int Id;`) no tienen un nodo `name` directo — tienen un `variable_declaration` con `variable_declarator` adentro. `_walk` maneja este caso especial buscando el nombre en esa jerarquía.

---

## go.py — GoAnalyzer

### Visibilidad por convención

En Go no hay keywords de visibilidad. La regla es: si el nombre empieza con mayúscula, es exportado (público). Si empieza con minúscula, es privado. `_is_exported(name)` implementa exactamente esta regla: `name[0].isupper()`.

### Methods vs Functions

Go no tiene clases — tiene tipos con métodos. Un method declaration tiene un `receiver`: `func (r *Repository) Save(...)`. El analyzer extrae el tipo del receiver para usarlo como `parent`, igual que si fuera la "clase" a la que pertenece el método.

### type_declaration — struct vs interface

`type Foo struct {...}` y `type Bar interface {...}` usan el mismo nodo `type_declaration` con un hijo `type_spec`. El analyzer determina el kind inspeccionando el tipo del child: `struct_type` → `"struct"`, `interface_type` → `"interface"`, cualquier otro → `"class"` (para type aliases, etc.).

---

## Agregar un nuevo lenguaje

1. Instalar el paquete `tree-sitter-<lang>`
2. Crear `languages/<lang>.py` implementando `LanguageAnalyzer`
3. Agregar la extensión en `config.py::EXTENSION_TO_LANGUAGE`
4. Registrar el analyzer en `ast_analyzer.py::build_analyzer`

Eso es todo. Ningún otro módulo necesita cambios.
