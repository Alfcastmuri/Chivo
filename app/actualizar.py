"""GESTOR: actualización automática.

Una vez al día pregunta a GitHub si hay una versión nueva. Si la hay, te avisa y en el panel aparece
«Actualizar ahora»: con un clic se descarga el instalador nuevo y se instala en silencio
(respaldando antes la base de datos); al terminar, GESTOR vuelve a abrirse solo.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import bd
import nucleo

REPO = "Alfcastmuri/Chivo"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGINA = f"https://github.com/{REPO}/releases/latest"
CADA_HORAS = 20
CLAVE_REGISTRO = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{A7D3E5B2-4C91-4F0B-8E6A-2D5C9B1F7E43}_is1"


def version_tupla(texto):
    return tuple(int(n) for n in re.findall(r"\d+", texto or "")[:3]) or (0,)


def carpeta_instalada():
    """Dónde lo instaló el instalador (o "" si no está instalado)."""
    if not nucleo.ES_WINDOWS:
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_REGISTRO) as k:
            return winreg.QueryValueEx(k, "InstallLocation")[0] or ""
    except OSError:
        return ""


def puede_instalarse_solo():
    """Solo la copia instalada con el instalador se actualiza sola (la del .zip se descarga a mano)."""
    carpeta = carpeta_instalada()
    return bool(nucleo.EMPAQUETADO and carpeta and nucleo._dentro_de(sys.executable, carpeta))


def estado():
    a = bd.leer("actualizacion", {}) or {}
    nueva = bool(a.get("version")) and version_tupla(a["version"]) > version_tupla(nucleo.VERSION)
    return {**a, "actual": nucleo.VERSION, "nueva": nueva, "puede_instalarse": puede_instalarse_solo(),
            "pagina": PAGINA, "activo": nucleo.cargar_ajustes().get("buscar_actualizaciones", True)}


def comprobar(forzar=False):
    previo = bd.leer("actualizacion", {}) or {}
    if not forzar and time.time() - previo.get("t", 0) < CADA_HORAS * 3600:
        return estado()
    try:
        peticion = urllib.request.Request(API, headers={"User-Agent": f"GESTOR/{nucleo.VERSION}",
                                                        "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(peticion, timeout=20) as r:
            datos = json.load(r)
    except Exception as e:
        bd.escribir("actualizacion", {**previo, "t": time.time(), "error": str(e)})
        return estado()
    instalador = next((a for a in datos.get("assets") or []
                       if a.get("name", "").lower().startswith("gestor-instalador") and a["name"].lower().endswith(".exe")), None)
    bd.escribir("actualizacion", {
        "t": time.time(), "error": "", "version": (datos.get("tag_name") or "").lstrip("vV"),
        "notas": (datos.get("body") or "")[:4000], "publicada": datos.get("published_at", ""),
        "url": instalador["browser_download_url"] if instalador else "", "bytes": instalador["size"] if instalador else 0,
        "avisada": previo.get("avisada", "")})
    return estado()


def descargar(e):
    destino = os.path.join(tempfile.gettempdir(), f'GESTOR-Instalador-{e["version"]}.exe')
    peticion = urllib.request.Request(e["url"], headers={"User-Agent": f"GESTOR/{nucleo.VERSION}"})
    with urllib.request.urlopen(peticion, timeout=60) as r, open(destino + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or e.get("bytes") or 0)
        hechos = 0
        while True:
            trozo = r.read(256 * 1024)
            if not trozo:
                break
            f.write(trozo)
            hechos += len(trozo)
            nucleo.avance(hechos=hechos, total=total or None, etapa="Descargando la versión " + e["version"])
    if e.get("bytes") and os.path.getsize(destino + ".part") != e["bytes"]:
        raise OSError("La descarga llegó incompleta. Inténtalo otra vez.")
    os.replace(destino + ".part", destino)
    return destino


def instalar():
    """Descarga e instala la versión nueva. El instalador cierra GESTOR y lo vuelve a abrir al terminar."""
    e = comprobar(forzar=True)
    if not e["nueva"]:
        return {"ok": False, "mensaje": f'Ya tienes la última versión ({nucleo.VERSION}).'}
    if not e.get("url"):
        return {"ok": False, "mensaje": "La versión nueva todavía no tiene instalador. Prueba en unos minutos."}
    if not e["puede_instalarse"]:
        return {"ok": False, "mensaje": "Esta copia de GESTOR no se instaló con el instalador: descarga la versión nueva desde "
                                        + PAGINA, "pagina": PAGINA}
    ruta = descargar(e)
    subprocess.Popen([ruta, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/reabrir=1"],
                     creationflags=0x00000008 | 0x00000200, close_fds=True)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    return {"ok": True, "mensaje": f'Instalando GESTOR {e["version"]}… El panel se cerrará y volverá a abrirse solo.'}


def mantenimiento():
    """Lo llama el motor: una consulta al día y un aviso por cada versión nueva."""
    if not nucleo.cargar_ajustes().get("buscar_actualizaciones", True):
        return
    e = comprobar()
    if e["nueva"] and e.get("avisada") != e["version"]:
        a = bd.leer("actualizacion", {}) or {}
        a["avisada"] = e["version"]
        bd.escribir("actualizacion", a)
        nucleo.avisar("Hay una versión nueva de GESTOR",
                      f'La {e["version"]} está lista. Actualiza con un clic desde el panel.')
