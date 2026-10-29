"""GESTOR: mantenimiento. Lo usan el instalador y el panel.

  GESTOR.exe --detener          detiene los servicios (cierra el icono y el motor no ordena nada)
  GESTOR.exe --reiniciar        los vuelve a encender, actualiza la tarea programada y abre el icono
  GESTOR.exe --respaldar-base   copia la base de datos a Documentos\\GESTOR\\Respaldos de la base
  GESTOR.exe --cerrar-procesos  cierra todo GESTOR sin cambiar nada (antes de actualizar o reparar)
  GESTOR.exe --desinstalar      cierra todo y quita la tarea programada (tus datos se conservan)

Cada orden termina con código 0 si fue bien y escribe el resultado en mantenimiento.log.
"""

import datetime as dt
import os
import shutil
import sqlite3
import sys
import time

import bd
import nucleo

MAX_RESPALDOS = 30


def carpeta_respaldos():
    return os.path.join(nucleo.carpeta_conocida("Documentos"), "GESTOR", "Respaldos de la base")


def _anotar(texto):
    try:
        with open(os.path.join(nucleo.DATOS, "mantenimiento.log"), "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}  {texto}\n")
    except OSError:
        pass


def procesos_gestor():
    """Todos los GESTOR.exe en marcha (de cualquier carpeta) menos este."""
    if not (nucleo.ES_WINDOWS and nucleo.EMPAQUETADO):
        return []
    nombre = os.path.basename(sys.executable).lower()
    return [(pid, ruta) for pid, ruta in nucleo._procesos_windows()
            if pid != os.getpid() and os.path.basename(ruta).lower() == nombre]


def cerrar_procesos(espera=6):
    """Pide a todo GESTOR que se cierre y, si no lo hace a los pocos segundos, lo cierra a la fuerza."""
    otros = procesos_gestor()
    if otros:
        nucleo.pedir_cierre([pid for pid, _ in otros])
        limite = time.time() + espera
        while time.time() < limite and procesos_gestor():
            time.sleep(0.5)
        import ctypes
        for pid, _ in procesos_gestor():
            h = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
            if h:
                ctypes.windll.kernel32.TerminateProcess(h, 0)
                ctypes.windll.kernel32.CloseHandle(h)
        time.sleep(1)
    try:
        os.remove(nucleo.ARCHIVO_BLOQUEO)
    except OSError:
        pass
    return len(otros)


def detener():
    ajustes = nucleo.cargar_ajustes()
    ajustes["detenido"] = True
    nucleo.guardar_ajustes(ajustes)
    cerrados = cerrar_procesos()
    return {"ok": True, "mensaje": f"Servicios detenidos ({cerrados} procesos cerrados)."}


def reiniciar():
    cerrar_procesos()
    ajustes = nucleo.cargar_ajustes()
    ajustes["detenido"] = False
    ajustes["pausado"] = False
    nucleo.guardar_ajustes(ajustes)
    if nucleo.ES_WINDOWS:
        r = nucleo.programar_motor(int(ajustes.get("revisar_cada_minutos") or 5))  # también abre el icono
        if not r.get("ok"):
            return {"ok": False, "mensaje": "No se pudo programar el motor: " + r.get("mensaje", "")}
    else:
        nucleo.lanzar_residente()
    return {"ok": True, "mensaje": "Servicios reiniciados."}


def respaldar_base(carpeta=None):
    """Copia segura de gestor.db (aunque GESTOR la esté usando) y de la contraseña del panel."""
    carpeta = carpeta or carpeta_respaldos()
    os.makedirs(carpeta, exist_ok=True)
    sello = dt.datetime.now().strftime("%Y-%m-%d %H%M%S")
    destino = os.path.join(carpeta, f"gestor {sello}.db")
    origen = bd.con()
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
    credenciales = os.path.join(nucleo.DATOS, "credenciales.json")
    if os.path.exists(credenciales):
        shutil.copy2(credenciales, os.path.join(carpeta, f"credenciales {sello}.json"))
    viejos = sorted(n for n in os.listdir(carpeta) if n.startswith("gestor ") and n.endswith(".db"))
    for n in viejos[:-MAX_RESPALDOS]:
        for archivo in (n, "credenciales " + n[7:-3] + ".json"):
            try:
                os.remove(os.path.join(carpeta, archivo))
            except OSError:
                pass
    return {"ok": True, "ruta": destino, "mensaje": f"Base de datos respaldada en {destino}"}


def respaldos():
    carpeta = carpeta_respaldos()
    if not os.path.isdir(carpeta):
        return []
    return [{"ruta": os.path.join(carpeta, n), "bytes": os.path.getsize(os.path.join(carpeta, n))}
            for n in sorted(os.listdir(carpeta), reverse=True) if n.endswith(".db")]


def desinstalar():
    cerrar_procesos()
    nucleo.quitar_programacion()
    return {"ok": True, "mensaje": "Servicios quitados. Tus datos siguen en " + nucleo.DATOS}


ORDENES = {"--detener": detener, "--reiniciar": reiniciar, "--respaldar-base": respaldar_base,
           "--cerrar-procesos": lambda: {"ok": True, "mensaje": f"{cerrar_procesos()} procesos cerrados."},
           "--desinstalar": desinstalar}


def main(orden, args):
    try:
        r = ORDENES[orden](*args[:1]) if orden == "--respaldar-base" else ORDENES[orden]()
    except Exception as e:
        r = {"ok": False, "mensaje": f"{type(e).__name__}: {e}"}
    _anotar(f"{orden}: {r.get('mensaje')}")
    if sys.stdout:
        try:
            print(r.get("mensaje"))
        except Exception:
            pass
    sys.exit(0 if r.get("ok") else 1)
