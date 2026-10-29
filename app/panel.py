"""GESTOR: panel. Abre http://127.0.0.1:8765 en el navegador para crear y editar servicios.

El panel se cierra solo cuando cierras la pestaña (tras unos minutos sin actividad),
o con el botón "Cerrar panel".
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import nucleo

PUERTO = int(os.environ.get("GESTOR_PUERTO", "8765"))
TOKEN = secrets.token_urlsafe(24)
INACTIVIDAD_SEGUNDOS = 5 * 60
ultima_actividad = time.time()

def dialogo_carpeta(salida, inicial=""):
    """Selector de carpetas nativo de Windows. Se ejecuta en un proceso aparte (ver elegir_carpeta).

    El resultado se escribe en un archivo porque el .exe sin consola no tiene salida estándar.
    """
    import tkinter as tk
    from tkinter import filedialog
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    ruta = filedialog.askdirectory(title="Elige una carpeta para GESTOR",
                                   initialdir=inicial or None, mustexist=True)
    raiz.destroy()
    with open(salida, "w", encoding="utf-8") as f:
        f.write(ruta or "")


def elegir_carpeta(inicial=""):
    salida = os.path.join(nucleo.DATOS, f"carpeta-{secrets.token_hex(4)}.txt")
    if nucleo.EMPAQUETADO:
        comando = [sys.executable, "--elegir-carpeta", salida, inicial or ""]
    else:
        comando = [sys.executable, os.path.join(nucleo.BASE, "gestor.py"), "--elegir-carpeta", salida, inicial or ""]
    subprocess.run(comando, creationflags=0x08000000 if nucleo.ES_WINDOWS else 0)
    try:
        with open(salida, encoding="utf-8") as f:
            ruta = f.read().strip()
        os.remove(salida)
    except OSError:
        ruta = ""
    return os.path.normpath(ruta) if ruta else ""


def servicios_con_estado():
    estado = nucleo.cargar_estado()
    resultado = []
    for s in nucleo.cargar_servicios():
        e = estado.get(s["id"], {})
        resultado.append({"servicio": s, "ultima": e.get("ultima"),
                          "ultimo_resultado": e.get("ultimo_resultado"),
                          "proxima": nucleo.proxima_ejecucion(s, e)})
    return resultado


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_valido(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _responder(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _leer(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo) or b"{}") if largo else {}

    def do_GET(self):
        global ultima_actividad
        if not self._host_valido():
            return self._responder(403, {"error": "Acceso no permitido"})
        ultima_actividad = time.time()
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            with open(os.path.join(nucleo.BASE, "panel.html"), "rb") as f:
                html = f.read().replace(b"__TOKEN__", TOKEN.encode())
            return self._responder(200, html, "text/html; charset=utf-8")
        return self._responder(404, {"error": "No encontrado"})

    def do_POST(self):
        global ultima_actividad
        if not self._host_valido() or self.headers.get("X-Gestor-Token") != TOKEN:
            return self._responder(403, {"error": "Acceso no permitido"})
        ultima_actividad = time.time()
        ruta = urlparse(self.path).path
        try:
            datos = self._leer()
            return self._responder(200, self._api(ruta, datos))
        except Exception as e:
            return self._responder(500, {"error": str(e)})

    def _api(self, ruta, datos):
        if ruta == "/api/inicio":
            return {"servicios": servicios_con_estado(), "categorias": list(nucleo.CATEGORIAS) + ["Otros"],
                    "carpetas_rapidas": nucleo.carpetas_rapidas(), "ajustes": nucleo.cargar_ajustes(),
                    "programacion": nucleo.estado_programacion(), "windows": nucleo.ES_WINDOWS}
        if ruta == "/api/latido":
            return {"ok": True}
        if ruta == "/api/servicios":
            return {"servicios": servicios_con_estado()}
        if ruta == "/api/guardar":
            servicio = datos["servicio"]
            if not servicio.get("id"):
                servicio["id"] = nucleo.nuevo_id()
            for regla in servicio.get("reglas", []):
                regla.setdefault("id", nucleo.nuevo_id())
            servicios = nucleo.cargar_servicios()
            for i, s in enumerate(servicios):
                if s["id"] == servicio["id"]:
                    servicios[i] = servicio
                    break
            else:
                servicios.append(servicio)
            nucleo.guardar_servicios(servicios)
            # Al cambiar el horario, empieza a contar desde ahora.
            estado = nucleo.cargar_estado()
            e = estado.setdefault(servicio["id"], {})
            if e.get("horario") != servicio.get("horario") or not e.get("activo_antes") and servicio.get("activo"):
                e["visto"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            e["horario"] = servicio.get("horario")
            e["activo_antes"] = bool(servicio.get("activo"))
            nucleo.guardar_estado(estado)
            return {"ok": True, "id": servicio["id"], "servicios": servicios_con_estado()}
        if ruta == "/api/borrar":
            servicios = [s for s in nucleo.cargar_servicios() if s["id"] != datos["id"]]
            nucleo.guardar_servicios(servicios)
            return {"ok": True, "servicios": servicios_con_estado()}
        if ruta == "/api/elegir-carpeta":
            carpeta = elegir_carpeta(datos.get("inicial", ""))
            permitida, aviso = nucleo.revisar_carpeta(carpeta) if carpeta else (True, "")
            return {"carpeta": carpeta, "permitida": permitida, "aviso": aviso}
        if ruta == "/api/revisar-carpeta":
            permitida, aviso = nucleo.revisar_carpeta(datos.get("carpeta", ""))
            return {"permitida": permitida, "aviso": aviso,
                    "existe": os.path.isdir(datos.get("carpeta", ""))}
        if ruta == "/api/simular":
            return nucleo.ejecutar_servicio(datos["servicio"], simular=True)
        if ruta == "/api/ejecutar":
            servicio = next(s for s in nucleo.cargar_servicios() if s["id"] == datos["id"])
            registro = nucleo.ejecutar_y_anotar(servicio)
            return {"registro": registro, "servicios": servicios_con_estado()}
        if ruta == "/api/registros":
            return {"registros": nucleo.listar_registros(datos["id"])}
        if ruta == "/api/deshacer":
            with nucleo.Bloqueo():
                return nucleo.deshacer(datos["id"], datos.get("archivo"))
        if ruta == "/api/ajustes":
            ajustes = nucleo.cargar_ajustes()
            ajustes["revisar_cada_minutos"] = max(1, min(1440, int(datos["revisar_cada_minutos"])))
            nucleo.guardar_ajustes(ajustes)
            resultado = nucleo.programar_motor(ajustes["revisar_cada_minutos"])
            resultado["programacion"] = nucleo.estado_programacion()
            return resultado
        if ruta == "/api/quitar-programacion":
            resultado = nucleo.quitar_programacion()
            resultado["programacion"] = nucleo.estado_programacion()
            return resultado
        if ruta == "/api/cerrar":
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return {"ok": True}
        raise ValueError(f"Ruta desconocida: {ruta}")


def vigilar_inactividad():
    while True:
        time.sleep(30)
        if time.time() - ultima_actividad > INACTIVIDAD_SEGUNDOS:
            os._exit(0)


def main():
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    except OSError:
        # Ya hay un panel abierto: se reutiliza.
        webbrowser.open(f"http://127.0.0.1:{PUERTO}/")
        return
    threading.Thread(target=vigilar_inactividad, daemon=True).start()
    url = f"http://127.0.0.1:{PUERTO}/"
    print(f"Panel de GESTOR en {url}  (cierra esta ventana o usa 'Cerrar panel' para salir)")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
