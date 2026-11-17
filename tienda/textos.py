"""Saca los textos en español de GESTOR para traducirlos.

    python tienda/textos.py            → escribe app/idiomas/_textos.json y dice cuántos faltan por idioma
    python tienda/textos.py --faltan en → imprime en JSON los textos que faltan en ese idioma

Busca en panel.html y login.html (texto, title, placeholder y las cadenas del JavaScript, también las
plantillas `...${x}...`, que quedan como «... {} ...») y en las cadenas de Python que parecen frases.
"""

import json
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app")
IDIOMAS = os.path.join(APP, "idiomas")
LETRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
ESPANOL = re.compile(r"[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|en|no|un|una|por|para|con|se|al|tu|tus|y|o|es|está|hay)\b", re.I)
PYTHON_SIN_TRADUCIR = {"idioma.py", "red.py"}


def normal(t):
    t = re.sub(r"\{[a-zñáéíóú_]+(:[^}]*)?\}", "{}", t)     # {n}, {proveedor}, {x:.1f} → {}
    return re.sub(r"\s+", " ", t).strip()


def _fin_cadena(codigo, i):
    """Índice justo después de la cadena que empieza en codigo[i] (', " o `)."""
    c, j, n = codigo[i], i + 1, len(codigo)
    while j < n:
        if codigo[j] == "\\":
            j += 2
            continue
        if c == "`" and codigo.startswith("${", j):
            j = _fin_expresion(codigo, j + 2)
            continue
        if codigo[j] == c or (c != "`" and codigo[j] == "\n"):
            return j + 1
        j += 1
    return n


def _fin_expresion(codigo, i):
    """Desde dentro de ${, índice justo después de la } que lo cierra."""
    profundidad, j, n = 1, i, len(codigo)
    while j < n:
        c = codigo[j]
        if c in "'\"`":
            j = _fin_cadena(codigo, j)
            continue
        if c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if not profundidad:
                return j + 1
        j += 1
    return n


def cadenas_js(codigo):
    """Literales '..', "..", `..` del JavaScript. Una plantilla `..${x}..` sale como «..{}..», y las
    cadenas de dentro de cada ${...} salen también por separado."""
    i, n = 0, len(codigo)
    while i < n:
        c = codigo[i]
        if c == "/" and codigo.startswith("//", i):
            i = codigo.find("\n", i)
            i = n if i < 0 else i
            continue
        if c == "/" and codigo.startswith("/*", i):
            i = codigo.find("*/", i)
            i = n if i < 0 else i + 2
            continue
        if c == "/":
            previo = codigo[:i].rstrip()[-1:]
            if not previo or previo in "(,=:[!&|?{};+-*%<>~^" or codigo[:i].rstrip().endswith("return"):
                j, en_clase = i + 1, False       # expresión regular /.../: se salta entera
                while j < n and codigo[j] != "\n":
                    if codigo[j] == "\\":
                        j += 2
                        continue
                    if codigo[j] == "[":
                        en_clase = True
                    elif codigo[j] == "]":
                        en_clase = False
                    elif codigo[j] == "/" and not en_clase:
                        break
                    j += 1
                i = j + 1
                continue
        if c in "'\"":
            fin = _fin_cadena(codigo, i)
            yield codigo[i + 1:fin - 1]
            i = fin
            continue
        if c == "`":
            fin = _fin_cadena(codigo, i)
            salida, j = [], i + 1
            while j < fin - 1:
                if codigo[j] == "\\":
                    salida.append(codigo[j:j + 2])
                    j += 2
                elif codigo.startswith("${", j):
                    k = _fin_expresion(codigo, j + 2)
                    yield from cadenas_js(codigo[j + 2:k - 1])
                    salida.append("{}")
                    j = k
                else:
                    salida.append(codigo[j])
                    j += 1
            yield "".join(salida)
            i = fin
            continue
        i += 1


def fragmentos(texto):
    """Parte un texto con HTML en los trozos que el navegador muestra como nodos de texto."""
    texto = texto.replace("\\n", " ").replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    for atributo in re.findall(r'(?:title|placeholder|aria-label|alt)="([^"]*)"', texto):
        yield atributo
    # La frase entera, quitando solo las etiquetas de formato (<code>, <b>…): idioma.js la traduce de una vez.
    sin_formato = re.sub(r"</?(code|b|strong|em|i|small|span|kbd|u|mark)(\s[^>]*)?>", "", texto)
    if sin_formato != texto:
        for trozo in re.split(r"<[^>]*>", sin_formato):
            trozo = normal(trozo.replace("&nbsp;", " "))
            if trozo and "{}" not in trozo.replace("{}", "", 0) or trozo:
                yield trozo
    for trozo in re.split(r"<[^>]*>", texto):
        trozo = normal(re.sub(r"&nbsp;", " ", trozo))
        trozo = trozo.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        if trozo:
            yield trozo
            # Si el trozo empieza o acaba con un valor (a menudo HTML), también sirve sin él.
            recortado = re.sub(r"^(\{\}\s*)+|(\s*\{\})+$", "", trozo).strip()
            if recortado and recortado != trozo:
                yield recortado
            if "{}" in recortado:               # el valor puede ser HTML (<code>…): cada lado por separado
                for lado in recortado.split("{}"):
                    lado = lado.strip(" ,;:")
                    if len(lado) > 3:
                        yield lado


def util(t):
    t = normal(t)
    if len(t) < 2 or not LETRA.search(t):
        return False
    sin_valores = t.replace("{}", "")
    if not LETRA.search(sin_valores):
        return False
    if re.fullmatch(r"[#.\w-]+", t) and (re.search(r"[#._\d-]", t) or re.search(r"[a-z][A-Z]", t)):
        return False                           # selectores, claves, nombres de variables
    if re.search(r"^(/api/|https?://|var\(|#[0-9a-f]{3})|\.(png|ico|json|html|js|css)$|[{};]\s*$", t) and " " not in t:
        return False
    if re.search(r"\w=[\w\"']|=>|\(\)|function|querySelector|getElement|\$\(|;\s*$|^\s*;", t):
        return False
    if re.fullmatch(r"[a-z_]+", t):            # claves internas («intervalo», «diario»)
        return False
    if re.fullmatch(r"(#[0-9A-Fa-f]{3,8}\s*)+", t) or re.fullmatch(r"(\.[\w-]+\s*)+", t):
        return False                           # colores y listas de extensiones
    if "(?" in t or re.search(r"\w\|\w", t):    # expresiones regulares
        return False
    return True


def de_html(ruta):
    with open(ruta, encoding="utf-8") as f:
        html = f.read()
    textos = set()
    html_sin_estilo = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    partes = re.split(r"(<script[^>]*>.*?</script>)", html_sin_estilo, flags=re.S)
    for parte in partes:
        if parte.startswith("<script"):
            for literal in cadenas_js(parte):
                for t in fragmentos(literal):
                    if util(t):
                        textos.add(normal(t))
        else:
            for t in fragmentos(parte):
                if util(t) and not t.startswith("<!"):
                    textos.add(normal(t))
    return textos


def de_python(ruta):
    import ast
    with open(ruta, encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    textos = set()
    docstrings = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if nodo.body and isinstance(nodo.body[0], ast.Expr) and isinstance(getattr(nodo.body[0], "value", None), ast.Constant):
                docstrings.add(id(nodo.body[0].value))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.JoinedStr):
            partes = []
            for v in nodo.values:
                partes.append(v.value if isinstance(v, ast.Constant) else "{}")
            t = normal("".join(partes))
        elif isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and id(nodo) not in docstrings:
            t = normal(nodo.value)
        else:
            continue
        # En Python solo las frases: con un espacio y algo de español, o una palabra con mayúscula.
        if not util(t) or len(t) > 400:
            continue
        if " " in t and ESPANOL.search(t) or re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+", t):
            ruta_sola = re.search(r"\\|/", t) and "→" not in t and not re.search(r"[a-záéíóúñ]{3,} [a-záéíóúñ]{3,} ", t)
            if not ruta_sola and not re.search(r"%\w|\$_|Get-|\bSELECT\b|\bCREATE\b|powershell", t):
                textos.add(t)
    return textos


# Frases que el panel arma pegando trozos y no se pueden sacar solas del código.
EXTRA = ["Faltan librerías opcionales: {}. El .exe ya las incluye.", "{} servicio activo de {}",
         "{} servicios activos de {}", "Cada {} minutos", "Cada {} horas", "Cada {} días", "minutos", "horas",
         "Si es {}", "extensión {}"]


def todos():
    textos = set(EXTRA)
    for nombre in ("panel.html", "login.html"):
        textos |= de_html(os.path.join(APP, nombre))
    for nombre in sorted(os.listdir(APP)):
        if nombre.endswith(".py") and nombre not in PYTHON_SIN_TRADUCIR:
            textos |= de_python(os.path.join(APP, nombre))
    return sorted(textos)


def diccionario(codigo):
    try:
        with open(os.path.join(IDIOMAS, f"{codigo}.json"), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def main():
    textos = todos()
    if len(sys.argv) > 2 and sys.argv[1] == "--faltan":
        d = diccionario(sys.argv[2])
        print(json.dumps([t for t in textos if t not in d], ensure_ascii=False, indent=1))
        return
    os.makedirs(IDIOMAS, exist_ok=True)
    with open(os.path.join(IDIOMAS, "_textos.json"), "w", encoding="utf-8") as f:
        json.dump(textos, f, ensure_ascii=False, indent=1)
    print(f"{len(textos)} textos")
    for nombre in sorted(os.listdir(IDIOMAS)):
        if nombre.endswith(".json") and not nombre.startswith("_"):
            d = diccionario(nombre[:-5])
            faltan = sum(1 for t in textos if t not in d)
            print(f"  {nombre[:-5]}: {len(textos) - faltan} traducidos, faltan {faltan}")


if __name__ == "__main__":
    main()
