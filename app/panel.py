"""GESTOR: panel. Abre http://127.0.0.1:8765 en el navegador para crear y editar servicios.

El panel se cierra solo cuando cierras la pestaña (tras unos minutos sin actividad),
o con el botón "Cerrar panel".
"""

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import nucleo

PUERTO = int(os.environ.get("GESTOR_PUERTO", "8765"))
TOKEN = secrets.token_urlsafe(24)
INACTIVIDAD_SEGUNDOS = 5 * 60
ultima_actividad = time.time()

# --------------------------------------------------------------------------- login

ARCHIVO_CLAVE = os.path.join(nucleo.DATOS, "credenciales.json")
ITERACIONES = 300_000
LARGO_MINIMO = 6
SESIONES = set()
intentos = {"fallos": 0, "hasta": 0.0}
candado = threading.Lock()


def hay_clave():
    return os.path.exists(ARCHIVO_CLAVE)


def _derivar(clave, sal, iteraciones):
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones)


def guardar_clave(clave):
    sal = secrets.token_bytes(16)
    nucleo.escribir_json(ARCHIVO_CLAVE, {"sal": sal.hex(), "iteraciones": ITERACIONES,
                                         "hash": _derivar(clave, sal, ITERACIONES).hex()})


def clave_correcta(clave):
    datos = nucleo.leer_json(ARCHIVO_CLAVE, None)
    if not datos:
        return False
    calculado = _derivar(clave, bytes.fromhex(datos["sal"]), int(datos["iteraciones"]))
    return hmac.compare_digest(calculado.hex(), datos["hash"])


def comprobar_con_espera(clave):
    """Tras 5 fallos seguidos, cada intento obliga a esperar más (30 s, 1 min, 2 min... hasta 15 min)."""
    with candado:
        espera = intentos["hasta"] - time.time()
        if espera > 0:
            return False, f"Demasiados intentos. Espera {int(espera) + 1} segundos."
        if clave_correcta(clave):
            intentos.update(fallos=0, hasta=0.0)
            return True, ""
        intentos["fallos"] += 1
        if intentos["fallos"] >= 5:
            intentos["hasta"] = time.time() + min(30 * 2 ** (intentos["fallos"] - 5), 900)
        return False, "Contraseña incorrecta."

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
            if not self._sesion_valida():
                with open(os.path.join(nucleo.BASE, "login.html"), "rb") as f:
                    html = f.read().replace(b"__MODO__", b"entrar" if hay_clave() else b"crear")
                return self._responder(200, html, "text/html; charset=utf-8")
            with open(os.path.join(nucleo.BASE, "panel.html"), "rb") as f:
                html = f.read().replace(b"__TOKEN__", TOKEN.encode())
            return self._responder(200, html, "text/html; charset=utf-8")
        return self._responder(404, {"error": "No encontrado"})

    def _sesion_valida(self):
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        return "gestor_sesion" in cookie and cookie["gestor_sesion"].value in SESIONES

    def _origen_valido(self):
        origen = self.headers.get("Origin")
        return origen in (f"http://127.0.0.1:{PUERTO}", f"http://localhost:{PUERTO}")

    def _login(self, ruta):
        datos = self._leer()
        clave = str(datos.get("clave", ""))
        if ruta == "/auth/crear":
            if hay_clave():
                return self._responder(400, {"error": "Ya hay una contraseña."})
            if len(clave) < LARGO_MINIMO:
                return self._responder(400, {"error": f"Usa al menos {LARGO_MINIMO} caracteres."})
            guardar_clave(clave)
        else:
            ok, mensaje = comprobar_con_espera(clave)
            if not ok:
                return self._responder(401, {"error": mensaje})
        sesion = secrets.token_urlsafe(32)
        SESIONES.add(sesion)
        cuerpo = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Set-Cookie", f"gestor_sesion={sesion}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        global ultima_actividad
        ruta = urlparse(self.path).path
        if ruta in ("/auth/entrar", "/auth/crear"):
            if not self._host_valido() or not self._origen_valido():
                return self._responder(403, {"error": "Acceso no permitido"})
            ultima_actividad = time.time()
            return self._login(ruta)
        if not self._host_valido() or self.headers.get("X-Gestor-Token") != TOKEN:
            return self._responder(403, {"error": "Acceso no permitido"})
        if not self._sesion_valida():
            return self._responder(401, {"error": "Sesión caducada: vuelve a entrar."})
        ultima_actividad = time.time()
        try:
            datos = self._leer()
            return self._responder(200, self._api(ruta, datos))
        except Exception as e:
            return self._responder(500, {"error": str(e)})

    def _api(self, ruta, datos):
        if ruta == "/api/inicio":
            return {"servicios": servicios_con_estado(), "categorias": list(nucleo.CATEGORIAS) + ["Otros"],
                    "procedencias": nucleo.PROCEDENCIAS, "pillow": nucleo.pillow_disponible(),
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
        if ruta == "/api/cambiar-clave":
            ok, mensaje = comprobar_con_espera(str(datos.get("actual", "")))
            if not ok:
                return {"ok": False, "mensaje": mensaje}
            nueva = str(datos.get("nueva", ""))
            if len(nueva) < LARGO_MINIMO:
                return {"ok": False, "mensaje": f"Usa al menos {LARGO_MINIMO} caracteres."}
            guardar_clave(nueva)
            return {"ok": True, "mensaje": "Contraseña cambiada."}
        if ruta == "/api/salir":
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            SESIONES.discard(cookie["gestor_sesion"].value)
            return {"ok": True}
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
