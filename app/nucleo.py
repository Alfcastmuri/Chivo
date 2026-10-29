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

VERSION = "0.7.1"
ES_WINDOWS = os.name == "nt"
EMPAQUETADO = getattr(sys, "frozen", False)  # convertido en .exe con PyInstaller

# BASE: donde está el programa. DATOS: donde se guarda tu configuración y el historial.
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATOS = os.environ.get("GESTOR_DATOS") or (
    os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GESTOR") if ES_WINDOWS
    else os.path.join(os.path.expanduser("~"), ".gestor"))
os.makedirs(DATOS, exist_ok=True)

import bd  # noqa: E402  (necesita DATOS)
bd.iniciar(DATOS)

ARCHIVO_SERVICIOS = os.path.join(DATOS, "servicios.json")
ARCHIVO_ESTADO = os.path.join(DATOS, "estado.json")
ARCHIVO_AJUSTES = os.path.join(DATOS, "ajustes.json")
ARCHIVO_BLOQUEO = os.path.join(DATOS, "motor.lock")
ARCHIVO_ERRORES = os.path.join(DATOS, "errores.log")
ARCHIVO_AVISOS = os.path.join(DATOS, "avisos.jsonl")
CARPETA_REGISTRO = os.path.join(DATOS, "registro")
MAX_REGISTROS_POR_SERVICIO = 1000

# Tipos de archivo por extensión. Cada extensión pertenece a un solo tipo. Se pueden añadir más
# (o cambiar el tipo de una) en el panel: Personalizar → Tipos de archivo (ajuste "extensiones_propias").
CATEGORIAS = {
    "Imágenes": [".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".gif", ".bmp", ".dib", ".webp", ".heic", ".heif",
                 ".avif", ".jxl", ".jp2", ".j2k", ".tif", ".tiff", ".svg", ".svgz", ".ico", ".icns", ".cur", ".tga",
                 ".pcx", ".ppm", ".pgm", ".pbm", ".pnm", ".exr", ".hdr", ".dds", ".emf", ".wmf", ".raw", ".cr2", ".cr3",
                 ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw", ".x3f",
                 ".3fr", ".erf", ".kdc", ".mrw", ".dcr", ".mef", ".mos", ".iiq", ".rwl"],
    "Vídeos": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".f4v", ".webm", ".m4v", ".3gp", ".3g2", ".mpg", ".mpeg",
               ".m2v", ".mpe", ".m2ts", ".mts", ".vob", ".ogv", ".rm", ".rmvb", ".asf", ".divx", ".xvid", ".mxf", ".dv",
               ".insv", ".lrv", ".h264", ".h265", ".hevc", ".swf", ".qt", ".yuv"],
    "Música": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".m4a", ".m4b", ".m4r", ".wma", ".opus", ".aiff", ".aif",
               ".aifc", ".alac", ".ape", ".wv", ".mka", ".mid", ".midi", ".kar", ".amr", ".ac3", ".dts", ".caf", ".ra",
               ".au", ".snd", ".dsf", ".dff", ".mpc", ".tta", ".spx", ".weba", ".mod", ".xm", ".it", ".s3m"],
    "Documentos": [".pdf", ".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".odt", ".ott", ".fodt", ".rtf", ".txt",
                   ".md", ".markdown", ".rst", ".tex", ".pages", ".wpd", ".wps", ".xps", ".oxps", ".hwp", ".abw", ".sxw",
                   ".nfo", ".log", ".one", ".onepkg", ".gdoc", ".vsd", ".vsdx", ".pub", ".mpp", ".odg", ".ofd"],
    "Hojas de cálculo": [".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm", ".ods", ".ots", ".fods", ".csv",
                         ".tsv", ".numbers", ".dif", ".slk", ".gsheet", ".qif", ".ofx", ".xlr"],
    "Presentaciones": [".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".ppsm", ".pot", ".potx", ".potm", ".odp", ".otp",
                       ".fodp", ".key", ".sxi", ".gslides", ".prezi"],
    "Comprimidos": [".zip", ".zipx", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".zst", ".lz",
                    ".lzma", ".lz4", ".z", ".cab", ".arj", ".lzh", ".lha", ".ace", ".sit", ".sitx", ".iso", ".wim",
                    ".cpio", ".ar", ".r00", ".001", ".pea", ".uue"],
    "Instaladores": [".exe", ".msi", ".msp", ".msu", ".msix", ".msixbundle", ".appx", ".appxbundle", ".appinstaller",
                     ".bat", ".cmd", ".com", ".scr", ".apk", ".xapk", ".apkm", ".aab", ".ipa", ".deb", ".rpm", ".pkg",
                     ".dmg", ".mpkg", ".appimage", ".flatpak", ".snap", ".run", ".vsix", ".crx", ".xpi", ".oxt"],
    "Código": [".py", ".pyw", ".pyi", ".ipynb", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html",
               ".htm", ".xhtml", ".css", ".scss", ".sass", ".less", ".json", ".jsonc", ".json5", ".xml", ".xsl", ".xsd",
               ".java", ".class", ".jar", ".war", ".kt", ".kts", ".scala", ".groovy", ".gradle", ".c", ".h", ".cpp",
               ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".cs", ".csproj", ".sln", ".vcxproj", ".xaml", ".razor", ".cshtml",
               ".vb", ".vbs", ".fs", ".fsx", ".go", ".rs", ".rb", ".erb", ".php", ".phtml", ".swift", ".m", ".mm",
               ".dart", ".lua", ".pl", ".pm", ".r", ".rmd", ".jl", ".sql", ".ps1", ".psm1", ".psd1", ".sh", ".bash",
               ".zsh", ".fish", ".asm", ".s", ".hs", ".elm", ".ex", ".exs", ".erl", ".clj", ".cljs", ".nim", ".zig",
               ".sol", ".tf", ".hcl", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties", ".reg",
               ".proto", ".graphql", ".gql", ".cmake", ".mk", ".dockerfile", ".patch", ".diff", ".lock", ".jsp",
               ".asp", ".aspx", ".twig", ".liquid", ".ahk", ".au3", ".applescript", ".vba", ".bas", ".pas", ".f90",
               ".for", ".cob", ".ada", ".d", ".v", ".sv", ".ino", ".pde", ".gd", ".shader", ".glsl", ".hlsl"],
    "Accesos directos": [".lnk", ".url", ".webloc", ".desktop", ".website"],
    "Diseño": [".psd", ".psb", ".ai", ".ait", ".eps", ".indd", ".indt", ".idml", ".xd", ".fig", ".sketch", ".cdr",
               ".afdesign", ".afphoto", ".afpub", ".xcf", ".kra", ".clip", ".procreate", ".pxm", ".pdn", ".ase",
               ".aco", ".abr", ".atn", ".cpt", ".sai", ".qxp", ".fla", ".ora", ".lrcat", ".xmp", ".cube", ".3dl"],
    "3D y CAD": [".stl", ".obj", ".mtl", ".fbx", ".blend", ".dae", ".3ds", ".max", ".ma", ".mb", ".c4d", ".gltf", ".glb",
                 ".3mf", ".usd", ".usdz", ".ply", ".x3d", ".dwg", ".dxf", ".dwf", ".dgn", ".step", ".stp", ".iges", ".igs",
                 ".skp", ".sldprt", ".sldasm", ".slddrw", ".ipt", ".iam", ".idw", ".f3d", ".rvt", ".rfa", ".ifc", ".3dm",
                 ".catpart", ".prt", ".gcode", ".ufp", ".lys", ".chitubox", ".scad", ".fcstd", ".ztl", ".spp"],
    "Fuentes": [".ttf", ".otf", ".ttc", ".woff", ".woff2", ".eot", ".fon", ".fnt", ".pfb", ".pfm", ".afm", ".bdf",
                ".pcf", ".sfd", ".dfont"],
    "Libros y cómics": [".epub", ".mobi", ".azw", ".azw3", ".kfx", ".fb2", ".djvu", ".djv", ".cbz", ".cbr", ".cb7",
                        ".cbt", ".ibooks", ".lit", ".lrf", ".pdb", ".prc", ".acsm"],
    "Correo y contactos": [".eml", ".emlx", ".msg", ".oft", ".pst", ".ost", ".mbox", ".mbx", ".vcf", ".vcard", ".ics",
                           ".ical", ".vcs", ".nws", ".olm"],
    "Bases de datos": [".db", ".db3", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".accde", ".dbf", ".sdf", ".frm",
                       ".ibd", ".myd", ".myi", ".ndf", ".mdf", ".ldf", ".kdbx", ".kdb", ".realm", ".fdb", ".gdb",
                       ".odb", ".nsf", ".fp7", ".fmp12"],
    "Subtítulos": [".srt", ".vtt", ".ass", ".ssa", ".sub", ".sbv", ".idx", ".smi", ".sami", ".ttml", ".dfxp", ".lrc"],
    "Discos virtuales": [".vmdk", ".vdi", ".vhdx", ".ova", ".ovf", ".qcow2", ".qcow", ".img", ".hdd", ".pvm", ".vmx",
                         ".vbox", ".avhdx", ".vhd", ".nrg", ".mds", ".bin", ".cue", ".ccd", ".toast", ".dsk"],
    "Proyectos de audio y vídeo": [".prproj", ".aep", ".aet", ".drp", ".veg", ".kdenlive", ".mlt", ".wfp", ".camproj",
                                   ".tscproj", ".fcpbundle", ".imovieproj", ".als", ".alp", ".flp", ".logicx", ".ptx",
                                   ".aup", ".aup3", ".band", ".cpr", ".rpp", ".sesx", ".omf", ".aaf", ".edl", ".mogrt"],
    "Certificados y firmas": [".cer", ".crt", ".pem", ".der", ".pfx", ".p12", ".p7b", ".p7c", ".p7s", ".csr", ".req",
                              ".sig", ".asc", ".gpg", ".pgp", ".ppk", ".jks", ".keystore"],
    "Mapas y GPS": [".gpx", ".kml", ".kmz", ".geojson", ".shp", ".shx", ".fit", ".tcx", ".osm", ".mbtiles",
                    ".gpkg", ".qgs", ".qgz"],
    "Torrents": [".torrent", ".magnet", ".metalink", ".nzb"],
    "Sistema": [".dll", ".sys", ".drv", ".ocx", ".cpl", ".msc", ".efi", ".inf", ".cat", ".mui", ".tlb", ".so", ".dylib",
                ".ko", ".dat", ".tmp", ".temp", ".bak", ".old", ".dmp", ".etl", ".evtx", ".pf", ".blf", ".regtrans-ms"],
}

# Archivos que ningún servicio toca: descargas a medias, accesos directos, archivos del sistema.
IGNORAR_SIEMPRE = ["archivo ????-??.zip", "*.crdownload", "*.part", "*.partial", "*.tmp", "*.download", "~$*",
                   "desktop.ini", "thumbs.db", ".ds_store", "*.lnk", "*.url"]

MESES = ["", "01-Enero", "02-Febrero", "03-Marzo", "04-Abril", "05-Mayo", "06-Junio", "07-Julio",
         "08-Agosto", "09-Septiembre", "10-Octubre", "11-Noviembre", "12-Diciembre"]

AJUSTES_POR_DEFECTO = {"revisar_cada_minutos": 5, "pausado": False, "notificaciones": True,
                       "icono_bandeja": True, "papelera": "gestor", "retencion_dias": 30, "copias": [],
                       "mis_rfc": "", "umbral_disco": 10, "aviso_semanal": True, "renombrar_facturas": True,
                       "no_molestar": {"bateria": True, "pantalla_completa": True,
                                       "horas": False, "desde": "22:00", "hasta": "07:00"}}
ARCHIVO_DETENER = os.path.join(DATOS, "detener.json")  # pide a otros procesos de GESTOR que se cierren
ARCHIVO_PID_RESIDENTE = os.path.join(DATOS, "residente.pid")
ARCHIVO_SISTEMA = os.path.join(DATOS, "sistema.json")  # avisos de disco, resumen semanal
ARCHIVO_INDICE = os.path.join(DATOS, "indice.jsonl")   # a dónde fue cada archivo, para el buscador
MAX_INDICE = 20 * 1024 * 1024
ARCHIVO_PAPELERA = os.path.join(DATOS, "papelera.json")
PUERTO_RESIDENTE = int(os.environ.get("GESTOR_PUERTO_RESIDENTE", "8766"))
MAX_HECHOS = 5000


# --------------------------------------------------------------------------- archivos JSON

def _en_bd(ruta):
    """Los .json de la carpeta de datos viven en la base de datos (gestor.db). La contraseña no: se
    queda en credenciales.json para poder borrarla si se olvida."""
    return ruta.endswith(".json") and os.path.basename(ruta) != "credenciales.json" \
        and _norm(os.path.dirname(ruta)) == _norm(DATOS)


def leer_json(ruta, por_defecto):
    if _en_bd(ruta):
        return bd.leer(os.path.basename(ruta), por_defecto, archivo=ruta)
    for _ in range(10):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return por_defecto
        except PermissionError:  # Windows o el antivirus lo tienen abierto: se espera un poco
            time.sleep(0.3)
        except (OSError, ValueError):
            return por_defecto
    return por_defecto


def escribir_json(ruta, datos):
    if _en_bd(ruta):
        bd.escribir(os.path.basename(ruta), datos)
        return
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ruta)


def existe_json(ruta):
    return bd.existe(os.path.basename(ruta), archivo=ruta) if _en_bd(ruta) else os.path.exists(ruta)


def borrar_json(ruta):
    if _en_bd(ruta):
        bd.borrar(os.path.basename(ruta))
    try:
        os.remove(ruta)
    except OSError:
        pass


def cargar_servicios():
    if not existe_json(ARCHIVO_SERVICIOS):
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


class _Estado(dict):
    """El estado tal como se leyó: al guardar solo se escriben las partes que cambiaron, así dos
    procesos (panel y motor) que guardan a la vez no se borran lo que el otro anotó."""
    visto = None


def cargar_estado():
    grupo = bd.leer_grupo("estado")
    if not grupo:
        antiguo = bd.leer("estado.json", None, archivo=ARCHIVO_ESTADO)
        if isinstance(antiguo, dict) and antiguo:
            bd.escribir_grupo("estado", antiguo)
            bd.borrar("estado.json")
            grupo = antiguo
    e = _Estado(grupo)
    e.visto = {k: json.dumps(v, sort_keys=True, ensure_ascii=False) for k, v in grupo.items()}
    return e


def guardar_estado(estado):
    visto = getattr(estado, "visto", None) or {}
    cambios = {k: v for k, v in estado.items() if visto.get(k) != json.dumps(v, sort_keys=True, ensure_ascii=False)}
    quitar = [k for k in visto if k not in estado] if isinstance(estado, _Estado) else []
    bd.escribir_grupo("estado", cambios, quitar)
    if isinstance(estado, _Estado):
        estado.visto = {k: json.dumps(v, sort_keys=True, ensure_ascii=False) for k, v in estado.items()}


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


def sin_tocar_acceso(funcion):
    """Lo que GESTOR lee (contenido, EXIF, huellas) no cuenta como "usar" el archivo: se restaura su
    último acceso, para que "sin usar en N días" no se reinicie solo porque GESTOR lo miró."""
    @functools.wraps(funcion)
    def envoltura(ruta, *args, **kwargs):
        try:
            antes = os.stat(ruta)
        except OSError:
            return funcion(ruta, *args, **kwargs)
        try:
            return funcion(ruta, *args, **kwargs)
        finally:
            try:
                despues = os.stat(ruta)
                if despues.st_atime_ns != antes.st_atime_ns and despues.st_mtime_ns == antes.st_mtime_ns:
                    os.utime(ruta, ns=(antes.st_atime_ns, antes.st_mtime_ns))
            except OSError:
                pass
    return envoltura


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
@sin_tocar_acceso
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


_FECHA_EN_NOMBRE = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)")


def fecha_en_nombre(ruta):
    """Fecha escrita en el nombre: IMG-20231005-WA0012, Screenshot_20231005-1012, PXL_20231005..."""
    m = _FECHA_EN_NOMBRE.search(os.path.basename(ruta))
    if not m:
        return None
    try:
        return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fecha_archivo(ruta, st, fuente):
    if fuente == "captura":
        # WhatsApp y las capturas no llevan EXIF, pero sí la fecha en el nombre.
        fecha = fecha_captura(ruta) or fecha_en_nombre(ruta)
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
@sin_tocar_acceso
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
    """Texto de un PDF (primeras páginas), DOCX o archivo de texto. Vacío si no se puede leer.

    Las fotos y los PDF escaneados se leen con el OCR de Windows (ver ocr.py)."""
    extension = os.path.splitext(ruta)[1].lower()
    if extension not in EXT_CON_TEXTO:
        if ES_WINDOWS:
            import ocr
            if extension in ocr.EXT_IMAGEN and ocr.activo():
                return ocr.texto(ruta)
        return ""
    try:
        texto = _texto(ruta, os.path.getmtime(ruta))
    except OSError:
        return ""
    if extension == ".pdf" and ES_WINDOWS and len(texto.strip()) < 40:
        import ocr
        if ocr.activo():
            return ocr.texto(ruta) or texto
    return texto


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
    # Varias palabras separadas por coma: tienen que aparecer todas. Con "|", basta una.
    texto = sin_acentos(texto.lower())
    for grupo in valor.split(","):
        opciones = [sin_acentos(p.strip().lower()) for p in grupo.split("|") if p.strip()]
        if opciones and not any(o in texto for o in opciones):
            return False
    return True


def dato_de_regla(regla, ruta):
    """El dato que captura la expresión regular de contenido de la regla: el grupo "dato" o el primero."""
    c = (regla or {}).get("si") or {}
    if c.get("contenido_modo") != "regex" or not c.get("contenido_valor"):
        return None
    try:
        m = re.search(c["contenido_valor"], texto_de(ruta), re.IGNORECASE)
    except re.error:
        return None
    if not m:
        return None
    if "dato" in m.groupdict():
        return (m.group("dato") or "").strip() or None
    return (m.group(1) if m.groups() else m.group(0)).strip() or None


# --------------------------------------------------------------------------- facturas (CFDI de México)

_RFC = re.compile(r"\b([A-ZÑ&]{3,4})-?(\d{6})-?([A-Z\d]{3})\b")
_PROVEEDOR = [
    re.compile(r"(?:nombre|raz[oó]n social)\s*(?:del\s+)?emisor\s*[:\-]?\s*([^\n]{3,80})", re.IGNORECASE),
    re.compile(r"emisor\s*[:\-]\s*([^\n]{3,80})", re.IGNORECASE),
    re.compile(r"(?:nombre|raz[oó]n social)\s*[:\-]\s*([^\n]{3,80})", re.IGNORECASE),
]
_PALABRAS_FACTURA = ("folio fiscal", "cfdi", "comprobante fiscal", "factura")


def sin_acentos(texto):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


@sin_tocar_acceso
def _cfdi_xml(ruta):
    import xml.etree.ElementTree as ET
    try:
        raiz = ET.parse(ruta).getroot()
    except (ET.ParseError, OSError):
        return None
    if not raiz.tag.endswith("Comprobante"):
        return None
    emisor = next((e for e in raiz if e.tag.endswith("Emisor")), None)
    receptor = next((e for e in raiz if e.tag.endswith("Receptor")), None)
    return {"es_factura": True,
            "rfc": (emisor.get("Rfc") or emisor.get("rfc") or "") if emisor is not None else "",
            "proveedor": (emisor.get("Nombre") or emisor.get("nombre") or "") if emisor is not None else "",
            "rfc_receptor": (receptor.get("Rfc") or "") if receptor is not None else "",
            "fecha": raiz.get("Fecha") or raiz.get("fecha") or "",
            "total": raiz.get("Total") or raiz.get("total") or "",
            "folio": ((raiz.get("Serie") or "") + (raiz.get("Folio") or "")).strip()}


@functools.lru_cache(maxsize=1024)
def _datos_factura(ruta, _mtime, mis_rfc):
    extension = os.path.splitext(ruta)[1].lower()
    vacio = {"es_factura": False, "rfc": "", "proveedor": "", "rfc_receptor": "", "fecha": "", "total": "", "folio": ""}
    if extension == ".xml":
        return _cfdi_xml(ruta) or vacio
    if extension not in (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
        return vacio  # las fotos de recibos solo tienen texto si el OCR de Windows está activo
    # El PDF de una factura suele ir acompañado de su XML con el mismo nombre.
    for ext in (".xml", ".XML"):
        gemelo = os.path.splitext(ruta)[0] + ext
        if os.path.exists(gemelo):
            datos = _cfdi_xml(gemelo)
            if datos:
                return datos
    texto = texto_de(ruta)
    plano = sin_acentos(texto.lower())
    if not any(p in plano for p in _PALABRAS_FACTURA):
        return vacio
    rfcs = ["".join(m.groups()) for m in _RFC.finditer(texto.upper())]
    ajenos = [r for r in rfcs if r not in mis_rfc]
    proveedor = ""
    for patron in _PROVEEDOR:
        m = patron.search(texto)
        if m:
            proveedor = re.split(r"\s{2,}|\bRFC\b", m.group(1).strip(), flags=re.IGNORECASE)[0].strip(" :-,")
            if proveedor:
                break
    totales = _TOTAL.findall(texto)
    fecha = _FECHA_FACTURA.search(texto)
    return {"es_factura": True, "rfc": ajenos[0] if ajenos else (rfcs[0] if rfcs else ""),
            "proveedor": proveedor, "rfc_receptor": "",
            "fecha": fecha.group(1) if fecha else "",
            "total": totales[-1].replace(",", "") if totales else "", "folio": ""}


_TOTAL = re.compile(r"\btotal\b(?!\s*(?:de\s+)?(?:impuestos|trasladados|retenidos|art))[^\d\n]{0,25}\$?\s*([\d,]+\.\d{2})",
                    re.IGNORECASE)
_FECHA_FACTURA = re.compile(r"(?:fecha\s*(?:y\s*hora\s*)?de\s*emisi[oó]n|fecha)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

# Nombres cortos de emisores frecuentes, para nombres de archivo legibles.
_PROVEEDORES_CORTOS = {
    "comision federal de electricidad": "CFE", "telefonos de mexico": "Telmex", "radiomovil dipsa": "Telcel",
    "servicio de administracion tributaria": "SAT", "instituto mexicano del seguro social": "IMSS",
    "cadena comercial oxxo": "OXXO", "nueva wal mart de mexico": "Walmart", "costco de mexico": "Costco",
    "amazon": "Amazon", "mercado libre": "Mercado Libre", "uber": "Uber", "didi": "DiDi",
    "cablevision red": "izzi", "total play telecomunicaciones": "Totalplay", "tiendas soriana": "Soriana",
    "tiendas chedraui": "Chedraui", "home depot mexico": "Home Depot", "liverpool": "Liverpool",
    "naturgy": "Naturgy", "gas natural": "Naturgy", "pemex": "Pemex", "at&t": "AT&T",
}
_SOCIEDADES = re.compile(r"[,.]?\s*\b(s\.?\s*a\.?\s*p?\.?\s*i?\.?(\s*de\s*c\.?\s*v\.?)?|s\.?\s*de\s*r\.?\s*l\.?(\s*de\s*c\.?\s*v\.?)?|"
                         r"s\.?\s*c\.?|a\.?\s*c\.?|s\.?\s*a\.?\s*b\.?(\s*de\s*c\.?\s*v\.?)?)\s*$", re.IGNORECASE)


def proveedor_corto(nombre):
    """"COMISION FEDERAL DE ELECTRICIDAD" → "CFE"; "PAPELERIA LOPEZ SA DE CV" → "Papeleria Lopez"."""
    n = re.sub(r"\s+", " ", nombre or "").strip()
    plano = sin_acentos(n.lower())
    for clave, corto in _PROVEEDORES_CORTOS.items():
        if clave in plano:
            return corto
    n = _SOCIEDADES.sub("", n).strip(" ,.")
    palabras = n.split()
    if n.isupper():
        palabras = [p if len(p) <= 3 and p.isalpha() and p not in ("DE", "DEL", "LA", "LOS", "Y") else p.title()
                    for p in palabras]
    palabras = palabras[:3]
    while len(palabras) > 1 and sin_acentos(palabras[-1].lower()) in ("de", "del", "la", "las", "los", "y", "e"):
        palabras.pop()
    return " ".join(palabras)


NOMBRE_FACTURA = "{fecha_factura} {proveedor_corto} {total}"


def nombre_factura(ruta, origen, fecha, regla=None):
    """"2026-10 CFE $1,234.50" con los datos de la factura, o None si no hay datos suficientes."""
    f = datos_factura(ruta)
    if not f["es_factura"] or not (proveedor_corto(f.get("proveedor")) or f.get("rfc")) or not f.get("total"):
        return None
    nuevo = re.sub(r"\s+", " ", expandir(NOMBRE_FACTURA, ruta, origen, fecha, regla)).strip()
    if f.get("folio"):
        nuevo += f' {f["folio"]}'
    return _limpiar_nombre(nuevo)


def _total_legible(total):
    try:
        return "${:,.2f}".format(float(total))
    except (TypeError, ValueError):
        return ""


def datos_factura(ruta):
    """RFC y nombre del emisor de una factura (XML de CFDI, o PDF con su XML o con el texto)."""
    mis_rfc = tuple(r.strip().upper() for r in str(cargar_ajustes().get("mis_rfc", "")).split(",") if r.strip())
    try:
        return _datos_factura(ruta, os.path.getmtime(ruta), mis_rfc)
    except OSError:
        return {"es_factura": False, "rfc": "", "proveedor": "", "rfc_receptor": "", "fecha": ""}


# --------------------------------------------------------------------------- reglas

_TIPOS_CACHE = {"t": 0, "por_ext": {}, "tipos": {}}


def _tipos():
    """{extensión: tipo} con las extensiones propias por encima de las de GESTOR (se relee cada pocos segundos)."""
    if time.time() - _TIPOS_CACHE["t"] > 5:
        propias = cargar_ajustes().get("extensiones_propias") or {}
        tipos = {k: [e for e in v if e not in propias] for k, v in CATEGORIAS.items()}
        for ext, tipo in sorted(propias.items()):
            tipos.setdefault(tipo, []).append(ext)
        por_ext = {}
        for tipo, extensiones in tipos.items():
            for e in extensiones:
                por_ext.setdefault(e, tipo)
        _TIPOS_CACHE.update(t=time.time(), por_ext=por_ext, tipos=tipos)
    return _TIPOS_CACHE


def categorias():
    """{tipo: [extensiones]}: los de GESTOR y los que creaste tú."""
    return _tipos()["tipos"]


def categoria_de(extension):
    return _tipos()["por_ext"].get((extension or "").lower(), "Otros")


def normalizar_extension(texto):
    e = "." + (texto or "").strip().lower().lstrip("*").lstrip(".")
    if not re.fullmatch(r"\.[a-z0-9_\-+~]{1,20}", e):
        raise ValueError(f"«{texto}» no parece una extensión (por ejemplo: .dwg).")
    return e


def guardar_extensiones_propias(cambios, quitar=()):
    """cambios: {".ext": "Tipo"}; quitar: extensiones que vuelven a su tipo original."""
    ajustes = cargar_ajustes()
    propias = dict(ajustes.get("extensiones_propias") or {})
    for ext, tipo in cambios.items():
        tipo = " ".join(str(tipo or "").split())[:40]
        if not tipo or tipo == "Otros":
            raise ValueError("Elige o escribe un tipo de archivo.")
        propias[normalizar_extension(ext)] = tipo
    for ext in quitar:
        propias.pop(normalizar_extension(ext), None)
    ajustes["extensiones_propias"] = propias
    guardar_ajustes(ajustes)
    _TIPOS_CACHE["t"] = 0
    return propias


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
        n, v = sin_acentos(nombre.lower()), sin_acentos(texto.lower())
        if modo == "contiene" and not any(p.strip() and p.strip() in n for p in v.split("|")):
            return False
        if modo == "empieza" and not n.startswith(v):
            return False
        if modo == "termina" and not sin_acentos(base.lower()).endswith(v):
            return False
        if modo == "regex":
            try:
                if not (re.search(texto, nombre, re.IGNORECASE) or re.search(texto, n, re.IGNORECASE)):
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
    if c.get("sin_uso_dias") not in (None, "") and (ahora - ultimo_uso(st)) / 86400 <= float(c["sin_uso_dias"]):
        return False
    if c.get("zip_descomprimido") and not zip_descomprimido(ruta):
        return False
    if c.get("factura") and not datos_factura(ruta)["es_factura"]:
        return False
    return _contenido_cumple(c, ruta)  # lo más costoso, al final


def llegada(st):
    """Cuándo llegó el archivo a la carpeta: en Windows, su fecha de creación (la de la descarga)."""
    nacimiento = getattr(st, "st_birthtime", None)
    if nacimiento is None and ES_WINDOWS:
        nacimiento = st.st_ctime
    return nacimiento or st.st_mtime


def ultimo_uso(st):
    """Lo más reciente entre llegada, modificación y último acceso (abrirlo cuenta como usarlo)."""
    return max(llegada(st), st.st_mtime, st.st_atime)


def zip_descomprimido(ruta):
    """Un .zip (o .rar, .7z) con una carpeta del mismo nombre al lado: ya se descomprimió."""
    base, ext = os.path.splitext(ruta)
    if ext.lower() not in (".zip", ".rar", ".7z"):
        return False
    return any(os.path.isdir(c) and _tiene_algo(c) for c in (base, base.rstrip(" ")))


def _tiene_algo(carpeta):
    try:
        with os.scandir(carpeta) as it:
            return any(True for _ in it)
    except OSError:
        return False


def _limpiar_nombre(texto):
    return re.sub(r'[<>:"/\\|?*]', "_", texto).strip() or "_"


def expandir(patron, ruta, origen, fecha, regla=None):
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
        "carpeta_padre": os.path.basename(os.path.dirname(ruta)),
        "origen": os.path.normpath(origen),
    }
    if re.search(r"\{(procedencia|camara|sitio)\}", patron):
        valores.update(procedencia_de(ruta))
    if re.search(r"\{(rfc|proveedor)\}", patron):
        f = datos_factura(ruta)
        valores["rfc"] = f["rfc"] or "Sin RFC"
        valores["proveedor"] = (f["proveedor"] or f["rfc"] or "Proveedor desconocido").title() \
            if f["proveedor"].isupper() else (f["proveedor"] or f["rfc"] or "Proveedor desconocido")
    if re.search(r"\{(fecha_factura|total|proveedor_corto|folio)\}", patron):
        f = datos_factura(ruta)
        fecha_f = (f.get("fecha") or "")[:7]
        valores["fecha_factura"] = fecha_f if re.match(r"\d{4}-\d{2}$", fecha_f) else f"{fecha:%Y-%m}"
        valores["total"] = _total_legible(f.get("total"))
        valores["proveedor_corto"] = proveedor_corto(f.get("proveedor")) or f.get("rfc") or ""
        valores["folio"] = f.get("folio") or ""
    if "{tipo_acceso}" in patron:
        valores["tipo_acceso"] = tipo_acceso(ruta)
    if "{dato}" in patron:
        valores["dato"] = dato_de_regla(regla, ruta) or "Sin dato"

    def sustituir(m):
        clave = m.group(1)
        if clave not in valores:
            return m.group(0)
        if clave == "origen":
            return valores[clave]
        return _limpiar_nombre(valores[clave])

    return re.sub(r"\{([a-zñ_]+)\}", sustituir, patron)


_JUEGOS = ("steam", "epic games", "epicgames", "com.epicgames", "riot games", "battle.net", "ubisoft",
           "ea games", "origin games", "gog galaxy", "xboxgames", "minecraft", "roblox", "rockstar")


def destino_de_acceso(ruta):
    """A qué apunta un acceso directo (.url: su dirección; .lnk: la ruta local guardada en él)."""
    try:
        if ruta.lower().endswith(".url"):
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                for linea in f:
                    if linea.strip().lower().startswith("url="):
                        return linea.strip()[4:]
            return ""
        with open(ruta, "rb") as f:
            d = f.read(64 * 1024)
        if len(d) < 0x4C or d[:4] != b"\x4c\x00\x00\x00":
            return ""
        flags = struct.unpack_from("<I", d, 0x14)[0]
        pos = 0x4C
        if flags & 0x01:  # HasLinkTargetIDList
            pos += 2 + struct.unpack_from("<H", d, pos)[0]
        if not flags & 0x02:  # HasLinkInfo
            return ""
        inicio = pos
        cabecera = struct.unpack_from("<I", d, inicio + 4)[0]
        if cabecera >= 0x24:  # ruta en Unicode
            off = struct.unpack_from("<I", d, inicio + 0x1C)[0]
            fin = d.find(b"\x00\x00", inicio + off)
            while fin != -1 and (fin - inicio - off) % 2:
                fin = d.find(b"\x00\x00", fin + 1)
            return d[inicio + off:fin].decode("utf-16-le", "ignore")
        off = struct.unpack_from("<I", d, inicio + 0x10)[0]
        return d[inicio + off:d.find(b"\x00", inicio + off)].decode("mbcs" if ES_WINDOWS else "latin-1", "ignore")
    except (OSError, struct.error, ValueError, LookupError):
        return ""


def tipo_acceso(ruta):
    """Programas, Juegos, Sitios web, Carpetas o Archivos, según a qué apunte el acceso directo."""
    destino = destino_de_acceso(ruta)
    d = destino.lower()
    nombre = os.path.basename(ruta).lower()
    if any(j in d or j in nombre for j in _JUEGOS) or d.startswith(("steam:", "com.epicgames", "uplay:")):
        return "Juegos"
    if d.startswith(("http:", "https:")):
        return "Sitios web"
    if ruta.lower().endswith(".url"):
        return "Sitios web" if "://" in d else "Programas"
    ext = os.path.splitext(d)[1]
    if not d or ext in (".exe", ".msc", ".bat", ".cmd", ".appref-ms") or "\\program files" in d:
        return "Programas"
    if not ext:
        return "Carpetas"
    return "Archivos"


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


# --------------------------------------------------------------------------- papelera inteligente

ARCHIVO_RETENIDOS = os.path.join(DATOS, "retenidos.json")
DIAS_USO_RECIENTE = 14
_CATEGORIAS_PERSONALES = ("Imágenes", "Vídeos", "Música", "Documentos", "Hojas de cálculo", "Presentaciones")


def motivo_para_retener(op, ahora=None):
    """Por qué no conviene que un servicio mande este archivo a la papelera sin preguntarte (o None).

    - lo abriste hace poco (menos de 14 días);
    - es un documento, foto, vídeo... y no hay otra copia en ninguna carpeta del mapa de archivos.
    Los duplicados idénticos y los archivados en ZIP nunca se retienen: siempre queda una copia.
    """
    if op.get("accion") != "papelera" or op.get("duplicado") or op.get("carpeta"):
        return None
    if not cargar_ajustes().get("papelera_inteligente", True):
        return None
    ruta = op["origen"]
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    clave = f"{_norm(ruta)}|{int(st.st_mtime)}"
    if any(r.get("clave") == clave and r.get("estado") == "borrar" for r in leer_json(ARCHIVO_RETENIDOS, [])):
        return None  # ya dijiste que sí se puede borrar
    ahora = ahora or time.time()
    abierto = st.st_atime if st.st_atime > st.st_mtime + 60 else 0
    if ahora - abierto < DIAS_USO_RECIENTE * 86400:
        return f"Lo abriste hace {max(0, int((ahora - abierto) / 86400))} días"
    if categoria_de(os.path.splitext(ruta)[1].lower()) in _CATEGORIAS_PERSONALES:
        try:
            import mapa
            if mapa.config()["activo"] and bd.contar_archivos()["archivos"] and \
                    not bd.hay_otra_copia(ruta, os.path.basename(ruta), st.st_size):
                return "Es la única copia que tienes"
        except Exception:
            pass
    return None


def retener(op, servicio, motivo):
    """Apunta el archivo para que decidas tú. Devuelve True si es nuevo (para avisar una sola vez)."""
    try:
        st = os.stat(op["origen"])
    except OSError:
        return False
    clave = f'{_norm(op["origen"])}|{int(st.st_mtime)}'
    lista = leer_json(ARCHIVO_RETENIDOS, [])
    if any(r.get("clave") == clave for r in lista):
        return False
    lista.append({"id": nuevo_id(), "clave": clave, "ruta": op["origen"], "bytes": st.st_size, "motivo": motivo,
                  "servicio": servicio.get("nombre", ""), "servicio_id": servicio.get("id", ""),
                  "fecha": dt.datetime.now().isoformat(timespec="seconds"), "estado": "pendiente"})
    escribir_json(ARCHIVO_RETENIDOS, lista[-500:])
    return True


def retenidos():
    return [dict(r, existe=os.path.exists(r["ruta"])) for r in reversed(leer_json(ARCHIVO_RETENIDOS, []))
            if r.get("estado") == "pendiente"]


def decidir_retenido(rid, borrar):
    """borrar=True: a la papelera de GESTOR ahora. False: se conserva y ese servicio ya no lo toca."""
    lista = leer_json(ARCHIVO_RETENIDOS, [])
    r = next((x for x in lista if x["id"] == rid), None)
    if not r:
        return {"ok": False, "mensaje": "Ya no está en la lista."}
    r["estado"] = "borrar" if borrar else "conservar"
    escribir_json(ARCHIVO_RETENIDOS, lista)
    if borrar and os.path.exists(r["ruta"]):
        op = {"accion": "papelera", "origen": r["ruta"], "destino": "", "bytes": r.get("bytes", 0)}
        op["papelera_id"] = quitar(r["ruta"], "regla")
        indexar({"nombre": r.get("servicio") or "Papelera inteligente"}, [op], quien="tu")
    return {"ok": True}


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
    ignorar = [p for p in IGNORAR_SIEMPRE if not (servicio.get("ordenar_accesos") and p in ("*.lnk", "*.url"))]
    ignorar += [p for p in servicio.get("ignorar", []) if p]
    esperar = (float(servicio.get("esperar_minutos") or 0) * 60 if esperar_segundos is None
               else esperar_segundos)
    ya_hechos = ya_hechos or {}
    reglas = servicio.get("reglas", [])
    plan, avisos = [], []
    destinos_previstos = _Previstos()

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
        mantener = (servicio.get("carpeta_mantener") or "Mantener").strip().lower()
        for carpeta, subcarpetas, archivos in os.walk(origen):
            if not servicio.get("subcarpetas"):
                subcarpetas[:] = []
            else:
                subcarpetas[:] = [d for d in subcarpetas
                                  if not d.startswith(".")
                                  and not any(_dentro_de(os.path.join(carpeta, d), e) for e in excluir)]
            if servicio.get("subcarpetas"):
                subcarpetas[:] = [d for d in subcarpetas if d.lower() != mantener]
            juntos = servicio.get("mover_hermanos", True)
            avance(sumar=len(archivos), etapa="Revisando archivos")
            for grupo in _grupos(archivos, juntos):
                listos = []
                for nombre in grupo:
                    if _ignorado(nombre, ignorar):
                        continue
                    ruta = os.path.join(carpeta, nombre)
                    try:
                        st = os.stat(ruta)
                    except OSError:
                        continue
                    if ahora - st.st_mtime < esperar:
                        listos = None  # un hermano aún se está descargando: se espera a todo el grupo
                        break
                    if ya_hechos.get(_norm(ruta)) == int(st.st_mtime):
                        continue
                    listos.append((ruta, st))
                if not listos:
                    continue
                restantes = list(listos)
                while restantes:
                    ruta, st = restantes.pop(0)
                    op = _primera_regla(reglas, ruta, st, ahora, origen, servicio, destinos_previstos)
                    if not op:
                        continue
                    plan.append(op)
                    if juntos and len(listos) > 1 and op["accion"] != "papelera" and not op.get("duplicado"):
                        for h_ruta, h_st in restantes:
                            h = _operacion_hermana(op, h_ruta, h_st, servicio, destinos_previstos)
                            if h:
                                plan.append(h)
                        restantes = []
        plan.extend(_carpetas_viejas(servicio, origen, ahora, excluir, ignorar, mantener, destinos_previstos))
    return plan, avisos


# Extensiones que acompañan a otro archivo: nunca mandan sobre a dónde va el grupo.
_ACOMPANANTES = {".xml", ".xmp", ".aae", ".json", ".srt", ".vtt", ".sub", ".txt", ".nfo", ".thm",
                 ".lrc", ".cue", ".md5", ".sha1", ".sfv", ".log", ".ini"}


def _grupos(nombres, juntos):
    """Agrupa archivos con el mismo nombre y distinta extensión (factura.pdf + factura.xml).

    El principal va primero: el de una categoría "de verdad" antes que un acompañante.
    """
    if not juntos:
        return [[n] for n in nombres]
    grupos = {}
    for n in nombres:
        grupos.setdefault(os.path.splitext(n)[0].lower(), []).append(n)

    def peso(n):
        ext = os.path.splitext(n)[1].lower()
        return (ext in _ACOMPANANTES, categoria_de(ext) == "Otros", n.lower())

    return [sorted(g, key=peso) for g in grupos.values()]


def _primera_regla(reglas, ruta, st, ahora, origen, servicio, destinos_previstos):
    for regla in reglas:
        if (regla.get("si") or {}).get("solo_subcarpetas") and _norm(os.path.dirname(ruta)) == _norm(origen):
            continue  # ya está en la raíz
        if cumple(regla.get("si"), ruta, st, ahora):
            return _operacion(regla, ruta, st, origen, servicio, destinos_previstos)
    return None


# --------------------------------------------------------------------------- sacar todo a la raíz

ID_APLANAR = "_aplanar"


def servicio_aplanar(carpeta, nombre_con_carpeta=False, borrar_vacias=True, identicos="papelera", ignorar=None):
    """Servicio de un solo uso que saca los archivos de todas las subcarpetas a la raíz de la carpeta."""
    return {
        "id": ID_APLANAR, "nombre": f"Sacar a la raíz: {os.path.basename(os.path.normpath(carpeta)) or carpeta}",
        "activo": False, "origenes": [carpeta], "subcarpetas": True, "conflicto": "renombrar",
        "identicos": identicos if identicos in ("papelera", "carpeta", "conflicto") else "papelera",
        "borrar_carpetas_vacias": bool(borrar_vacias), "esperar_minutos": 0, "mover_hermanos": True,
        "fecha_captura_fotos": False, "carpeta_mantener": "Mantener", "ignorar": list(ignorar or []),
        "reglas": [{"id": "aplanar", "si": {"solo_subcarpetas": True}, "accion": "mover", "destino": "{origen}",
                    "fecha": "modificacion",
                    "nuevo_nombre": "{carpeta_padre} - {nombre}" if nombre_con_carpeta else ""}],
    }


def problema_aplanar(carpeta):
    """Carpetas que nunca se aplanan: raíces de disco, la carpeta de usuario y las del sistema."""
    ok, aviso = revisar_carpeta(carpeta)
    if not ok:
        return aviso
    if not os.path.isdir(carpeta):
        return "Esa carpeta no existe."
    normal = _norm(carpeta)
    if normal == _norm(os.path.splitdrive(carpeta)[0] + os.sep) or normal in (_norm("/"), _norm(os.path.expanduser("~"))):
        return "Por seguridad no se puede sacar a la raíz un disco entero ni tu carpeta de usuario."
    return ""


def aplanar(carpeta, simular=True, **opciones):
    problema = problema_aplanar(carpeta)
    if problema:
        return {"ok": False, "mensaje": problema}
    servicio = servicio_aplanar(carpeta, **opciones)
    if simular:
        r = ejecutar_servicio(servicio, simular=True)
    else:
        with Bloqueo():
            r = ejecutar_servicio(servicio)
        indexar(servicio, r["operaciones"])
    subcarpetas = sum(1 for _ in os.scandir(carpeta) if _.is_dir()) if os.path.isdir(carpeta) else 0
    return dict(r, ok=True, subcarpetas=subcarpetas)


def _operacion_hermana(principal, ruta, st, servicio, destinos_previstos):
    """El hermano sigue al principal: misma carpeta, mismo nombre nuevo, su propia extensión."""
    if principal.get("duplicado"):
        return None
    extension = os.path.splitext(ruta)[1]
    categoria = categoria_de(extension.lower())
    base_op = {"origen": ruta, "regla": principal.get("regla"), "bytes": st.st_size,
               "categoria": categoria, "hermano_de": principal["origen"]}
    if principal["accion"] == "archivar":
        return dict(base_op, accion="archivar", destino=principal["destino"])
    base_nueva = os.path.splitext(os.path.basename(principal["destino"]))[0]
    destino = os.path.join(os.path.dirname(principal["destino"]), base_nueva + extension)
    if _norm(destino) == _norm(ruta):
        return None
    if os.path.exists(destino) or _norm(destino) in destinos_previstos:
        if servicio.get("conflicto", "renombrar") == "saltar":
            return None
        b, e = os.path.splitext(destino)
        i = 1
        while os.path.exists(destino) or _norm(destino) in destinos_previstos:
            destino = f"{b} ({i}){e}"
            i += 1
    destinos_previstos.add(_norm(destino))
    return dict(base_op, accion=principal["accion"], destino=destino)


def _tamano_carpeta(carpeta, limite=200_000):
    total, vistos, reciente = 0, 0, 0.0
    for raiz, _, archivos in os.walk(carpeta):
        for n in archivos:
            try:
                st = os.stat(os.path.join(raiz, n))
            except OSError:
                continue
            total += st.st_size
            reciente = max(reciente, st.st_mtime)
            vistos += 1
            if vistos >= limite:
                return total, reciente
    return total, reciente


def _carpetas_viejas(servicio, origen, ahora, excluir, ignorar, mantener, destinos_previstos):
    """Mueve carpetas enteras del origen (por ejemplo un zip ya descomprimido) sin desarmarlas."""
    conf = servicio.get("carpetas") or {}
    if not conf.get("activo") or not conf.get("destino"):
        return []
    dias = float(conf.get("dias") or 0)
    ops = []
    try:
        entradas = list(os.scandir(origen))
    except OSError:
        return []
    for d in entradas:
        nombre = d.name
        if not d.is_dir(follow_symlinks=False) or nombre.startswith(".") or nombre.lower() == mantener:
            continue
        if _ignorado(nombre, ignorar) or any(_dentro_de(d.path, e) or _dentro_de(e, d.path) for e in excluir):
            continue
        try:
            st = d.stat()
        except OSError:
            continue
        total, reciente = _tamano_carpeta(d.path)
        # Sin el último acceso de la carpeta: el propio GESTOR lo actualiza al recorrerla.
        uso = max(llegada(st), st.st_mtime, reciente)
        if (ahora - uso) / 86400 <= dias:
            continue
        fecha = dt.datetime.fromtimestamp(llegada(st))
        carpeta = os.path.abspath(expandir(conf["destino"], d.path, origen, fecha))
        destino = os.path.join(carpeta, nombre)
        if _dentro_de(carpeta, d.path):
            continue
        i = 1
        while os.path.exists(destino) or _norm(destino) in destinos_previstos:
            destino = os.path.join(carpeta, f"{nombre} ({i})")
            i += 1
        destinos_previstos.add(_norm(destino))
        ops.append({"accion": "mover", "origen": d.path, "destino": destino, "regla": "carpetas",
                    "bytes": total, "categoria": "Carpetas", "carpeta": True})
    return ops


class _Previstos(set):
    """Destinos ya planificados en esta ejecución, y qué archivo va a cada uno."""

    def __init__(self):
        super().__init__()
        self.origen_de = {}


def _gemelo_previsto(ruta, st, destino, previstos):
    """Si otro archivo de esta misma ejecución va al mismo destino y es idéntico, lo devuelve."""
    otro = getattr(previstos, "origen_de", {}).get(_norm(destino))
    try:
        if otro and os.path.getsize(otro) == st.st_size and _huella(otro) == _huella(ruta):
            return otro
    except OSError:
        pass
    return None


@sin_tocar_acceso
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
                                           ruta, origen, fecha, regla))
        zip_ruta = os.path.join(carpeta, f"Archivo {fecha:%Y-%m}.zip")
        return {"accion": "archivar", "origen": ruta, "destino": zip_ruta, "regla": regla.get("id"),
                "bytes": st.st_size, "categoria": categoria}
    nombre = os.path.basename(ruta)
    extension = os.path.splitext(nombre)[1]
    if not regla.get("nuevo_nombre") and (regla.get("si") or {}).get("factura") \
            and cargar_ajustes().get("renombrar_facturas", True):
        nuevo = nombre_factura(ruta, origen, fecha, regla)
        if nuevo:
            nombre = nuevo + extension
    if regla.get("nuevo_nombre"):
        nombre = _limpiar_nombre(re.sub(r"\s+", " ", expandir(regla["nuevo_nombre"], ruta, origen, fecha, regla))) + extension
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
        carpeta = expandir(regla.get("destino", ""), ruta, origen, fecha, regla)
        if not carpeta:
            return None
        carpeta = os.path.abspath(carpeta)
    destino = os.path.join(carpeta, nombre)
    if _norm(destino) == _norm(ruta):
        return None
    identicos = servicio.get("identicos", "papelera")
    if identicos != "conflicto" and (os.path.exists(destino) or _norm(destino) in destinos_previstos):
        gemelo = (_copia_identica(ruta, st, destino) if os.path.exists(destino) else None) \
            or _gemelo_previsto(ruta, st, destino, destinos_previstos)
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
    if hasattr(destinos_previstos, "origen_de"):
        destinos_previstos.origen_de[_norm(destino)] = ruta
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
    hechas, errores, retenidos = [], [], []
    avance(hechos=0, total=len(plan), etapa="Moviendo archivos")
    for op in plan:
        avance(sumar=1)
        motivo = motivo_para_retener(op)
        if motivo:
            if retener(op, servicio, motivo):
                retenidos.append(op)
            continue
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
    if retenidos:
        avisar("Papelera inteligente", f"No envié a la papelera {len(retenidos)} archivo(s) que usaste hace poco o que "
               "no tienen otra copia. Decide tú en el panel (Papelera).")
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


# --------------------------------------------------------------------------- procesos (barra de progreso)

import threading  # noqa: E402

_hilo = threading.local()


class proceso:
    """Anota en la base de datos un proceso largo (nombre, avance, inicio) para que el panel muestre
    su barra de progreso y su cronómetro, aunque lo esté haciendo el motor o el icono."""

    def __init__(self, nombre):
        self.nombre = nombre

    def __enter__(self):
        self.anterior = getattr(_hilo, "p", None)
        if self.anterior:  # ya hay uno abierto en este hilo: se reutiliza
            return self.anterior
        self.p = {"id": nuevo_id(), "nombre": self.nombre, "inicio": time.time(), "hechos": 0, "total": None,
                  "etapa": "", "estado": "en marcha", "fin": None, "pid": os.getpid(), "_guardado": 0}
        _hilo.p = self.p
        _guardar_proceso(self.p, forzar=True)
        return self.p

    def __exit__(self, tipo, valor, _):
        if self.anterior:
            return
        self.p.update(estado="error" if tipo else "terminado", fin=time.time(),
                      error=str(valor) if tipo else None)
        _guardar_proceso(self.p, forzar=True)
        _hilo.p = None


def _guardar_proceso(p, forzar=False):
    ahora = time.time()
    if not forzar and ahora - p["_guardado"] < 0.5:
        return
    p["_guardado"] = ahora
    try:
        bd.escribir("proceso:" + p["id"], {k: v for k, v in p.items() if k != "_guardado"})
    except Exception:
        pass


def avance(hechos=None, total=None, etapa=None, sumar=0):
    """Lo llaman los bucles largos. Si no hay un proceso abierto en este hilo, no hace nada."""
    p = getattr(_hilo, "p", None)
    if not p:
        return
    if hechos is not None:
        p["hechos"] = hechos
    p["hechos"] += sumar
    if total is not None:
        p["total"] = total
    if etapa is not None and etapa != p["etapa"]:
        p["etapa"] = etapa
        _guardar_proceso(p, forzar=True)
    _guardar_proceso(p)


def procesos():
    """Los procesos en marcha y los terminados hace menos de un minuto."""
    ahora = time.time()
    salida, viejos = [], []
    for k, p in bd.leer_grupo("proceso").items():
        if p.get("fin") and ahora - p["fin"] > 60 or not p.get("fin") and ahora - p.get("inicio", 0) > 12 * 3600:
            viejos.append(k)
        else:
            salida.append(p)
    try:
        import mapa
        m = mapa.progreso()
        if m.get("estado") == "escaneando" or (m.get("fin") and ahora - m["fin"] < 60 and m.get("estado") == "listo"):
            salida.append({"id": "mapa", "nombre": "Mapa de archivos", "inicio": m.get("inicio"), "hechos": m.get("hechos", 0),
                           "total": m.get("total_estimado") if m.get("estado") != "escaneando" or (m.get("total_estimado") or 0) > m.get("hechos", 0) else None,
                           "etapa": "Recorriendo " + os.path.basename(m.get("carpeta") or "") if m.get("estado") == "escaneando" else "Listo",
                           "estado": "en marcha" if m.get("estado") == "escaneando" else "terminado", "fin": m.get("fin")})
    except Exception:
        pass
    if viejos:
        bd.escribir_grupo("proceso", {}, viejos)
    return sorted(salida, key=lambda p: p.get("inicio") or 0)


def ejecutar_y_anotar(servicio, motivo="manual", esperar_segundos=None, aprobado=False):
    with proceso(servicio.get("nombre") or "Servicio"):
        return _ejecutar_y_anotar(servicio, motivo, esperar_segundos, aprobado)


def _ejecutar_y_anotar(servicio, motivo="manual", esperar_segundos=None, aprobado=False):
    """Ejecuta el servicio y lo anota todo. En modo prueba solo apunta lo que haría (salvo aprobado)."""
    if servicio.get("modo_prueba") and not aprobado:
        return proponer(servicio, motivo, esperar_segundos)
    with Bloqueo():
        estado = cargar_estado()
        e = estado.setdefault(servicio["id"], {})
        registro = ejecutar_servicio(servicio, esperar_segundos=esperar_segundos,
                                     ya_hechos=e.get("hechos"))
        e.pop("propuestas", None)
        indexar(servicio, registro["operaciones"])
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


def proponer(servicio, motivo="horario", esperar_segundos=None):
    """Modo prueba: calcula lo que haría y lo guarda para aprobarlo desde el panel con un clic."""
    plan, avisos = planificar(servicio, esperar_segundos=esperar_segundos)
    estado = cargar_estado()
    e = estado.setdefault(servicio["id"], {})
    antes = (e.get("propuestas") or {}).get("n", 0)
    e["ultima"] = dt.datetime.now().isoformat(timespec="seconds")
    e["propuestas"] = {"fecha": e["ultima"], "n": len(plan), "operaciones": plan[:500], "avisos": avisos}
    e["ultimo_resultado"] = {"movidos": 0, "errores": 0, "motivo": motivo, "propuestos": len(plan)}
    guardar_estado(estado)
    if plan and len(plan) != antes:
        avisar(f'{servicio.get("nombre", "GESTOR")} (modo prueba)',
               f"Propone {len(plan)} cambios. Revísalos y apruébalos en el panel.")
    return {"simulado": True, "prueba": True, "operaciones": plan, "errores": [], "avisos": avisos}


def aprobar_prueba(servicio_id):
    """Ejecuta de verdad un servicio en modo prueba y lo saca del modo prueba."""
    servicios = cargar_servicios()
    servicio = next((s for s in servicios if s["id"] == servicio_id), None)
    if not servicio:
        raise ValueError("No existe ese servicio.")
    servicio["modo_prueba"] = False
    servicio["activo"] = True
    guardar_servicios(servicios)
    return ejecutar_y_anotar(servicio, motivo="aprobado", aprobado=True)


def terminar_prueba(servicio_id, activar=True):
    servicios = cargar_servicios()
    for s in servicios:
        if s["id"] == servicio_id:
            s["modo_prueba"] = False
            s["activo"] = bool(activar)
    guardar_servicios(servicios)
    estado = cargar_estado()
    estado.get(servicio_id, {}).pop("propuestas", None)
    guardar_estado(estado)


# --------------------------------------------------------------------------- buscador: ¿a dónde fue?

def indexar(servicio, operaciones, quien="gestor"):
    """Anota para siempre cada movimiento en la base de datos (historial, buscador, estadísticas)."""
    if not operaciones:
        return
    t = time.time()
    _migrar_indice()
    bd.anotar_movimientos([{"t": t, "servicio": servicio.get("nombre", ""), "accion": op["accion"],
                            "origen": op["origen"], "destino": op.get("destino", ""),
                            "zip": op.get("nombre_en_zip"), "papelera_id": op.get("papelera_id"),
                            "carpeta": op.get("carpeta", False), "bytes": op.get("bytes", 0), "quien": quien}
                           for op in operaciones])
    try:
        import mapa
        if mapa.config()["activo"]:
            mapa.tras_operaciones(operaciones)  # también mueve etiquetas y notas
        else:
            for op in operaciones:
                if op.get("accion") in ("mover", "renombrar") and op.get("destino"):
                    bd.seguir(op["origen"], op["destino"])
    except Exception:
        pass


_indice_migrado = False


def _migrar_indice():
    global _indice_migrado
    if not _indice_migrado:
        bd.migrar_indice(ARCHIVO_INDICE)
        _indice_migrado = True


def _leer_indice(desde=None):
    _migrar_indice()
    yield from bd.movimientos(desde=desde, limite=None)


def ultimos_movimientos(n=10):
    """Lo último que GESTOR movió, del más reciente al más antiguo."""
    _migrar_indice()
    salida = []
    for r in bd.movimientos(limite=n, recientes_primero=True):
        salida.append({"fecha": dt.datetime.fromtimestamp(r["t"]).isoformat(timespec="minutes"),
                       "servicio": r.get("s", ""), "accion": r["a"], "nombre": os.path.basename(r["o"]),
                       "destino": r.get("d") or "", "existe": bool(r.get("d")) and os.path.exists(r["d"])})
        if len(salida) >= n:
            break
    return salida


def resumen_desde(desde):
    _migrar_indice()
    return bd.resumen_movimientos(desde)


def buscar_movidos(texto, desde=None, hasta=None, limite=200):
    """Busca por nombre (sin importar acentos ni mayúsculas) en todo lo que GESTOR ha movido."""
    _migrar_indice()
    resultados = bd.movimientos(texto or "", desde, hasta, limite=None, recientes_primero=True)
    salida = []
    for r in resultados[:limite]:
        donde = r["d"]
        if r["a"] == "papelera":
            existe = any(x["id"] == r.get("p") for x in listar_papelera())
            estado = "en la papelera de GESTOR" if existe else "ya no está en la papelera"
        elif r["a"] == "archivar":
            estado = "dentro del ZIP" if os.path.exists(donde) else "el ZIP ya no está ahí"
        elif r["a"] == "borrado":
            estado = "se borró (o se mandó a la papelera de Windows)"
        else:
            estado = "está ahí" if os.path.exists(donde) else "ya no está ahí (se movió o se deshizo)"
        salida.append({"fecha": dt.datetime.fromtimestamp(r["t"]).isoformat(timespec="minutes"),
                       "servicio": r["s"], "accion": r["a"], "origen": r["o"], "destino": donde,
                       "en_zip": r.get("z"), "carpeta": r.get("c"), "estado": estado,
                       "existe": os.path.exists(donde) if donde else False, "papelera_id": r.get("p"),
                       "quien": r.get("quien")})
    return {"resultados": salida, "total": len(resultados)}


def abrir_en_explorador(ruta):
    import subprocess
    if not ruta or not os.path.exists(ruta):
        carpeta = os.path.dirname(ruta or "")
        if not os.path.isdir(carpeta):
            raise ValueError("Ya no existe ni el archivo ni su carpeta.")
        ruta = carpeta
    if ES_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(ruta)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(ruta)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- resumen semanal

def cargar_sistema():
    return leer_json(ARCHIVO_SISTEMA, {})


def guardar_sistema(datos):
    escribir_json(ARCHIVO_SISTEMA, datos)


def resumen_semana(ahora=None):
    ahora = ahora or time.time()
    desde = ahora - 7 * 86400
    por_servicio, movidos, a_papelera, bytes_papelera = {}, 0, 0, 0
    for r in _leer_indice(desde):
        por_servicio[r["s"]] = por_servicio.get(r["s"], 0) + 1
        if r["a"] == "papelera":
            a_papelera += 1
            bytes_papelera += r.get("b", 0)
        else:
            movidos += 1
    return {"movidos": movidos, "papelera": a_papelera, "bytes_papelera": bytes_papelera,
            "por_servicio": por_servicio}


def aviso_semanal(ahora=None):
    """Una vez por semana, un aviso con lo que se ordenó. Devuelve True si avisó."""
    ahora = ahora or time.time()
    if not cargar_ajustes().get("aviso_semanal", True):
        return False
    sistema = cargar_sistema()
    ultimo = sistema.get("resumen_semanal")
    if ultimo is None:
        sistema["resumen_semanal"] = ahora  # la primera semana empieza a contar ahora
        guardar_sistema(sistema)
        return False
    if ahora - ultimo < 7 * 86400:
        return False
    sistema["resumen_semanal"] = ahora
    guardar_sistema(sistema)
    r = resumen_semana(ahora)
    if not r["movidos"] and not r["papelera"]:
        return False
    partes = [f'{r["movidos"]} archivos ordenados']
    if r["papelera"]:
        partes.append(f'{r["papelera"]} a la papelera ({tamano_legible(r["bytes_papelera"])} liberables)')
    top = sorted(r["por_servicio"].items(), key=lambda x: -x[1])[:3]
    texto = ", ".join(partes) + ". " + " · ".join(f"{n}: {c}" for n, c in top)
    avisar("Resumen de la semana", texto)
    return True


def tamano_legible(b):
    for unidad in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {unidad}" if unidad == "B" else f"{b:.1f} {unidad}"
        b /= 1024
    return f"{b:.1f} TB"


# --------------------------------------------------------------------------- espacio en disco

def unidades_fijas():
    """[{"letra", "total", "libre"}] de los discos con letra (o "/" fuera de Windows)."""
    salida = []
    if ES_WINDOWS:
        import ctypes
        mascara = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if not mascara & (1 << i):
                continue
            raiz = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(raiz) not in (2, 3):  # extraíble o fijo
                continue
            try:
                u = shutil.disk_usage(raiz)
            except OSError:
                continue
            salida.append({"letra": raiz[:2], "total": u.total, "libre": u.free})
    else:
        u = shutil.disk_usage(os.path.expanduser("~"))
        salida.append({"letra": "/", "total": u.total, "libre": u.free})
    return salida


def revisar_disco(ahora=None):
    """Avisa (como mucho una vez al día por disco) si queda menos espacio libre que el umbral."""
    ahora = ahora or time.time()
    umbral = float(cargar_ajustes().get("umbral_disco") or 0)
    if umbral <= 0:
        return []
    sistema = cargar_sistema()
    vistos = sistema.setdefault("aviso_disco", {})
    avisados = []
    for u in unidades_fijas():
        if not u["total"]:
            continue
        pct = u["libre"] * 100 / u["total"]
        if pct >= umbral or ahora - vistos.get(u["letra"], 0) < 86400:
            continue
        vistos[u["letra"]] = ahora
        avisar(f'Queda poco espacio en {u["letra"]}',
               f'Libre: {tamano_legible(u["libre"])} ({pct:.0f} %). Abre GESTOR > Espacio para ver qué liberar.')
        avisados.append(u["letra"])
    if avisados:
        guardar_sistema(sistema)
    return avisados


def analizar_espacio(min_mb=50, maximo=100, limite_archivos=300_000):
    """Sugerencias para liberar espacio en las carpetas del usuario."""
    carpetas = carpetas_rapidas()
    grandes, instaladores, viejos_descargas = [], [], []
    ahora = time.time()
    descargas = _norm(carpetas["Descargas"])
    vistos = 0
    for nombre, raiz in carpetas.items():
        if not os.path.isdir(raiz):
            continue
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            subcarpetas[:] = [d for d in subcarpetas if not d.startswith(".") and d.lower() != "appdata"]
            avance(sumar=len(archivos), etapa="Mirando " + nombre)
            for n in archivos:
                vistos += 1
                if vistos > limite_archivos:
                    break
                ruta = os.path.join(carpeta, n)
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                fila = {"ruta": ruta, "bytes": st.st_size,
                        "dias": int((ahora - ultimo_uso(st)) / 86400)}
                if st.st_size >= min_mb * 1024 * 1024:
                    grandes.append(fila)
                if _dentro_de(ruta, descargas):
                    ext = os.path.splitext(n)[1].lower()
                    if categoria_de(ext) == "Instaladores" or zip_descomprimido(ruta):
                        instaladores.append(fila)
                    elif fila["dias"] > 90:
                        viejos_descargas.append(fila)
    grandes.sort(key=lambda f: -f["bytes"])
    papelera = listar_papelera()
    return {
        "discos": unidades_fijas(),
        "umbral": cargar_ajustes().get("umbral_disco", 10),
        "grandes": grandes[:maximo],
        "instaladores": sorted(instaladores, key=lambda f: -f["bytes"])[:maximo],
        "viejos_descargas": sorted(viejos_descargas, key=lambda f: -f["bytes"])[:maximo],
        "papelera": {"n": len(papelera), "bytes": sum(p.get("bytes", 0) for p in papelera)},
        "incompleto": vistos > limite_archivos,
    }


# --------------------------------------------------------------------------- no molestar

def _con_bateria():
    if not ES_WINDOWS:
        return False
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    s = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return False
    return s.ACLineStatus == 0 and s.BatteryFlag != 128  # desenchufado y con batería


def _pantalla_ocupada():
    """Juego, vídeo o presentación a pantalla completa (lo mismo que usa Windows para callar avisos)."""
    if not ES_WINDOWS:
        return False
    import ctypes
    estado = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(estado)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return estado.value in (2, 3, 4)  # ocupado, Direct3D a pantalla completa, modo presentación


def _en_horas(desde, hasta, ahora):
    def minutos(t):
        h, m = (t or "0:0").split(":")[:2]
        return int(h) * 60 + int(m)
    a, b, n = minutos(desde), minutos(hasta), ahora.hour * 60 + ahora.minute
    return a <= n < b if a <= b else (n >= a or n < b)


def motivo_no_molestar(ahora=None):
    """Texto con el motivo por el que ahora no conviene ordenar, o None. Lo pendiente se hace después."""
    nm = cargar_ajustes().get("no_molestar") or {}
    ahora = ahora or dt.datetime.now()
    try:
        if nm.get("horas") and _en_horas(nm.get("desde"), nm.get("hasta"), ahora):
            return f'horario de no molestar ({nm.get("desde")}–{nm.get("hasta")})'
        if nm.get("bateria") and _con_bateria():
            return "el equipo funciona con batería"
        if nm.get("pantalla_completa") and _pantalla_ocupada():
            return "hay un juego, vídeo o presentación a pantalla completa"
    except Exception:
        return None
    return None


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

@sin_tocar_acceso
def _huella_parcial(ruta, tam=64 * 1024):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        h.update(f.read(tam))
    return h.digest()


_NO_DUPLICADOS = ("appdata", "node_modules", "__pycache__", "gestor-papelera", "system volume information",
                  "windows.old", "$recycle.bin", "msocache", "recovery")


def buscar_duplicados(carpetas, min_bytes=1024, progreso=None, cancelado=lambda: False, por_carpeta=None):
    """Grupos de archivos con contenido idéntico, aunque tengan distinto nombre.

    Se filtra en tres pasos para no leer de más: mismo tamaño, mismos primeros 64 KB y
    misma huella SHA-256 completa. Devuelve los grupos ordenados por espacio recuperable.
    """
    externo = progreso or (lambda **k: None)

    def progreso(**k):
        externo(**k)
        avance(hechos=k.get("comparados", k.get("revisados")), total=k.get("total") if "comparados" in k else None,
               etapa=k.get("fase"))
    por_tamano, vistos, revisados = {}, set(), 0
    por_carpeta = por_carpeta if por_carpeta is not None else {}
    # Los respaldos son copias a propósito: no se cuentan como duplicados.
    respaldos = [r.get("destino") for r in cargar_ajustes().get("respaldos") or [] if r.get("destino")]
    for raiz in carpetas:
        if not revisar_carpeta(raiz)[0]:
            continue
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            if cancelado():
                return []
            subcarpetas[:] = [d for d in subcarpetas if not d.startswith((".", "$"))
                              and d.lower() not in _NO_DUPLICADOS
                              and revisar_carpeta(os.path.join(carpeta, d))[0]
                              and not any(_dentro_de(os.path.join(carpeta, d), r) for r in respaldos)]
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
                por_carpeta[carpeta] = por_carpeta.get(carpeta, 0) + 1
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


def carpetas_que_se_repiten(grupos, por_carpeta, minimo=3, maximo=100):
    """Parejas de carpetas que comparten muchos archivos idénticos (una suele ser copia de la otra).

    [{a, b, archivos, bytes, pct_a, pct_b}]: pct_a es qué parte de los archivos de A también está en B.
    """
    parejas = {}
    for g in grupos:
        carpetas = sorted({os.path.dirname(r) for r in g["archivos"]})
        for i, a in enumerate(carpetas):
            for b in carpetas[i + 1:]:
                p = parejas.setdefault((a, b), {"archivos": 0, "bytes": 0})
                p["archivos"] += 1
                p["bytes"] += g["bytes"]
    salida = []
    for (a, b), p in parejas.items():
        if p["archivos"] < minimo:
            continue
        salida.append({"a": a, "b": b, "archivos": p["archivos"], "bytes": p["bytes"],
                       "pct_a": round(100 * p["archivos"] / max(por_carpeta.get(a, 1), 1)),
                       "pct_b": round(100 * p["archivos"] / max(por_carpeta.get(b, 1), 1))})
    salida.sort(key=lambda x: x["bytes"], reverse=True)
    return salida[:maximo]


ID_COMBINAR = "_combinar"


def combinar_carpetas(conservar, vaciar, simular=True):
    """Junta dos carpetas parecidas: todo lo de «vaciar» pasa a «conservar» con su misma estructura.

    Lo que ya existe igual (mismo contenido) va a la papelera de GESTOR; si existe con otro contenido,
    se guarda como «archivo (1)». Las carpetas que quedan vacías se borran. Se puede deshacer.
    """
    for c in (conservar, vaciar):
        problema = problema_aplanar(c)
        if problema:
            return {"ok": False, "mensaje": f"{c}: {problema}"}
    if _norm(conservar) == _norm(vaciar) or _dentro_de(conservar, vaciar) or _dentro_de(vaciar, conservar):
        return {"ok": False, "mensaje": "Una carpeta está dentro de la otra: elige dos carpetas distintas."}
    plan, previstos = [], set()
    resumen = {"mover": 0, "iguales": 0, "renombrados": 0, "bytes_liberados": 0}
    for carpeta, subcarpetas, archivos in os.walk(vaciar):
        subcarpetas[:] = [d for d in subcarpetas if not d.startswith(".")]
        avance(sumar=len(archivos), etapa="Comparando archivos")
        for n in archivos:
            ruta = os.path.join(carpeta, n)
            destino = os.path.join(conservar, os.path.relpath(ruta, vaciar))
            try:
                st = os.stat(ruta)
                if os.path.exists(destino) and os.path.getsize(destino) == st.st_size and _huella(destino) == _huella(ruta):
                    plan.append({"accion": "papelera", "origen": ruta, "destino": "", "duplicado": True,
                                 "igual_a": destino, "bytes": st.st_size, "categoria": categoria_de(os.path.splitext(n)[1].lower())})
                    resumen["iguales"] += 1
                    resumen["bytes_liberados"] += st.st_size
                    continue
            except OSError:
                continue
            renombrado = os.path.exists(destino) or _norm(destino) in previstos
            if renombrado:
                b, e = os.path.splitext(destino)
                i = 1
                while os.path.exists(f"{b} ({i}){e}") or _norm(f"{b} ({i}){e}") in previstos:
                    i += 1
                destino = f"{b} ({i}){e}"
                resumen["renombrados"] += 1
            previstos.add(_norm(destino))
            resumen["mover"] += 1
            plan.append({"accion": "mover", "origen": ruta, "destino": destino, "bytes": st.st_size,
                         "renombrado": renombrado, "categoria": categoria_de(os.path.splitext(n)[1].lower())})
    if simular:
        return {"ok": True, "simulado": True, "operaciones": plan, "resumen": resumen}
    hechas, errores = [], []
    avance(hechos=0, total=len(plan), etapa="Combinando")
    with Bloqueo():
        for op in plan:
            avance(sumar=1)
            try:
                aplicar(op)
                hechas.append(op)
            except Exception as e:
                errores.append(dict(op, error=str(e)))
        borradas = []
        for carpeta, _, _ in sorted(os.walk(vaciar), key=lambda x: -len(x[0])):
            try:
                restos = os.listdir(carpeta)
                if all(r.lower() in ("desktop.ini", "thumbs.db", ".ds_store") for r in restos):
                    for r in restos:
                        os.remove(os.path.join(carpeta, r))
                    os.rmdir(carpeta)
                    borradas.append(carpeta)
            except OSError:
                pass
    servicio = {"id": ID_COMBINAR, "nombre": "Combinar carpetas"}
    if hechas or errores:
        guardar_registro({"servicio": ID_COMBINAR, "nombre": "Combinar carpetas",
                          "fecha": dt.datetime.now().isoformat(timespec="seconds"), "operaciones": hechas,
                          "errores": errores, "avisos": [], "deshecho": False, "carpetas_borradas": borradas})
    indexar(servicio, hechas)
    if resumen["iguales"]:
        anotar_liberado(sum(op["bytes"] for op in hechas if op["accion"] == "papelera"),
                        sum(1 for op in hechas if op["accion"] == "papelera"))
    return {"ok": True, "simulado": False, "operaciones": hechas, "errores": [e["error"] for e in errores][:50],
            "resumen": resumen, "carpetas_borradas": borradas}


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


def _nombre_amigable(carpeta):
    for nombre, ruta in carpetas_rapidas().items():
        if _norm(ruta) == _norm(carpeta):
            return nombre
    return os.path.basename(os.path.normpath(carpeta)) or carpeta


def crear_desde_asistente(carpeta, reglas, limpiar=False):
    servicio = {
        "id": nuevo_id(), "nombre": f"Ordenar {_nombre_amigable(carpeta)}",
        "activo": True, "modo_prueba": True, "origenes": [carpeta], "subcarpetas": False,
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
    if ajustes.get("detenido"):
        return False
    if ajustes.get("acceso_red") or (ajustes.get("mapa_archivos") or {}).get("activo", True):
        return True
    if ajustes.get("icono_bandeja", True) and ES_WINDOWS:
        return True
    return any(s.get("activo") and (s.get("horario") or {}).get("tipo") == "instante"
               for s in cargar_servicios())


def lanzar_residente():
    """Arranca el proceso residente (icono y modo al instante) si hace falta y no está ya en marcha."""
    if os.environ.get("GESTOR_SIN_RESIDENTE") or residente_activo() or not necesita_residente():
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

# --------------------------------------------------------------------------- versiones y relevo

def _procesos_windows():
    """[(pid, ruta del ejecutable)] de los procesos que se pueden consultar."""
    import ctypes
    from ctypes import wintypes
    psapi, kernel32 = ctypes.windll.psapi, ctypes.windll.kernel32
    pids = (wintypes.DWORD * 4096)()
    usados = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(usados)):
        return []
    salida = []
    for pid in pids[:usados.value // ctypes.sizeof(wintypes.DWORD)]:
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            largo = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(largo)):
                salida.append((pid, buf.value))
        finally:
            kernel32.CloseHandle(h)
    return salida


def otras_versiones():
    """Procesos GESTOR.exe que se ejecutan desde otra carpeta (otra versión). Solo en el .exe."""
    if not (ES_WINDOWS and EMPAQUETADO):
        return []
    propio = _norm(sys.executable)
    nombre = os.path.basename(sys.executable).lower()
    return [(pid, ruta) for pid, ruta in _procesos_windows()
            if pid != os.getpid() and os.path.basename(ruta).lower() == nombre and _norm(ruta) != propio]


def pedir_cierre(pids):
    """Pide a esos procesos que se cierren solos (los de esta versión o posteriores lo atienden)."""
    escribir_json(ARCHIVO_DETENER, {"pids": list(pids), "t": time.time()})


def cerrar_residente():
    """Pide al residente (icono, al instante) que se cierre."""
    try:
        with open(ARCHIVO_PID_RESIDENTE) as f:
            pedir_cierre([int(f.read().strip())])
    except (OSError, ValueError):
        pass


def debo_cerrarme():
    datos = leer_json(ARCHIVO_DETENER, {})
    return os.getpid() in (datos.get("pids") or []) and time.time() - datos.get("t", 0) < 120


def relevar_versiones_antiguas(espera=6):
    """Al abrir una versión nueva: cierra la anterior (icono, panel) para que no se queden dos a la vez.

    Primero se lo pide con amabilidad; si a los pocos segundos sigue abierta (las versiones viejas no
    entienden la petición), se cierra a la fuerza. Devuelve cuántos procesos cerró.
    """
    otras = otras_versiones()
    if not otras:
        return 0
    pedir_cierre([pid for pid, _ in otras])
    limite = time.time() + espera
    while time.time() < limite and otras_versiones():
        time.sleep(0.5)
    import ctypes
    for pid, _ in otras_versiones():
        h = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if h:
            ctypes.windll.kernel32.TerminateProcess(h, 0)
            ctypes.windll.kernel32.CloseHandle(h)
    time.sleep(1)
    try:
        os.remove(ARCHIVO_BLOQUEO)  # por si la versión vieja lo dejó puesto
    except OSError:
        pass
    return len(otras)


def comando_programado():
    """El comando que tiene la tarea programada ahora mismo (o "" si no hay tarea)."""
    if not ES_WINDOWS:
        return ""
    import subprocess
    r = subprocess.run(["schtasks", "/Query", "/TN", NOMBRE_TAREA, "/XML"], capture_output=True,
                       creationflags=0x08000000)
    if r.returncode != 0:
        return ""
    xml = r.stdout.decode("utf-16", "ignore") if r.stdout[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else r.stdout.decode("utf-8", "ignore")
    m = re.search(r"<Command>(.*?)</Command>", xml, re.S)
    return m.group(1).strip().strip('"') if m else ""


def actualizar_programacion():
    """Si la tarea programada apunta a otra versión del .exe, la cambia a esta. Devuelve True si cambió."""
    if not (ES_WINDOWS and EMPAQUETADO):
        return False
    actual = comando_programado()
    if not actual or _norm(actual) == _norm(sys.executable):
        return False
    return programar_motor(int(cargar_ajustes().get("revisar_cada_minutos") or 5)).get("ok", False)


def tomar_el_relevo():
    """Lo hace cada versión al abrirse: cierra la vieja, actualiza la tarea y arranca su residente."""
    cerrados = relevar_versiones_antiguas()
    cambiada = actualizar_programacion()
    if cerrados or cambiada:
        avisar("GESTOR actualizado", f"Ahora funciona la versión {VERSION}.")
    return {"cerrados": cerrados, "programacion_actualizada": cambiada}


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
