"""GESTOR: lógica común del panel y del motor.

Solo usa la biblioteca estándar de Python. Si Pillow está instalado se usa
para leer la fecha de captura de más formatos de foto; si no, se usa un lector
propio que entiende JPEG.
"""

import calendar
import datetime as dt
import fnmatch
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
IGNORAR_SIEMPRE = ["*.crdownload", "*.part", "*.partial", "*.tmp", "*.download", "~$*",
                   "desktop.ini", "thumbs.db", ".ds_store", "*.lnk", "*.url"]

MESES = ["", "01-Enero", "02-Febrero", "03-Marzo", "04-Abril", "05-Mayo", "06-Junio", "07-Julio",
         "08-Agosto", "09-Septiembre", "10-Octubre", "11-Noviembre", "12-Diciembre"]

AJUSTES_POR_DEFECTO = {"revisar_cada_minutos": 5}


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
            "conflicto": "renombrar", "identicos": "papelera",
            "esperar_minutos": 10, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "{año}", "{mes}"), "captura"),
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
            "conflicto": "renombrar", "identicos": "papelera",
            "esperar_minutos": 30, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "{año}", "{mes}"), "captura"),
                regla("Documentos", os.path.join(documentos, "{categoria}", "{año}")),
                regla("Hojas de cálculo", os.path.join(documentos, "{categoria}", "{año}")),
                regla("Presentaciones", os.path.join(documentos, "{categoria}", "{año}")),
            ],
        },
        {
            "id": nuevo_id(), "nombre": "Ordenar Escritorio", "activo": False,
            "origenes": [escritorio], "subcarpetas": False, "horario": dict(horario),
            "conflicto": "renombrar", "identicos": "papelera",
            "esperar_minutos": 60, "ignorar": [],
            "reglas": [
                regla("Imágenes", os.path.join(imagenes, "Escritorio", "{año}", "{mes}"), "captura"),
                {"id": nuevo_id(), "si": {"antiguedad_mayor_dias": 7}, "accion": "mover",
                 "destino": os.path.join(documentos, "Escritorio", "{año}-{mes_num}"),
                 "fecha": "modificacion", "nuevo_nombre": ""},
            ],
        },
    ]


# --------------------------------------------------------------------------- fechas

def _exif_jpeg(ruta):
    """Lee DateTimeOriginal de un JPEG sin librerías externas."""
    with open(ruta, "rb") as f:
        if f.read(2) != b"\xff\xd8":
            return None
        while True:
            marca = f.read(2)
            if len(marca) < 2 or marca[0] != 0xFF:
                return None
            if marca[1] in (0xD9, 0xDA):
                return None
            largo = struct.unpack(">H", f.read(2))[0]
            datos = f.read(largo - 2)
            if marca[1] == 0xE1 and datos[:6] == b"Exif\x00\x00":
                return _exif_tiff(datos[6:])


def _exif_tiff(t):
    if len(t) < 8:
        return None
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
        return crudo.split(b"\x00")[0].decode("ascii", "ignore")

    principal = ifd(struct.unpack(orden + "I", t[4:8])[0])
    candidatos = []
    if 0x8769 in principal:
        exif = ifd(struct.unpack(orden + "I", principal[0x8769][2])[0])
        for etiqueta in (0x9003, 0x9004):
            if etiqueta in exif:
                candidatos.append(texto(exif[etiqueta]))
    if 0x0132 in principal:
        candidatos.append(texto(principal[0x0132]))
    for c in candidatos:
        fecha = _parsear_fecha_exif(c)
        if fecha:
            return fecha
    return None


def _parsear_fecha_exif(valor):
    if not valor:
        return None
    try:
        return dt.datetime.strptime(valor.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def fecha_captura(ruta):
    try:
        from PIL import Image  # opcional
        try:
            import pillow_heif  # opcional, para .heic
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        with Image.open(ruta) as img:
            exif = img.getexif()
            valor = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
            fecha = _parsear_fecha_exif(valor)
            if fecha:
                return fecha
    except Exception:
        pass
    if os.path.splitext(ruta)[1].lower() in (".jpg", ".jpeg"):
        try:
            return _exif_jpeg(ruta)
        except (OSError, struct.error, ValueError):
            return None
    return None


def fecha_archivo(ruta, st, fuente):
    if fuente == "captura":
        fecha = fecha_captura(ruta)
        if fecha:
            return fecha
    if fuente == "creacion":
        return dt.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_ctime if ES_WINDOWS else st.st_mtime))
    return dt.datetime.fromtimestamp(st.st_mtime)


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
    return True


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


# --------------------------------------------------------------------------- ejecutar un servicio

def planificar(servicio, ahora=None):
    """Lista de operaciones que haría el servicio, sin tocar nada."""
    ahora = ahora or time.time()
    ignorar = IGNORAR_SIEMPRE + [p for p in servicio.get("ignorar", []) if p]
    esperar = float(servicio.get("esperar_minutos") or 0) * 60
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


def _operacion(regla, ruta, st, origen, servicio, destinos_previstos):
    accion = regla.get("accion", "mover")
    if accion == "papelera":
        return {"accion": "papelera", "origen": ruta, "destino": "", "regla": regla.get("id")}
    fecha = fecha_archivo(ruta, st, regla.get("fecha", "modificacion"))
    nombre = os.path.basename(ruta)
    if regla.get("nuevo_nombre"):
        extension = os.path.splitext(nombre)[1]
        nombre = _limpiar_nombre(expandir(regla["nuevo_nombre"], ruta, origen, fecha)) + extension
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
    if os.path.exists(destino) and servicio.get("identicos", "papelera") == "papelera":
        gemelo = _copia_identica(ruta, st, destino)
        if gemelo:
            if accion == "copiar":
                return None  # la copia ya está en el destino
            return {"accion": "papelera", "origen": ruta, "destino": "", "regla": regla.get("id"),
                    "identico_a": gemelo}
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
    return {"accion": accion, "origen": ruta, "destino": destino, "regla": regla.get("id")}


def aplicar(op):
    accion, origen, destino = op["accion"], op["origen"], op["destino"]
    if accion == "papelera":
        a_papelera(origen)
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


def ejecutar_servicio(servicio, simular=False):
    plan, avisos = planificar(servicio)
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
    if hechas or errores:
        guardar_registro(registro)
    return registro


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
                    a_papelera(op["destino"])
                else:
                    raise OSError("estaba en la papelera de reciclaje: restáuralo desde ahí")
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
    if tipo in ("manual", "inicio"):
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


def ejecutar_y_anotar(servicio, motivo="manual"):
    with Bloqueo():
        registro = ejecutar_servicio(servicio)
        estado = cargar_estado()
        e = estado.setdefault(servicio["id"], {})
        e["ultima"] = dt.datetime.now().isoformat(timespec="seconds")
        e["ultimo_resultado"] = {"movidos": len(registro["operaciones"]),
                                 "errores": len(registro["errores"]), "motivo": motivo}
        guardar_estado(estado)
        return registro


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
