"""GESTOR: idiomas de la interfaz.

GESTOR está escrito en español. Los diccionarios de app/idiomas/<código>.json traducen cada texto en
español al otro idioma: {"texto en español": "traducción"}. Un texto con partes variables lleva {} (o {0},
{1}...) en el lugar de cada parte: «Se movieron {} archivos» → «{} files moved».

- En el panel, idioma.js traduce lo que se ve (ver ese archivo).
- En Python, t("texto") traduce los avisos, el menú del icono, etc.

El ajuste «idioma» vale "auto" (el idioma de Windows) o un código de IDIOMAS. GESTOR_IDIOMA lo sustituye.
"""

import json
import locale
import os
import re

import nucleo

IDIOMAS = [("es", "Español"), ("en", "English"), ("pt", "Português"), ("fr", "Français")]
CODIGOS = {c for c, _ in IDIOMAS}
NOMBRE_AUTO = {"es": "Automático", "en": "Automatic", "pt": "Automático", "fr": "Automatique"}
CARPETA = os.path.join(nucleo.BASE, "idiomas")

_diccionarios = {}
_plantillas = {}


def idioma_de_windows():
    """El idioma de la interfaz de Windows, reducido a uno de IDIOMAS (si no lo hay, inglés)."""
    codigo = ""
    if nucleo.ES_WINDOWS:
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            codigo = locale.windows_locale.get(lcid, "")
        except Exception:
            codigo = ""
    if not codigo:
        codigo = (os.environ.get("LANG") or locale.getlocale()[0] or "").replace("-", "_")
    base = codigo.split("_")[0].lower()
    return base if base in CODIGOS else ("es" if not codigo else "en")


def eleccion():
    """Lo que eligió la persona: "auto" o un código."""
    valor = os.environ.get("GESTOR_IDIOMA") or nucleo.cargar_ajustes().get("idioma", "auto")
    return valor if valor in CODIGOS else "auto"


def actual():
    valor = eleccion()
    return idioma_de_windows() if valor == "auto" else valor


def diccionario(codigo):
    if codigo == "es":
        return {}
    if codigo not in _diccionarios:
        try:
            with open(os.path.join(CARPETA, f"{codigo}.json"), encoding="utf-8") as f:
                _diccionarios[codigo] = {k: v for k, v in json.load(f).items() if isinstance(v, str) and v}
        except (OSError, ValueError):
            _diccionarios[codigo] = {}
    return _diccionarios[codigo]


def _normal(texto):
    return re.sub(r"\s+", " ", texto).strip()


def _lista_plantillas(codigo):
    if codigo not in _plantillas:
        lista = []
        for origen, destino in diccionario(codigo).items():
            if re.search(r"\{\d*\}", origen):
                partes = re.split(r"\{\d*\}", _normal(origen))
                if len(re.findall(r"[^\W\d_]", "".join(partes))) < 5:
                    continue                    # «de {}», «{} a {}»: encajarían con cualquier cosa
                literal = [_literal(partes[i], partes[i + 1]) for i in range(len(partes) - 1)]
                lista.append((re.compile("^" + "(.*?)".join(re.escape(p) for p in partes) + "$", re.S),
                               destino, len("".join(partes)), literal))
        lista.sort(key=lambda x: -x[2])
        _plantillas[codigo] = lista
    return _plantillas[codigo]


def _literal(antes, despues):
    """Un valor entre «» o comillas, o pegado a «\\» (una ruta), es un dato tuyo: no se traduce."""
    return antes.endswith(("\\", "«", '"', "“", "'")) or despues.startswith(("\\", "»", '"', "”", "'"))


def _rellenar(destino, valores, codigo, literal=()):
    contador = iter(range(len(valores)))

    def poner(m):
        i = int(m.group(1)) if m.group(1) else next(contador, len(valores))
        if i >= len(valores):
            return ""
        return valores[i] if i < len(literal) and literal[i] else t(valores[i], codigo)
    return re.sub(r"\{(\d*)\}", poner, destino)


def t(texto, codigo=None):
    """Traduce un texto en español al idioma actual. Si no está en el diccionario, lo deja igual."""
    if not isinstance(texto, str) or not texto.strip():
        return texto
    codigo = codigo or actual()
    if codigo == "es":
        return texto
    limpio = _normal(texto)
    dicc = diccionario(codigo)
    if limpio in dicc:
        return dicc[limpio]
    for patron, destino, _, literal in _lista_plantillas(codigo):
        m = patron.match(limpio)
        if m:
            return _rellenar(destino, m.groups(), codigo, literal)
    return texto


def datos_para_el_panel():
    codigo = actual()
    return {"idioma": codigo, "eleccion": eleccion(), "textos": diccionario(codigo),
            "idiomas": IDIOMAS, "nombre_auto": NOMBRE_AUTO.get(codigo, "Auto")}


def inyectar(html):
    """Añade al <head> de una página el diccionario y idioma.js."""
    try:
        with open(os.path.join(nucleo.BASE, "idioma.js"), "rb") as f:
            script = f.read()
    except OSError:
        return html
    datos = json.dumps(datos_para_el_panel(), ensure_ascii=False).replace("</", "<\\/").encode("utf-8")
    bloque = b"<script>window.GESTOR_I18N=" + datos + b";</script>\n<script>" + script + b"</script>\n"
    if b"</head>" in html:
        return html.replace(b"</head>", bloque + b"</head>", 1)
    return bloque + html


def guardar_eleccion(valor):
    valor = valor if valor in CODIGOS else "auto"
    ajustes = nucleo.cargar_ajustes()
    ajustes["idioma"] = valor
    nucleo.guardar_ajustes(ajustes)
    return valor
