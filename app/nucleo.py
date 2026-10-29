"""GESTOR: lógica común del panel y del motor.

Solo usa la biblioteca estándar de Python. Si Pillow está instalado se usa
para leer la fecha de captura de más formatos de foto; si no, se usa un lector
propio que entiende JPEG.
"""

import calendar
import datetime as dt
import fnmatch
import functools
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import time
import uuid

ES_WINDOWS = os.name == "nt"
EMPAQUETADO = getattr(sys, "frozen", False)  # convertido en .exe con PyInstaller

# BASE: donde está el programa. DATOS: donde se guarda tu configuración y el historial.
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATOS = os.environ.get("GESTOR_DATOS") or (
    os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GESTOR") if ES_WINDOWS
    else os.path.join(os.path.expanduser("~"), ".gestor"))
os.makedirs(DATOS, exist_ok=True)

ARCHIVO_SERVICIOS = os.path.join(DATOS, "servicios.json")
ARCHIVO_ESTADO = os.path.join(DATOS, "estado.json")
ARCHIVO_AJUSTES = os.path.join(DATOS, "ajustes.json")
ARCHIVO_BLOQUEO = os.path.join(DATOS, "motor.lock")
ARCHIVO_ERRORES = os.path.join(DATOS, "errores.log")
ARCHIVO_AVISOS = os.path.join(DATOS, "avisos.jsonl")
CARPETA_REGISTRO = os.path.join(DATOS, "registro")
MAX_REGISTROS_POR_SERVICIO = 50

CATEGORIAS = {
    "Imágenes": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif",
                 ".tif", ".tiff", ".svg", ".ico", ".raw", ".cr2", ".nef", ".arw", ".dng"],
    "Vídeos": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".mpg", ".mpeg"],
    "Música": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"],
    "Documentos": [".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".epub"],
    "Hojas de cálculo": [".xls", ".xlsx", ".xlsm", ".ods", ".csv"],
    "Presentaciones": [".ppt", ".pptx", ".odp", ".key"],
    "Comprimidos": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"],
    "Instaladores": [".exe", ".msi", ".msix", ".appx", ".bat", ".cmd"],
    "Código": [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".java", ".c", ".cpp",
               ".cs", ".php", ".sql", ".ps1", ".sh", ".yml", ".yaml"],
}

# Archivos que ningún servicio toca: descargas a medias, accesos directos, archivos del sistema.
IGNORAR_SIEMPRE = ["archivo ????-??.zip", "*.crdownload", "*.part", "*.partial", "*.tmp", "*.download", "~$*",
                   "desktop.ini", "thumbs.db", ".ds_store", "*.lnk", "*.url"]

MESES = ["", "01-Enero", "02-Febrero", "03-Marzo", "04-Abril", "05-Mayo", "06-Junio", "07-Julio",
         "08-Agosto", "09-Septiembre", "10-Octubre", "11-Noviembre", "12-Diciembre"]

AJUSTES_POR_DEFECTO = {"revisar_cada_minutos": 5, "pausado": False, "notificaciones": True,
                       "icono_bandeja": True, "papelera": "gestor", "retencion_dias": 30, "copias": []}
ARCHIVO_PAPELERA = os.path.join(DATOS, "papelera.json")
PUERTO_RESIDENTE = int(os.environ.get("GESTOR_PUERTO_RESIDENTE", "8766"))
MAX_HECHOS = 5000


# --------------------------------------------------------------------------- archivos JSON

def leer_json(ruta, por_defecto):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return por_defecto
    except (OSError, ValueError):
        return por_defecto


def escribir_json(ruta, datos):
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


def cargar_servicios():
    if not os.path.exists(ARCHIVO_SERVICIOS):
        servicios = plantillas_iniciales()
        escribir_json(ARCHIVO_SERVICIOS, servicios)
        return servicios
    return leer_json(ARCHIVO_SERVICIOS, [])


def guardar_servicios(servicios):
    escribir_json(ARCHIVO_SERVICIOS, servicios)


def cargar_ajustes():
    ajustes = dict(AJUSTES_POR_DEFECTO)
    ajustes.update(leer_json(ARCHIVO_AJUSTES, {}))
    return ajustes


def guardar_ajustes(ajustes):
    escribir_json(ARCHIVO_AJUSTES, ajustes)


def cargar_estado():
    return leer_json(ARCHIVO_ESTADO, {})


def guardar_estado(estado):
    escribir_json(ARCHIVO_ESTADO, estado)


# --------------------------------------------------------------------------- carpetas de Windows

_CARPETAS_CONOCIDAS = {
    "Descargas": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    "Documentos": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "Escritorio": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "Imágenes": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "Vídeos": ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Videos"),
    "Música": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "Music"),
}


def carpeta_conocida(nombre):
    """Ruta real de Descargas, Documentos, etc., aunque estén en OneDrive o movidas."""
    guid, por_defecto = _CARPETAS_CONOCIDAS[nombre]
    if ES_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID(guid)
            g = GUID(u.fields[0], u.fields[1], u.fields[2],
                     (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            ruta = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None,
                                                          ctypes.byref(ruta)) == 0:
                valor = ruta.value
                ctypes.windll.ole32.CoTaskMemFree(ruta)
                return valor
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), por_defecto)


def carpetas_rapidas():
    return {nombre: carpeta_conocida(nombre) for nombre in _CARPETAS_CONOCIDAS}


def _norm(ruta):
    return os.path.normcase(os.path.normpath(os.path.abspath(ruta)))


def _dentro_de(ruta, carpeta):
    ruta, carpeta = _norm(ruta), _norm(carpeta)
    return ruta == carpeta or ruta.startswith(carpeta.rstrip(os.sep) + os.sep)


def carpetas_prohibidas():
    if not ES_WINDOWS:
        return ["/bin", "/boot", "/etc", "/lib", "/proc", "/sys", "/usr", "/var"]
    lista = []
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        if os.environ.get(var):
            lista.append(os.environ[var])
    return lista


def revisar_carpeta(ruta):
    """Devuelve (permitida, aviso). Prohibidas: sistema y programas. Avisos: raíz de disco, AppData."""
    if not ruta:
        return False, "Carpeta vacía."
    for prohibida in carpetas_prohibidas():
        if _dentro_de(ruta, prohibida):
            return False, "Es una carpeta del sistema o de programas: GESTOR no actúa ahí."
    if _norm(ruta) == _norm(os.path.splitdrive(os.path.abspath(ruta))[0] + os.sep):
        return True, "Es la raíz de un disco: revisa bien las reglas antes de activarlo."
    if "appdata" in _norm(ruta).split(os.sep):
        return True, "Es una carpeta AppData, donde los programas guardan sus datos."
    return True, ""


# --------------------------------------------------------------------------- plantillas

def nuevo_id():
    return uuid.uuid4().hex[:10]


def plantillas_iniciales():
    """Servicios para Descargas, Documentos y Escritorio. Se crean desactivados."""
    descargas = carpeta_conocida("Descargas")
    documentos = carpeta_conocida("Documentos")
    escritorio = carpeta_conocida("Escritorio")
    imagenes = carpeta_conocida("Imágenes")
    horario = {"tipo": "intervalo", "cada": 8, "unidad": "horas"}

    def regla(categoria, destino, fecha="modificacion"):
        return {"id": nuevo_id(), "si": {"categorias": [categoria]}, "accion": "mover",
                "destino": destino, "fecha": fecha, "nuevo_nombre": ""}

    return [
        {
            "id": nuevo_id(), "nombre": "Ordenar Descargas", "activo": False,
            "origenes": [descargas], "subcarpetas": False, "horario": dict(horario),
            "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
            "esperar_minutos": 10, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "{procedencia}", "{año}", "{mes}")),
                regla("Documentos", os.path.join(documentos, "Descargados", "{año}")),
                regla("Hojas de cálculo", os.path.join(documentos, "Descargados", "{año}")),
                regla("Presentaciones", os.path.join(documentos, "Descargados", "{año}")),
                regla("Instaladores", os.path.join(descargas, "Instaladores")),
                regla("Comprimidos", os.path.join(descargas, "Comprimidos")),
                regla("Vídeos", os.path.join(descargas, "Vídeos")),
                regla("Música", os.path.join(descargas, "Música")),
            ],
        },
        {
            "id": nuevo_id(), "nombre": "Ordenar Documentos", "activo": False,
            "origenes": [documentos], "subcarpetas": False, "horario": dict(horario),
            "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
            "esperar_minutos": 30, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "{procedencia}", "{año}", "{mes}")),
                regla("Documentos", os.path.join(documentos, "{categoria}", "{año}")),
                regla("Hojas de cálculo", os.path.join(documentos, "{categoria}", "{año}")),
                regla("Presentaciones", os.path.join(documentos, "{categoria}", "{año}")),
            ],
        },
        {
            "id": nuevo_id(), "nombre": "Ordenar Escritorio", "activo": False,
            "origenes": [escritorio], "subcarpetas": False, "horario": dict(horario),
            "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
            "esperar_minutos": 60, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "{procedencia}", "{año}", "{mes}")),
                {"id": nuevo_id(), "si": {"antiguedad_mayor_dias": 7}, "accion": "mover",
                 "destino": os.path.join(documentos, "Escritorio", "{año}-{mes_num}"),
                 "fecha": "modificacion", "nuevo_nombre": ""},
            ],
        },
    ]


# --------------------------------------------------------------------------- metadatos de fotos

def _exif_jpeg(ruta):
    """Lee los datos EXIF de un JPEG sin librerías externas."""
    with open(ruta, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            return {}
        while True:
            marca = f.read(2)
            if len(marca) < 2 or marca[0] != 0xFF:
                return {}
            if marca[1] in (0xD9, 0xDA):
                return {}
            largo = struct.unpack(">H", f.read(2))[0]
            datos = f.read(largo - 2)
            if marca[1] == 0xE1 and datos[:6] == b"Exif\x00\x00":
                return _exif_tiff(datos[6:])


def _exif_tiff(t):
    if len(t) < 8:
        return {}
    orden = "<" if t[:2] == b"II" else ">"

    def ifd(desplazamiento):
        if desplazamiento + 2 > len(t):
            return {}
        n = struct.unpack(orden + "H", t[desplazamiento:desplazamiento + 2])[0]
        entradas = {}
        for i in range(n):
            p = desplazamiento + 2 + i * 12
            if p + 12 > len(t):
                break
            etiqueta, tipo, cuenta = struct.unpack(orden + "HHI", t[p:p + 8])
            entradas[etiqueta] = (tipo, cuenta, t[p + 8:p + 12])
        return entradas

    def texto(entrada):
        tipo, cuenta, valor = entrada
        if tipo != 2:
            return None
        if cuenta <= 4:
            crudo = valor[:cuenta]
        else:
            p = struct.unpack(orden + "I", valor)[0]
            crudo = t[p:p + cuenta]
        return crudo.split(b"\x00")[0].decode("ascii", "ignore").strip() or None

    principal = ifd(struct.unpack(orden + "I", t[4:8])[0])
    exif = ifd(struct.unpack(orden + "I", principal[0x8769][2])[0]) if 0x8769 in principal else {}
    leer = lambda tabla, etiqueta: texto(tabla[etiqueta]) if etiqueta in tabla else None
    return {
        "fecha": leer(exif, 0x9003) or leer(exif, 0x9004) or leer(principal, 0x0132),
        "marca": leer(principal, 0x010F),
        "modelo": leer(principal, 0x0110),
        "software": leer(principal, 0x0131),
    }


def _parsear_fecha_exif(valor):
    if not valor:
        return None
    try:
        return dt.datetime.strptime(valor.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


@functools.lru_cache(maxsize=4096)
def _metadatos(ruta, _mtime):
    """Fecha de captura, marca y modelo de cámara. Usa Pillow si está instalado."""
    datos = {}
    try:
        from PIL import Image  # opcional
        try:
            import pillow_heif  # opcional, para .heic
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        with Image.open(ruta) as img:
            exif = img.getexif()
            datos = {"fecha": exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132),
                     "marca": exif.get(0x010F), "modelo": exif.get(0x0110), "software": exif.get(0x0131)}
            datos = {k: str(v).strip("\x00 ") for k, v in datos.items() if v}
    except Exception:
        datos = {}
    if not datos and os.path.splitext(ruta)[1].lower() in (".jpg", ".jpeg"):
        try:
            datos = {k: v for k, v in (_exif_jpeg(ruta) or {}).items() if v}
        except (OSError, struct.error, ValueError):
            datos = {}
    return datos


def metadatos_foto(ruta):
    if categoria_de(os.path.splitext(ruta)[1].lower()) != "Imágenes":
        return {}
    try:
        return _metadatos(ruta, os.path.getmtime(ruta))
    except OSError:
        return {}


def fecha_captura(ruta):
    return _parsear_fecha_exif(metadatos_foto(ruta).get("fecha"))


# --------------------------------------------------------------------------- procedencia

PROCEDENCIAS = ["Cámara", "WhatsApp", "Telegram", "Captura de pantalla", "Escáner",
                "Descarga de internet", "Desconocida"]

_PATRONES_NOMBRE = [
    ("WhatsApp", r"^(img|vid|aud|ptt|stk|doc)-\d{8}-wa\d+"
                 r"|^whatsapp (image|video|audio|ptt|document)"
                 r"|^(imagen|video|vídeo|audio|documento) de whatsapp"),
    ("Telegram", r"^(photo|video|file|voice|sticker|audio)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"),
    ("Captura de pantalla", r"^(screenshot|screen shot|captura de pantalla|captura_de_pantalla"
                            r"|screen recording|grabación de pantalla|recorte de pantalla)"),
    ("Escáner", r"^(scan|escane|scanned|documento escaneado)"),
    ("Cámara", r"^(img_\d{8}_\d{6}|img_\d{4}\b|img\d{8}|dsc[fn_]?\d{4}|_dsc\d{4}|pxl_\d{8}"
               r"|vid_\d{8}|mvimg_|gopr\d|gx\d{6}|dji_\d|p\d{7}\.|\d{8}_\d{6}|mov_\d{4})"),
]

_PATRONES_CARPETA = [
    ("WhatsApp", ("whatsapp",)),
    ("Telegram", ("telegram desktop", "telegram")),
    ("Captura de pantalla", ("screenshots", "capturas de pantalla", "capturas")),
    ("Cámara", ("dcim", "camera", "cámara", "camara")),
]


def _zona_descarga(ruta):
    """Datos que Windows guarda al descargar un archivo de internet (Zone.Identifier)."""
    if not ES_WINDOWS:
        return {}
    try:
        with open(ruta + ":Zone.Identifier", "r", encoding="utf-8", errors="ignore") as f:
            texto = f.read()
    except OSError:
        return {}
    datos = dict(re.findall(r"^(\w+)=(.*)$", texto, re.MULTILINE))
    return {"zona": datos.get("ZoneId", "").strip(),
            "url": (datos.get("HostUrl") or datos.get("ReferrerUrl") or "").strip()}


def _dominio(url):
    m = re.match(r"^[a-z]+://([^/:?#]+)", url or "", re.IGNORECASE)
    return m.group(1).lower() if m else ""


@functools.lru_cache(maxsize=4096)
def _procedencia(ruta, _mtime):
    nombre = os.path.basename(ruta).lower()
    for procedencia, patron in _PATRONES_NOMBRE:
        if re.search(patron, nombre):
            break
    else:
        procedencia = None
    carpetas = [c.lower() for c in os.path.normpath(os.path.dirname(ruta)).split(os.sep)]
    if not procedencia:
        for nombre_proc, claves in _PATRONES_CARPETA:
            if any(c.startswith(claves) for c in carpetas):
                procedencia = nombre_proc
                break
    meta = metadatos_foto(ruta)
    if not procedencia and meta.get("marca"):
        procedencia = "Cámara"
    zona = _zona_descarga(ruta)
    sitio = _dominio(zona.get("url"))
    if not procedencia and sitio:
        if "whatsapp" in sitio:
            procedencia = "WhatsApp"
        elif "telegram" in sitio or sitio.endswith("t.me"):
            procedencia = "Telegram"
    if not procedencia and zona.get("zona") in ("3", "4"):
        procedencia = "Descarga de internet"
    camara = " ".join(x for x in (meta.get("marca"), meta.get("modelo")) if x)
    if meta.get("marca") and meta.get("modelo", "").lower().startswith(meta["marca"].lower()):
        camara = meta["modelo"]
    return {"procedencia": procedencia or "Desconocida", "camara": camara or "Desconocida",
            "sitio": sitio or "Desconocido"}


def procedencia_de(ruta):
    try:
        return _procedencia(ruta, os.path.getmtime(ruta))
    except OSError:
        return {"procedencia": "Desconocida", "camara": "Desconocida", "sitio": "Desconocido"}


def fecha_archivo(ruta, st, fuente):
    if fuente == "captura":
        fecha = fecha_captura(ruta)
        if fecha:
            return fecha
    if fuente == "creacion":
        return dt.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_ctime if ES_WINDOWS else st.st_mtime))
    return dt.datetime.fromtimestamp(st.st_mtime)


# --------------------------------------------------------------------------- contenido de documentos

EXT_CON_TEXTO = {".pdf", ".docx", ".txt", ".md", ".csv", ".xml", ".json", ".html", ".htm", ".rtf"}
MAX_PAGINAS_PDF = 5
MAX_CARACTERES = 200_000


def pypdf_disponible():
    try:
        import pypdf  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1024)
def _texto(ruta, _mtime):
    extension = os.path.splitext(ruta)[1].lower()
    try:
        if extension == ".pdf":
            import pypdf  # opcional
            lector = pypdf.PdfReader(ruta)
            if lector.is_encrypted:
                return ""
            paginas = lector.pages[:MAX_PAGINAS_PDF]
            return "\n".join((p.extract_text() or "") for p in paginas)[:MAX_CARACTERES]
        if extension == ".docx":
            import zipfile
            with zipfile.ZipFile(ruta) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            xml = re.sub(r"</w:p>", "\n", xml)
            return re.sub(r"<[^>]+>", "", xml)[:MAX_CARACTERES]
        with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(MAX_CARACTERES)
    except Exception:
        return ""


def texto_de(ruta):
    """Texto de un PDF (primeras páginas), DOCX o archivo de texto. Vacío si no se puede leer."""
    if os.path.splitext(ruta)[1].lower() not in EXT_CON_TEXTO:
        return ""
    try:
        return _texto(ruta, os.path.getmtime(ruta))
    except OSError:
        return ""


def _contenido_cumple(c, ruta):
    valor = c.get("contenido_valor")
    if not valor:
        return True
    texto = texto_de(ruta)
    if not texto:
        return False
    if c.get("contenido_modo") == "regex":
        try:
            return re.search(valor, texto, re.IGNORECASE) is not None
        except re.error:
            return False
    # Varias palabras separadas por coma: tienen que aparecer todas.
    texto = texto.lower()
    return all(p.strip().lower() in texto for p in valor.split(",") if p.strip())


# --------------------------------------------------------------------------- reglas

def categoria_de(extension):
    for nombre, extensiones in CATEGORIAS.items():
        if extension in extensiones:
            return nombre
    return "Otros"


def _lista_ext(valor):
    if isinstance(valor, str):
        valor = re.split(r"[,\s;]+", valor)
    resultado = []
    for e in valor or []:
        e = e.strip().lower()
        if e:
            resultado.append(e if e.startswith(".") else "." + e)
    return resultado


def cumple(condiciones, ruta, st, ahora):
    nombre = os.path.basename(ruta)
    base, extension = os.path.splitext(nombre)
    extension = extension.lower()
    c = condiciones or {}

    if c.get("categorias") and categoria_de(extension) not in c["categorias"]:
        return False
    if c.get("extensiones") and extension not in _lista_ext(c["extensiones"]):
        return False
    if c.get("procedencias") and procedencia_de(ruta)["procedencia"] not in c["procedencias"]:
        return False
    texto = c.get("nombre_valor")
    if texto:
        modo = c.get("nombre_modo", "contiene")
        n, v = nombre.lower(), texto.lower()
        if modo == "contiene" and v not in n:
            return False
        if modo == "empieza" and not n.startswith(v):
            return False
        if modo == "termina" and not base.lower().endswith(v):
            return False
        if modo == "regex":
            try:
                if not re.search(texto, nombre, re.IGNORECASE):
                    return False
            except re.error:
                return False
    mb = st.st_size / (1024 * 1024)
    if c.get("tamano_mayor_mb") not in (None, "") and mb <= float(c["tamano_mayor_mb"]):
        return False
    if c.get("tamano_menor_mb") not in (None, "") and mb >= float(c["tamano_menor_mb"]):
        return False
    dias = (ahora - st.st_mtime) / 86400
    if c.get("antiguedad_mayor_dias") not in (None, "") and dias <= float(c["antiguedad_mayor_dias"]):
        return False
    if c.get("antiguedad_menor_dias") not in (None, "") and dias >= float(c["antiguedad_menor_dias"]):
        return False
    return _contenido_cumple(c, ruta)  # lo más costoso, al final


def _limpiar_nombre(texto):
    return re.sub(r'[<>:"/\\|?*]', "_", texto).strip() or "_"


def expandir(patron, ruta, origen, fecha):
    nombre = os.path.basename(ruta)
    base, extension = os.path.splitext(nombre)
    valores = {
        "categoria": categoria_de(extension.lower()),
        "extension": extension.lower().lstrip(".") or "sin_extension",
        "año": f"{fecha.year:04d}", "anio": f"{fecha.year:04d}",
        "mes": MESES[fecha.month], "mes_num": f"{fecha.month:02d}",
        "dia": f"{fecha.day:02d}",
        "nombre": base,
        "carpeta_origen": os.path.basename(os.path.normpath(origen)),
        "origen": os.path.normpath(origen),
    }
    if re.search(r"\{(procedencia|camara|sitio)\}", patron):
        valores.update(procedencia_de(ruta))

    def sustituir(m):
        clave = m.group(1)
        if clave not in valores:
            return m.group(0)
        if clave == "origen":
            return valores[clave]
        return _limpiar_nombre(valores[clave])

    return re.sub(r"\{([a-zñ_]+)\}", sustituir, patron)


def _raiz_fija(destino):
    """Parte del destino anterior a la primera variable, para no volver a ordenar lo ya ordenado."""
    corte = destino.split("{", 1)[0]
    return os.path.dirname(corte) if "{" in destino else destino


def _ignorado(nombre, patrones):
    n = nombre.lower()
    return any(fnmatch.fnmatch(n, p.lower()) for p in patrones)


def _nombre_libre(destino):
    if not os.path.exists(destino):
        return destino
    base, extension = os.path.splitext(destino)
    i = 1
    while os.path.exists(f"{base} ({i}){extension}"):
        i += 1
    return f"{base} ({i}){extension}"


# --------------------------------------------------------------------------- papelera

def a_papelera(ruta):
    if not ES_WINDOWS:
        destino = os.path.join(os.path.expanduser("~"), ".local", "share", "Trash", "files")
        os.makedirs(destino, exist_ok=True)
        shutil.move(ruta, _nombre_libre(os.path.join(destino, os.path.basename(ruta))))
        return
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 16, 64, 1024
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(ruta) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI,
                         False, None, None)
    codigo = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if codigo != 0 or op.fAnyOperationsAborted:
        raise OSError(f"No se pudo enviar a la papelera (código {codigo}).")


# --------------------------------------------------------------------------- papelera de GESTOR

def _carpeta_papelera_para(ruta):
    """En la misma unidad que el archivo, para no copiar gigas de un disco a otro."""
    propia = os.path.join(DATOS, "papelera")
    unidad = os.path.splitdrive(os.path.abspath(ruta))[0]
    if not ES_WINDOWS or not unidad or unidad.lower() == os.path.splitdrive(DATOS)[0].lower():
        return propia
    return os.path.join(unidad + os.sep, "GESTOR-papelera")


def _ocultar(ruta):
    if ES_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(ruta, 0x02)  # oculto
        except Exception:
            pass


def quitar(ruta, motivo=""):
    """Quita un archivo de su sitio sin borrarlo: a la papelera de GESTOR (o la de Windows).

    Devuelve el id de la entrada en la papelera de GESTOR, o None si fue a la de Windows.
    """
    if cargar_ajustes().get("papelera", "gestor") == "windows":
        a_papelera(ruta)
        return None
    pid = dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    raiz = _carpeta_papelera_para(ruta)
    destino = os.path.join(raiz, pid, os.path.basename(ruta))
    try:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        _ocultar(raiz)
    except OSError:
        destino = os.path.join(DATOS, "papelera", pid, os.path.basename(ruta))
        os.makedirs(os.path.dirname(destino), exist_ok=True)
    tam = os.path.getsize(ruta)
    shutil.move(ruta, destino)
    indice = leer_json(ARCHIVO_PAPELERA, [])
    indice.append({"id": pid, "origen": ruta, "guardado": destino, "bytes": tam, "motivo": motivo,
                   "fecha": dt.datetime.now().isoformat(timespec="seconds")})
    escribir_json(ARCHIVO_PAPELERA, indice)
    return pid


def listar_papelera():
    dias = int(cargar_ajustes().get("retencion_dias", 30))
    resultado = []
    for e in reversed(leer_json(ARCHIVO_PAPELERA, [])):
        caduca = dt.datetime.fromisoformat(e["fecha"]) + dt.timedelta(days=dias)
        resultado.append(dict(e, caduca=caduca.isoformat(timespec="minutes"), existe=os.path.exists(e["guardado"])))
    return resultado


def restaurar(pid):
    indice = leer_json(ARCHIVO_PAPELERA, [])
    entrada = next((e for e in indice if e["id"] == pid), None)
    if not entrada:
        raise OSError("ya no está en la papelera de GESTOR")
    destino = entrada["origen"]
    if os.path.exists(destino):
        destino = _nombre_libre(destino)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(entrada["guardado"], destino)
    _borrar_carpeta_si_vacia(os.path.dirname(entrada["guardado"]))
    escribir_json(ARCHIVO_PAPELERA, [e for e in indice if e["id"] != pid])
    return destino


def _borrar_carpeta_si_vacia(carpeta):
    try:
        os.rmdir(carpeta)
    except OSError:
        pass


def purgar_papelera(todo=False, ids=None):
    """Borra de verdad lo que lleva más días que la retención (o todo, o los ids indicados)."""
    dias = int(cargar_ajustes().get("retencion_dias", 30))
    limite = dt.datetime.now() - dt.timedelta(days=dias)
    quedan, borrados, liberados = [], 0, 0
    for e in leer_json(ARCHIVO_PAPELERA, []):
        borrar = todo or (ids and e["id"] in ids) or (not ids and dt.datetime.fromisoformat(e["fecha"]) < limite)
        if not borrar:
            quedan.append(e)
            continue
        try:
            if os.path.exists(e["guardado"]):
                os.remove(e["guardado"])
            _borrar_carpeta_si_vacia(os.path.dirname(e["guardado"]))
            borrados += 1
            liberados += e.get("bytes", 0)
        except OSError:
            quedan.append(e)
    escribir_json(ARCHIVO_PAPELERA, quedan)
    return {"borrados": borrados, "bytes": liberados}


# --------------------------------------------------------------------------- limpiar nombres

_RESTOS_DE_COPIA = [
    r"\s*\((\d+|copia(\s*\d+)?|copy(\s*\d+)?)\)$",
    r"\s*-\s*(copia|copy)(\s*\(\d+\))?$",
    r"\s+(copia|copy)(\s*\d+)?$",
    r"^(copia de|copy of)\s+",
    r"^copia \(\d+\) de\s+",
]
_FECHA_INICIO = re.compile(r"^(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)[\s_-]*")
_FECHA_INICIO_DMA = re.compile(r"^(\d{2})[-_.](\d{2})[-_.](\d{4})(?!\d)[\s_-]*")


def limpiar_nombre(base, fecha=None):
    """Quita restos de copias, espacios dobles y caracteres raros. Con fecha, la pone al inicio."""
    nuevo = base
    cambiado = True
    while cambiado:  # "foto (1) - copia (2)" necesita varias pasadas
        cambiado = False
        for patron in _RESTOS_DE_COPIA:
            limpio = re.sub(patron, "", nuevo, flags=re.IGNORECASE)
            if limpio != nuevo and limpio.strip():
                nuevo, cambiado = limpio, True
    # Letras (con acentos), números, espacios y unos pocos signos; el resto se quita.
    nuevo = "".join(c if (c.isalnum() or c in " -_.,()&'+#@") else " " for c in nuevo)
    nuevo = re.sub(r"\s+", " ", nuevo).strip(" ._-") or base
    if fecha:
        m = _FECHA_INICIO.match(nuevo)
        m2 = _FECHA_INICIO_DMA.match(nuevo)
        if m:
            nuevo = f"{m.group(1)}-{m.group(2)}-{m.group(3)} " + nuevo[m.end():]
        elif m2:
            nuevo = f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)} " + nuevo[m2.end():]
        else:
            nuevo = f"{fecha:%Y-%m-%d} {nuevo}"
        nuevo = nuevo.strip()
    return nuevo


# --------------------------------------------------------------------------- ejecutar un servicio

def planificar(servicio, ahora=None, esperar_segundos=None, ya_hechos=None):
    """Lista de operaciones que haría el servicio, sin tocar nada.

    esperar_segundos sustituye a "esperar_minutos" (el modo al instante usa unos segundos).
    ya_hechos son archivos que GESTOR ya renombró en su sitio, para no renombrarlos otra vez.
    """
    ahora = ahora or time.time()
    ignorar = IGNORAR_SIEMPRE + [p for p in servicio.get("ignorar", []) if p]
    esperar = (float(servicio.get("esperar_minutos") or 0) * 60 if esperar_segundos is None
               else esperar_segundos)
    ya_hechos = ya_hechos or {}
    reglas = servicio.get("reglas", [])
    plan, avisos = [], []
    destinos_previstos = set()

    for origen in servicio.get("origenes", []):
        permitida, aviso = revisar_carpeta(origen)
        if not permitida:
            avisos.append(f"{origen}: {aviso}")
            continue
        if not os.path.isdir(origen):
            avisos.append(f"{origen}: la carpeta no existe.")
            continue
        # Carpetas de destino dentro del origen: no se recorren, para no reordenar lo ordenado.
        excluir = [_norm(_raiz_fija(r["destino"].replace("{origen}", origen)))
                   for r in reglas if r.get("destino")]
        if servicio.get("identicos") == "carpeta":
            excluir.append(_norm(_raiz_fija((servicio.get("carpeta_duplicados") or os.path.join(
                "{origen}", "Duplicados")).replace("{origen}", origen))))
        excluir = [e for e in excluir if e != _norm(origen)]
        for carpeta, subcarpetas, archivos in os.walk(origen):
            if not servicio.get("subcarpetas"):
                subcarpetas[:] = []
            else:
                subcarpetas[:] = [d for d in subcarpetas
                                  if not d.startswith(".")
                                  and not any(_dentro_de(os.path.join(carpeta, d), e) for e in excluir)]
            for nombre in archivos:
                if _ignorado(nombre, ignorar):
                    continue
                ruta = os.path.join(carpeta, nombre)
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                if ahora - st.st_mtime < esperar:
                    continue
                if ya_hechos.get(_norm(ruta)) == int(st.st_mtime):
                    continue
                for regla in reglas:
                    if not cumple(regla.get("si"), ruta, st, ahora):
                        continue
                    op = _operacion(regla, ruta, st, origen, servicio, destinos_previstos)
                    if op:
                        plan.append(op)
                    break
    return plan, avisos


def _huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.digest()


def _copia_identica(ruta, st, destino):
    """Busca en el destino un archivo con el mismo nombre (o "nombre (N)") y el mismo contenido.

    Primero compara el tamaño, que es gratis; la huella SHA-256 solo se calcula si coincide.
    """
    base, ext = os.path.splitext(destino)
    candidato, i, huella = destino, 1, None
    while os.path.exists(candidato):
        try:
            if os.path.getsize(candidato) == st.st_size:
                huella = huella or _huella(ruta)
                if _huella(candidato) == huella:
                    return candidato
        except OSError:
            pass
        candidato = f"{base} ({i}){ext}"
        i += 1
    return None


def _con_fecha(base, fecha):
    """Solo pone (o uniforma) la fecha al inicio, sin más limpieza."""
    m = _FECHA_INICIO.match(base)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)} " + base[m.end():]
    return f"{fecha:%Y-%m-%d} {base}"


def fuente_fecha(ruta, regla, servicio):
    """Las fotos usan la fecha de captura (EXIF) si el servicio lo tiene activado; el resto, la de la regla."""
    if servicio.get("fecha_captura_fotos", True) and categoria_de(os.path.splitext(ruta)[1].lower()) == "Imágenes":
        return "captura"
    fuente = regla.get("fecha", "modificacion")
    return "modificacion" if fuente == "captura" else fuente


def pillow_disponible():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _operacion(regla, ruta, st, origen, servicio, destinos_previstos):
    accion = regla.get("accion", "mover")
    if accion == "papelera":
        return {"accion": "papelera", "origen": ruta, "destino": "", "regla": regla.get("id"),
                "bytes": st.st_size, "categoria": categoria_de(os.path.splitext(ruta)[1].lower())}
    fecha = fecha_archivo(ruta, st, fuente_fecha(ruta, regla, servicio))
    categoria = categoria_de(os.path.splitext(ruta)[1].lower())
    if accion == "archivar":
        carpeta = os.path.abspath(expandir(regla.get("destino") or os.path.join("{origen}", "Archivados"),
                                           ruta, origen, fecha))
        zip_ruta = os.path.join(carpeta, f"Archivo {fecha:%Y-%m}.zip")
        return {"accion": "archivar", "origen": ruta, "destino": zip_ruta, "regla": regla.get("id"),
                "bytes": st.st_size, "categoria": categoria}
    nombre = os.path.basename(ruta)
    extension = os.path.splitext(nombre)[1]
    if regla.get("nuevo_nombre"):
        nombre = _limpiar_nombre(expandir(regla["nuevo_nombre"], ruta, origen, fecha)) + extension
    limpiado = False
    if servicio.get("limpiar_nombres") or servicio.get("fecha_al_inicio"):
        base = os.path.splitext(nombre)[0]
        nuevo = limpiar_nombre(base, fecha if servicio.get("fecha_al_inicio") else None) \
            if servicio.get("limpiar_nombres") else _con_fecha(base, fecha)
        limpiado = nuevo != base
        nombre = nuevo + extension
    if accion == "renombrar":
        carpeta = os.path.dirname(ruta)
    else:
        carpeta = expandir(regla.get("destino", ""), ruta, origen, fecha)
        if not carpeta:
            return None
        carpeta = os.path.abspath(carpeta)
    destino = os.path.join(carpeta, nombre)
    if _norm(destino) == _norm(ruta):
        return None
    identicos = servicio.get("identicos", "papelera")
    if os.path.exists(destino) and identicos != "conflicto":
        gemelo = _copia_identica(ruta, st, destino)
        if gemelo and _norm(gemelo) != _norm(ruta):
            if accion == "copiar":
                return None  # la copia ya está en el destino
            base_op = {"origen": ruta, "regla": regla.get("id"), "identico_a": gemelo, "bytes": st.st_size,
                       "categoria": categoria, "duplicado": True, "tras_limpiar": limpiado}
            if identicos == "carpeta":
                carpeta_dup = os.path.abspath(expandir(servicio.get("carpeta_duplicados")
                                                       or os.path.join("{origen}", "Duplicados"),
                                                       ruta, origen, fecha))
                destino_dup = os.path.join(carpeta_dup, os.path.basename(ruta))
                while os.path.exists(destino_dup) or _norm(destino_dup) in destinos_previstos:
                    destino_dup = _nombre_libre(destino_dup) if os.path.exists(destino_dup) else \
                        os.path.join(carpeta_dup, f"{uuid.uuid4().hex[:4]} {os.path.basename(ruta)}")
                destinos_previstos.add(_norm(destino_dup))
                return dict(base_op, accion="mover", destino=destino_dup)
            return dict(base_op, accion="papelera", destino="")
    conflicto = servicio.get("conflicto", "renombrar")
    if os.path.exists(destino) or _norm(destino) in destinos_previstos:
        if conflicto == "saltar":
            return None
        if conflicto == "renombrar":
            base, ext = os.path.splitext(destino)
            i = 1
            while os.path.exists(destino) or _norm(destino) in destinos_previstos:
                destino = f"{base} ({i}){ext}"
                i += 1
    destinos_previstos.add(_norm(destino))
    return {"accion": accion, "origen": ruta, "destino": destino, "regla": regla.get("id"),
            "bytes": st.st_size, "categoria": categoria_de(os.path.splitext(ruta)[1].lower())}


def _archivar(origen, zip_ruta):
    """Añade el archivo al ZIP del mes, comprueba que se lee bien y solo entonces lo quita de su sitio."""
    import zipfile
    os.makedirs(os.path.dirname(zip_ruta), exist_ok=True)
    nombre = os.path.basename(origen)
    with zipfile.ZipFile(zip_ruta, "a", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        existentes = set(z.namelist())
        base, ext = os.path.splitext(nombre)
        i = 1
        while nombre in existentes:
            nombre = f"{base} ({i}){ext}"
            i += 1
        z.write(origen, nombre)
    with zipfile.ZipFile(zip_ruta) as z:
        with z.open(nombre) as f:  # leerlo entero comprueba el CRC
            while f.read(1024 * 1024):
                pass
        if z.getinfo(nombre).file_size != os.path.getsize(origen):
            raise OSError("el archivo no se guardó bien en el ZIP")
    return nombre


def aplicar(op):
    accion, origen, destino = op["accion"], op["origen"], op["destino"]
    if accion == "papelera":
        op["papelera_id"] = quitar(origen, "duplicado" if op.get("duplicado") else "regla")
        return
    if accion == "archivar":
        op["nombre_en_zip"] = _archivar(origen, destino)
        op["papelera_id"] = quitar(origen, "archivado")
        return
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if accion == "copiar":
        if os.path.exists(destino):
            os.remove(destino)
        shutil.copy2(origen, destino)
    else:
        if os.path.exists(destino) and _norm(destino) != _norm(origen):
            os.remove(destino)  # solo ocurre con conflicto = "reemplazar"
        shutil.move(origen, destino)


def ejecutar_servicio(servicio, simular=False, esperar_segundos=None, ya_hechos=None):
    plan, avisos = planificar(servicio, esperar_segundos=esperar_segundos, ya_hechos=ya_hechos)
    if simular:
        return {"simulado": True, "operaciones": plan, "avisos": avisos}
    hechas, errores = [], []
    for op in plan:
        try:
            aplicar(op)
            hechas.append(op)
        except Exception as e:  # archivo en uso, sin permisos, ruta demasiado larga...
            errores.append(dict(op, error=str(e)))
    registro = {
        "servicio": servicio["id"], "nombre": servicio.get("nombre", ""),
        "fecha": dt.datetime.now().isoformat(timespec="seconds"),
        "operaciones": hechas, "errores": errores, "avisos": avisos, "deshecho": False,
    }
    if hechas and servicio.get("borrar_carpetas_vacias"):
        registro["carpetas_borradas"] = borrar_carpetas_vacias(servicio, hechas)
    if hechas or errores:
        guardar_registro(registro)
    return registro


def borrar_carpetas_vacias(servicio, hechas):
    """Borra las carpetas que se han quedado vacías dentro de los orígenes (nunca el origen en sí)."""
    origenes = [_norm(o) for o in servicio.get("origenes", [])]
    candidatas = set()
    for op in hechas:
        if op["accion"] == "copiar":
            continue
        carpeta = os.path.dirname(op["origen"])
        while _norm(carpeta) not in origenes and any(_dentro_de(carpeta, o) for o in origenes):
            candidatas.add(carpeta)
            carpeta = os.path.dirname(carpeta)
    borradas = []
    for carpeta in sorted(candidatas, key=len, reverse=True):  # primero las más profundas
        try:
            restos = os.listdir(carpeta)
            if all(r.lower() in ("desktop.ini", "thumbs.db", ".ds_store") for r in restos):
                for r in restos:
                    os.remove(os.path.join(carpeta, r))
                os.rmdir(carpeta)
                borradas.append(carpeta)
        except OSError:
            pass
    return borradas


# --------------------------------------------------------------------------- registro y deshacer

def _carpeta_registro(servicio_id):
    return os.path.join(CARPETA_REGISTRO, re.sub(r"[^a-zA-Z0-9_-]", "", servicio_id))


def guardar_registro(registro):
    carpeta = _carpeta_registro(registro["servicio"])
    os.makedirs(carpeta, exist_ok=True)
    nombre = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
    escribir_json(os.path.join(carpeta, nombre), registro)
    archivos = sorted(os.listdir(carpeta))
    for viejo in archivos[:-MAX_REGISTROS_POR_SERVICIO]:
        try:
            os.remove(os.path.join(carpeta, viejo))
        except OSError:
            pass


def listar_registros(servicio_id, limite=20):
    carpeta = _carpeta_registro(servicio_id)
    if not os.path.isdir(carpeta):
        return []
    resultado = []
    for nombre in sorted(os.listdir(carpeta), reverse=True)[:limite]:
        datos = leer_json(os.path.join(carpeta, nombre), None)
        if datos:
            datos["archivo"] = nombre
            resultado.append(datos)
    return resultado


def deshacer(servicio_id, archivo=None):
    """Devuelve los archivos de una ejecución (la última si no se indica) a su sitio."""
    carpeta = _carpeta_registro(servicio_id)
    if not os.path.isdir(carpeta):
        return {"ok": False, "mensaje": "No hay ejecuciones registradas."}
    candidatos = sorted(os.listdir(carpeta), reverse=True)
    if archivo:
        candidatos = [archivo] if archivo in candidatos else []
    for nombre in candidatos:
        ruta = os.path.join(carpeta, nombre)
        registro = leer_json(ruta, None)
        if not registro or registro.get("deshecho") or not registro.get("operaciones"):
            if archivo:
                return {"ok": False, "mensaje": "Esa ejecución ya se deshizo o no movió nada."}
            continue
        devueltos, fallos = 0, []
        for op in reversed(registro["operaciones"]):
            try:
                if op["accion"] in ("mover", "renombrar"):
                    if os.path.exists(op["origen"]):
                        raise OSError("ya existe un archivo en la ubicación original")
                    os.makedirs(os.path.dirname(op["origen"]), exist_ok=True)
                    shutil.move(op["destino"], op["origen"])
                elif op["accion"] == "copiar":
                    quitar(op["destino"], "deshacer copia")
                elif op.get("papelera_id"):
                    restaurar(op["papelera_id"])
                else:
                    raise OSError("estaba en la papelera de Windows: restáuralo desde ahí")
                devueltos += 1
            except Exception as e:
                fallos.append(f'{op["origen"]}: {e}')
        registro["deshecho"] = True
        registro["deshecho_fecha"] = dt.datetime.now().isoformat(timespec="seconds")
        registro["fallos_deshacer"] = fallos
        escribir_json(ruta, registro)
        return {"ok": True, "devueltos": devueltos, "fallos": fallos}
    return {"ok": False, "mensaje": "No hay ninguna ejecución pendiente de deshacer."}


# --------------------------------------------------------------------------- horarios

def _horas(lista):
    resultado = []
    for h in lista or []:
        try:
            hh, mm = str(h).split(":")
            resultado.append(dt.time(int(hh), int(mm)))
        except ValueError:
            continue
    return sorted(resultado)


def _ocurrencias(horario, desde, hasta):
    """Horas programadas entre dos fechas, para los horarios de calendario."""
    tipo = horario.get("tipo")
    horas = _horas(horario.get("horas")) or [dt.time(9, 0)]
    dia = desde.date()
    while dia <= hasta.date():
        valido = False
        if tipo == "diario":
            valido = True
        elif tipo == "semanal":
            valido = dia.weekday() in [int(d) for d in horario.get("dias", [])]
        elif tipo == "mensual":
            ultimo = calendar.monthrange(dia.year, dia.month)[1]
            dias = [int(d) for d in horario.get("dias_mes", [])]
            valido = dia.day in dias or (dia.day == ultimo and any(d > ultimo for d in dias))
        if valido:
            for h in horas:
                momento = dt.datetime.combine(dia, h)
                if desde < momento <= hasta:
                    yield momento
        dia += dt.timedelta(days=1)


def _intervalo(horario):
    cada = max(float(horario.get("cada") or 1), 0.0167)
    unidad = horario.get("unidad", "horas")
    return dt.timedelta(minutes=cada) if unidad == "minutos" else (
        dt.timedelta(days=cada) if unidad == "dias" else dt.timedelta(hours=cada))


def toca_ejecutar(servicio, estado_servicio, ahora):
    horario = servicio.get("horario") or {}
    tipo = horario.get("tipo", "manual")
    if tipo in ("manual", "inicio", "instante"):
        return False
    ultima = estado_servicio.get("ultima")
    referencia = dt.datetime.fromisoformat(ultima) if ultima else None
    if tipo == "intervalo":
        return referencia is None or ahora - referencia >= _intervalo(horario)
    if referencia is None:
        referencia = dt.datetime.fromisoformat(estado_servicio.get("visto", ahora.isoformat()))
    # Si el equipo estuvo apagado a la hora programada, se ejecuta en cuanto se encienda.
    desde = max(referencia, ahora - dt.timedelta(days=62))
    return next(_ocurrencias(horario, desde, ahora), None) is not None


def proxima_ejecucion(servicio, estado_servicio, ahora=None):
    ahora = ahora or dt.datetime.now()
    horario = servicio.get("horario") or {}
    tipo = horario.get("tipo", "manual")
    if not servicio.get("activo") or tipo == "manual":
        return None
    if tipo == "inicio":
        return "al iniciar sesión"
    if tipo == "instante":
        return "al instante"
    if tipo == "intervalo":
        ultima = estado_servicio.get("ultima")
        if not ultima:
            return "en la próxima revisión"
        momento = dt.datetime.fromisoformat(ultima) + _intervalo(horario)
        return "en la próxima revisión" if momento <= ahora else momento.isoformat(timespec="minutes")
    if toca_ejecutar(servicio, estado_servicio, ahora):
        return "en la próxima revisión"
    momento = next(_ocurrencias(horario, ahora, ahora + dt.timedelta(days=62)), None)
    return momento.isoformat(timespec="minutes") if momento else None


# --------------------------------------------------------------------------- bloqueo

class Bloqueo:
    """Evita que el motor y el panel ordenen archivos a la vez."""

    def __enter__(self):
        for _ in range(60):
            try:
                fd = os.open(ARCHIVO_BLOQUEO, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(ARCHIVO_BLOQUEO) > 7200:
                        os.remove(ARCHIVO_BLOQUEO)
                        continue
                except OSError:
                    pass
                time.sleep(1)
        raise RuntimeError("Otra ejecución de GESTOR está en marcha. Prueba de nuevo en un momento.")

    def __exit__(self, *args):
        try:
            os.remove(ARCHIVO_BLOQUEO)
        except OSError:
            pass


def ejecutar_y_anotar(servicio, motivo="manual", esperar_segundos=None):
    with Bloqueo():
        estado = cargar_estado()
        e = estado.setdefault(servicio["id"], {})
        registro = ejecutar_servicio(servicio, esperar_segundos=esperar_segundos,
                                     ya_hechos=e.get("hechos"))
        e["ultima"] = dt.datetime.now().isoformat(timespec="seconds")
        e["ultimo_resultado"] = {"movidos": len(registro["operaciones"]),
                                 "errores": len(registro["errores"]), "motivo": motivo}
        anotar_totales(e, registro["operaciones"])
        # Archivos renombrados en su misma carpeta: se recuerdan para no renombrarlos otra vez.
        hechos = e.setdefault("hechos", {})
        for op in registro["operaciones"]:
            if op["destino"] and _norm(os.path.dirname(op["destino"])) == _norm(os.path.dirname(op["origen"])):
                try:
                    hechos[_norm(op["destino"])] = int(os.path.getmtime(op["destino"]))
                except OSError:
                    pass
        if len(hechos) > MAX_HECHOS:
            e["hechos"] = dict(list(hechos.items())[-MAX_HECHOS:])
        guardar_estado(estado)
        if registro["operaciones"] or registro["errores"]:
            n = len(registro["operaciones"])
            texto = f'{n} {"archivo ordenado" if n == 1 else "archivos ordenados"}'
            if registro["errores"]:
                texto += f', {len(registro["errores"])} con error'
            avisar(servicio.get("nombre", "GESTOR"), texto)
        duplicados = [op for op in registro["operaciones"] if op.get("duplicado")]
        if duplicados:
            tras = sum(1 for op in duplicados if op.get("tras_limpiar"))
            donde = "movidos a Duplicados" if servicio.get("identicos") == "carpeta" else "enviados a la papelera"
            detalle = f" ({tras} detectados al quitar \"(1)\" o \"copia\")" if tras else ""
            avisar("Duplicados detectados", f"{len(duplicados)} archivos idénticos a otros, {donde}{detalle}.")
        return registro


def anotar_totales(estado_servicio, operaciones):
    t = estado_servicio.setdefault("totales", {"archivos": 0, "bytes_ordenados": 0,
                                               "bytes_liberados": 0, "por_categoria": {},
                                               "por_accion": {}, "desde": dt.date.today().isoformat()})
    for op in operaciones:
        t["archivos"] += 1
        tam = op.get("bytes", 0)
        if op["accion"] == "papelera":
            t["bytes_liberados"] += tam
        else:
            t["bytes_ordenados"] += tam
        cat = op.get("categoria", "Otros")
        t["por_categoria"][cat] = t["por_categoria"].get(cat, 0) + 1
        t["por_accion"][op["accion"]] = t["por_accion"].get(op["accion"], 0) + 1


# --------------------------------------------------------------------------- duplicados en todo el disco

def _huella_parcial(ruta, tam=64 * 1024):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        h.update(f.read(tam))
    return h.digest()


def buscar_duplicados(carpetas, min_bytes=1024, progreso=None, cancelado=lambda: False):
    """Grupos de archivos con contenido idéntico, aunque tengan distinto nombre.

    Se filtra en tres pasos para no leer de más: mismo tamaño, mismos primeros 64 KB y
    misma huella SHA-256 completa. Devuelve los grupos ordenados por espacio recuperable.
    """
    progreso = progreso or (lambda **k: None)
    por_tamano, vistos, revisados = {}, set(), 0
    for raiz in carpetas:
        if not revisar_carpeta(raiz)[0]:
            continue
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            if cancelado():
                return []
            subcarpetas[:] = [d for d in subcarpetas if not d.startswith((".", "$"))
                              and d.lower() not in ("appdata", "node_modules", "__pycache__")
                              and revisar_carpeta(os.path.join(carpeta, d))[0]]
            for nombre in archivos:
                ruta = os.path.join(carpeta, nombre)
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                if st.st_size < min_bytes or _ignorado(nombre, IGNORAR_SIEMPRE):
                    continue
                clave = _norm(ruta)
                if clave in vistos:
                    continue
                vistos.add(clave)
                por_tamano.setdefault(st.st_size, []).append(ruta)
                revisados += 1
                if revisados % 500 == 0:
                    progreso(fase="Recorriendo carpetas", revisados=revisados)
    candidatos = [g for g in por_tamano.values() if len(g) > 1]
    total = sum(len(g) for g in candidatos)
    hechos, grupos = 0, []
    for grupo in candidatos:
        por_parcial = {}
        for ruta in grupo:
            if cancelado():
                return []
            try:
                por_parcial.setdefault(_huella_parcial(ruta), []).append(ruta)
            except OSError:
                pass
            hechos += 1
            if hechos % 50 == 0:
                progreso(fase="Comparando contenido", revisados=revisados, comparados=hechos, total=total)
        for sub in por_parcial.values():
            if len(sub) < 2:
                continue
            por_huella = {}
            for ruta in sub:
                try:
                    por_huella.setdefault(_huella(ruta), []).append(ruta)
                except OSError:
                    pass
            for iguales in por_huella.values():
                if len(iguales) > 1:
                    # Se propone conservar el más antiguo.
                    iguales.sort(key=lambda r: os.path.getmtime(r) if os.path.exists(r) else 0)
                    tam = os.path.getsize(iguales[0])
                    grupos.append({"bytes": tam, "archivos": iguales, "recuperable": tam * (len(iguales) - 1)})
    grupos.sort(key=lambda g: g["recuperable"], reverse=True)
    progreso(fase="Terminado", revisados=revisados, comparados=hechos, total=total)
    return grupos


def anotar_liberado(bytes_liberados, archivos):
    estado = cargar_estado()
    g = estado.setdefault("_duplicados", {})
    t = g.setdefault("totales", {"archivos": 0, "bytes_ordenados": 0, "bytes_liberados": 0,
                                 "por_categoria": {}, "por_accion": {}, "desde": dt.date.today().isoformat()})
    t["archivos"] += archivos
    t["bytes_liberados"] += bytes_liberados
    t["por_accion"]["papelera"] = t["por_accion"].get("papelera", 0) + archivos
    guardar_estado(estado)


# --------------------------------------------------------------------------- copias a disco externo o USB

def unidades_conectadas():
    """[{"letra": "E:", "etiqueta": "MI USB"}] de las unidades montadas (excepto la del sistema)."""
    unidades = []
    if ES_WINDOWS:
        import ctypes
        mascara = ctypes.windll.kernel32.GetLogicalDrives()
        sistema = os.path.splitdrive(os.environ.get("SystemRoot", "C:\\Windows"))[0].upper()
        for i in range(26):
            if not mascara & (1 << i):
                continue
            letra = f"{chr(65 + i)}:"
            if letra == sistema:
                continue
            etiqueta = ctypes.create_unicode_buffer(261)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(letra + "\\", etiqueta, 261,
                                                              None, None, None, None, 0)
            if ok:
                unidades.append({"letra": letra, "etiqueta": etiqueta.value or "(sin nombre)"})
    else:
        for base in ("/media", "/mnt", "/run/media"):
            for raiz, dirs, _ in os.walk(base):
                for d in dirs:
                    ruta = os.path.join(raiz, d)
                    if os.path.ismount(ruta):
                        unidades.append({"letra": ruta, "etiqueta": d})
                if raiz.count(os.sep) >= 3:
                    dirs[:] = []
    return unidades


def _raiz_unidad(letra):
    return letra + "\\" if ES_WINDOWS else letra


def copiar_incremental(origen, destino, cancelado=lambda: False):
    """Copia lo nuevo o cambiado de origen a destino. Nunca borra nada en el destino."""
    copiados, bytes_copiados, errores = 0, 0, []
    for carpeta, subcarpetas, archivos in os.walk(origen):
        if cancelado():
            break
        subcarpetas[:] = [d for d in subcarpetas if not d.startswith((".", "$"))]
        relativa = os.path.relpath(carpeta, origen)
        for nombre in archivos:
            if _ignorado(nombre, IGNORAR_SIEMPRE):
                continue
            a = os.path.join(carpeta, nombre)
            b = os.path.normpath(os.path.join(destino, relativa, nombre))
            try:
                sa = os.stat(a)
                if os.path.exists(b):
                    sb = os.stat(b)
                    if sb.st_size == sa.st_size and abs(sb.st_mtime - sa.st_mtime) < 2:
                        continue
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(a, b)
                copiados += 1
                bytes_copiados += sa.st_size
            except OSError as e:
                errores.append(f"{a}: {e}")
    return copiados, bytes_copiados, errores


def ejecutar_copia(copia):
    """Una copia no se lanza dos veces a la vez, aunque la pidan el motor y el residente."""
    cerrojo = os.path.join(DATOS, f"copia-{re.sub(r'[^a-zA-Z0-9]', '', copia['id'])}.lock")
    try:
        if os.path.exists(cerrojo) and time.time() - os.path.getmtime(cerrojo) > 6 * 3600:
            os.remove(cerrojo)
        os.close(os.open(cerrojo, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return {"ok": False, "mensaje": "Esa copia ya está en marcha."}
    try:
        return _ejecutar_copia(copia)
    finally:
        try:
            os.remove(cerrojo)
        except OSError:
            pass


def _ejecutar_copia(copia):
    unidad = next((u for u in unidades_conectadas() if u["etiqueta"] == copia.get("etiqueta")), None)
    if not unidad:
        return {"ok": False, "mensaje": f'La unidad "{copia.get("etiqueta")}" no está conectada.'}
    raiz = os.path.join(_raiz_unidad(unidad["letra"]), copia.get("subcarpeta") or "GESTOR-copia")
    total, total_bytes, errores = 0, 0, []
    for carpeta in copia.get("carpetas", []):
        if not os.path.isdir(carpeta):
            errores.append(f"{carpeta}: no existe")
            continue
        n, b, e = copiar_incremental(carpeta, os.path.join(raiz, os.path.basename(os.path.normpath(carpeta))))
        total, total_bytes, errores = total + n, total_bytes + b, errores + e
    estado = cargar_estado()
    estado.setdefault("_copias", {})[copia["id"]] = {
        "ultima": dt.datetime.now().isoformat(timespec="seconds"),
        "copiados": total, "bytes": total_bytes, "errores": len(errores), "unidad": unidad["letra"]}
    guardar_estado(estado)
    avisar(f'Copia a {copia.get("etiqueta")}',
           f"{total} archivos copiados ({total_bytes / 1048576:.0f} MB)" + (f", {len(errores)} con error" if errores else ""))
    return {"ok": True, "copiados": total, "bytes": total_bytes, "errores": errores[:50]}


def copias_pendientes(conectadas_antes=None, horas=12):
    """Copias cuya unidad está conectada y que toca hacer: recién conectada, o sin copiar en N horas."""
    etiquetas = {u["etiqueta"] for u in unidades_conectadas()}
    estado = cargar_estado().get("_copias", {})
    pendientes = []
    for copia in cargar_ajustes().get("copias", []):
        if not copia.get("activa", True) or copia.get("etiqueta") not in etiquetas:
            continue
        recien = conectadas_antes is not None and copia["etiqueta"] not in conectadas_antes
        ultima = estado.get(copia["id"], {}).get("ultima")
        vieja = not ultima or dt.datetime.now() - dt.datetime.fromisoformat(ultima) > dt.timedelta(hours=horas)
        if recien or vieja:
            pendientes.append(copia)
    return pendientes, etiquetas


# --------------------------------------------------------------------------- asistente de primer uso

_SUGERENCIAS = [
    # (clave, condición sobre (procedencia, categoría, días), texto, regla)
    ("whatsapp", lambda p, c, d: p == "WhatsApp" and c in ("Imágenes", "Vídeos"),
     "{n} fotos y vídeos de WhatsApp", {"si": {"procedencias": ["WhatsApp"], "categorias": ["Imágenes", "Vídeos"]},
                                       "destino": "{imagenes}\\WhatsApp\\{año}\\{mes}"}),
    ("telegram", lambda p, c, d: p == "Telegram" and c in ("Imágenes", "Vídeos"),
     "{n} fotos y vídeos de Telegram", {"si": {"procedencias": ["Telegram"], "categorias": ["Imágenes", "Vídeos"]},
                                       "destino": "{imagenes}\\Telegram\\{año}\\{mes}"}),
    ("capturas", lambda p, c, d: p == "Captura de pantalla",
     "{n} capturas de pantalla", {"si": {"procedencias": ["Captura de pantalla"]},
                                  "destino": "{imagenes}\\Capturas de pantalla\\{año}"}),
    ("camara", lambda p, c, d: p == "Cámara",
     "{n} fotos y vídeos de cámara o móvil", {"si": {"procedencias": ["Cámara"]},
                                              "destino": "{imagenes}\\Cámara\\{año}\\{mes}"}),
    ("escaner", lambda p, c, d: p == "Escáner",
     "{n} documentos escaneados", {"si": {"procedencias": ["Escáner"]},
                                   "destino": "{documentos}\\Escaneados\\{año}"}),
    ("imagenes", lambda p, c, d: c == "Imágenes", "{n} imágenes más",
     {"si": {"categorias": ["Imágenes"]}, "destino": "{imagenes}\\{año}\\{mes}"}),
    ("documentos", lambda p, c, d: c in ("Documentos", "Hojas de cálculo", "Presentaciones"),
     "{n} documentos, hojas de cálculo y presentaciones",
     {"si": {"categorias": ["Documentos", "Hojas de cálculo", "Presentaciones"]},
      "destino": "{documentos}\\{categoria}\\{año}"}),
    ("instaladores_viejos", lambda p, c, d: c == "Instaladores" and d > 30,
     "{n} instaladores de hace más de un mes (ya no suelen hacer falta)",
     {"si": {"categorias": ["Instaladores"], "antiguedad_mayor_dias": 30}, "accion": "papelera"}),
    ("instaladores", lambda p, c, d: c == "Instaladores", "{n} instaladores recientes",
     {"si": {"categorias": ["Instaladores"]}, "destino": "{origen}\\Instaladores"}),
    ("comprimidos", lambda p, c, d: c == "Comprimidos", "{n} archivos comprimidos",
     {"si": {"categorias": ["Comprimidos"]}, "destino": "{origen}\\Comprimidos"}),
    ("videos", lambda p, c, d: c == "Vídeos", "{n} vídeos", {"si": {"categorias": ["Vídeos"]},
                                                            "destino": "{videos}\\{año}"}),
    ("musica", lambda p, c, d: c == "Música", "{n} canciones y audios", {"si": {"categorias": ["Música"]},
                                                                        "destino": "{musica}"}),
    ("viejos", lambda p, c, d: d > 180, "{n} archivos más sin tocar en 6 meses: archivarlos en ZIP mensuales",
     {"si": {"antiguedad_mayor_dias": 180}, "accion": "archivar", "destino": "{origen}\\Archivados"}),
]


def analizar_carpeta(carpeta, ahora=None):
    """Cuenta lo que hay en una carpeta y propone reglas, de la más concreta a la más general."""
    ahora = ahora or time.time()
    cuentas = {clave: {"n": 0, "bytes": 0} for clave, *_ in _SUGERENCIAS}
    copias, total = 0, 0
    try:
        nombres = os.listdir(carpeta)
    except OSError:
        return {"total": 0, "sugerencias": [], "copias": 0}
    for nombre in nombres:
        ruta = os.path.join(carpeta, nombre)
        if not os.path.isfile(ruta) or _ignorado(nombre, IGNORAR_SIEMPRE):
            continue
        st = os.stat(ruta)
        total += 1
        base = os.path.splitext(nombre)[0]
        if limpiar_nombre(base) != base:
            copias += 1
        proc = procedencia_de(ruta)["procedencia"]
        cat = categoria_de(os.path.splitext(nombre)[1].lower())
        dias = (ahora - st.st_mtime) / 86400
        for clave, condicion, *_ in _SUGERENCIAS:
            if condicion(proc, cat, dias):
                cuentas[clave]["n"] += 1
                cuentas[clave]["bytes"] += st.st_size
                break
    rutas = {"{imagenes}": carpeta_conocida("Imágenes"), "{documentos}": carpeta_conocida("Documentos"),
             "{videos}": carpeta_conocida("Vídeos"), "{musica}": carpeta_conocida("Música")}
    sugerencias = []
    for clave, _, texto, plantilla in _SUGERENCIAS:
        n = cuentas[clave]["n"]
        if not n:
            continue
        regla = {"id": nuevo_id(), "si": dict(plantilla["si"]), "accion": plantilla.get("accion", "mover"),
                 "destino": plantilla.get("destino", ""), "fecha": "modificacion", "nuevo_nombre": ""}
        for k, v in rutas.items():
            regla["destino"] = regla["destino"].replace(k, v)
        if os.sep != "\\":
            regla["destino"] = regla["destino"].replace("\\", os.sep)
        sugerencias.append({"clave": clave, "texto": texto.format(n=n), "n": n,
                            "bytes": cuentas[clave]["bytes"], "regla": regla})
    return {"total": total, "sugerencias": sugerencias, "copias": copias}


def crear_desde_asistente(carpeta, reglas, limpiar=False):
    servicio = {
        "id": nuevo_id(), "nombre": f"Ordenar {os.path.basename(os.path.normpath(carpeta)) or carpeta}",
        "activo": False, "origenes": [carpeta], "subcarpetas": False,
        "horario": {"tipo": "intervalo", "cada": 8, "unidad": "horas"},
        "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
        "limpiar_nombres": bool(limpiar), "fecha_al_inicio": False, "borrar_carpetas_vacias": False,
        "esperar_minutos": 10, "ignorar": [], "reglas": reglas,
    }
    servicios = cargar_servicios()
    servicios.append(servicio)
    guardar_servicios(servicios)
    return servicio


# --------------------------------------------------------------------------- avisos (notificaciones)

def avisar(titulo, texto):
    """Deja un aviso que el icono de la bandeja muestra como notificación de Windows."""
    if not cargar_ajustes().get("notificaciones", True):
        return
    try:
        with open(ARCHIVO_AVISOS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"titulo": titulo, "texto": texto, "t": time.time()}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def leer_avisos_desde(posicion):
    """Devuelve (avisos nuevos, nueva posición) del archivo de avisos."""
    try:
        tam = os.path.getsize(ARCHIVO_AVISOS)
        if tam < posicion:
            posicion = 0
        if tam > 1_000_000:  # se vacía de vez en cuando
            open(ARCHIVO_AVISOS, "w").close()
            return [], 0
        with open(ARCHIVO_AVISOS, "r", encoding="utf-8") as f:
            f.seek(posicion)
            lineas = f.read()
            posicion = f.tell()
        return [json.loads(l) for l in lineas.splitlines() if l.strip()], posicion
    except (OSError, ValueError):
        return [], posicion


# --------------------------------------------------------------------------- proceso residente

def residente_activo():
    import socket
    try:
        with socket.create_connection(("127.0.0.1", PUERTO_RESIDENTE), timeout=0.5):
            return True
    except OSError:
        return False


def necesita_residente():
    ajustes = cargar_ajustes()
    if ajustes.get("icono_bandeja", True) and ES_WINDOWS:
        return True
    return any(s.get("activo") and (s.get("horario") or {}).get("tipo") == "instante"
               for s in cargar_servicios())


def lanzar_residente():
    """Arranca el proceso residente (icono y modo al instante) si hace falta y no está ya en marcha."""
    if residente_activo() or not necesita_residente():
        return False
    import subprocess
    if EMPAQUETADO:
        comando = [sys.executable, "--residente"]
    else:
        comando = [_pythonw(), os.path.join(BASE, "gestor.py"), "--residente"]
    flags = 0x00000008 | 0x00000200 | 0x08000000 if ES_WINDOWS else 0  # sin ventana y desligado
    subprocess.Popen(comando, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


# --------------------------------------------------------------------------- Programador de tareas

NOMBRE_TAREA = "GESTOR\\Motor"


def _pythonw():
    candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidato if os.path.exists(candidato) else sys.executable


def _archivo_inicio():
    carpeta = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup")
    return os.path.join(carpeta, "GESTOR-inicio.vbs")


def _comando_motor(extra=""):
    """Comando que lanza el motor sin ventana: el .exe empaquetado o pythonw + gestor.py."""
    if EMPAQUETADO:
        return f'"{sys.executable}" --motor{extra}'
    return f'"{_pythonw()}" "{os.path.join(BASE, "gestor.py")}" --motor{extra}'


def programar_motor(minutos):
    """Crea (o actualiza) la tarea que lanza el motor cada N minutos, y el arranque al iniciar sesión."""
    if not ES_WINDOWS:
        return {"ok": False, "mensaje": "Solo disponible en Windows."}
    import subprocess
    comando = _comando_motor()
    r = subprocess.run(["schtasks", "/Create", "/F", "/TN", NOMBRE_TAREA, "/SC", "MINUTE",
                        "/MO", str(int(minutos)), "/TR", comando],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode != 0:
        return {"ok": False, "mensaje": (r.stderr or r.stdout).strip()}
    with open(_archivo_inicio(), "w", encoding="utf-8") as f:
        orden = _comando_motor(" --inicio").replace('"', '""')
        f.write(f'CreateObject("WScript.Shell").Run "{orden}", 0, False\n')
    lanzar_residente()
    return {"ok": True, "mensaje": f"El motor se revisará cada {int(minutos)} minutos."}


def estado_programacion():
    if not ES_WINDOWS:
        return {"instalada": False, "mensaje": "Solo disponible en Windows."}
    import subprocess
    r = subprocess.run(["schtasks", "/Query", "/TN", NOMBRE_TAREA], capture_output=True,
                       text=True, creationflags=0x08000000)
    return {"instalada": r.returncode == 0}


def quitar_programacion():
    if not ES_WINDOWS:
        return {"ok": False, "mensaje": "Solo disponible en Windows."}
    import subprocess
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", NOMBRE_TAREA], capture_output=True,
                   creationflags=0x08000000)
    try:
        os.remove(_archivo_inicio())
    except OSError:
        pass
    return {"ok": True, "mensaje": "Programación quitada."}
