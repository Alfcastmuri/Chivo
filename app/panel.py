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

import aprendizaje
import nucleo
import plantillas
import mapa
import respaldo
import vencimientos

PUERTO = int(os.environ.get("GESTOR_PUERTO", "8765"))
PUERTO_RED = int(os.environ.get("GESTOR_PUERTO_RED", "8770"))  # panel para el celular (lo sirve el residente)
SOLO_EN_EL_PC = {"/api/elegir-carpeta", "/api/cerrar", "/api/abrir", "/api/quitar-programacion", "/api/ajustes"}
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


def watchdog_disponible():
    try:
        import watchdog  # noqa: F401
        return True
    except ImportError:
        return False


def primera_vez():
    ajustes = nucleo.cargar_ajustes()
    return not ajustes.get("asistente_visto") and not any(s.get("activo") for s in nucleo.cargar_servicios())


# Llamadas que pueden tardar: se muestran con barra de progreso y cronómetro en el panel.
PROCESOS_LARGOS = {"/api/simular": "Simulando", "/api/ejecutar": "Ordenando", "/api/aplanar/simular": "Sacar a la raíz (vista previa)",
                   "/api/aplanar/ejecutar": "Sacando a la raíz", "/api/espacio": "Analizando espacio",
                   "/api/duplicados/combinar": "Combinando carpetas", "/api/prueba/aprobar": "Aplicando cambios aprobados",
                   "/api/copias/ejecutar": "Copia a USB", "/api/asistente/analizar": "Analizando carpeta",
                   "/api/deshacer": "Deshaciendo", "/api/papelera/vaciar": "Vaciando papelera"}
TRABAJOS = {}  # tareas largas en segundo plano: escanear vencimientos, respaldar...


NOMBRES_TRABAJOS = {"vencimientos": "Buscando vencimientos", "respaldo": "Respaldo", "mapa": "Mapa de archivos"}


def en_segundo_plano(nombre, funcion, *args):
    if (TRABAJOS.get(nombre) or {}).get("estado") == "en marcha":
        return {"ok": False, "mensaje": "Ya está en marcha."}
    TRABAJOS[nombre] = {"estado": "en marcha", "inicio": time.strftime("%H:%M:%S")}

    def trabajo():
        try:
            if nombre == "mapa":  # el mapa anota su propio avance
                TRABAJOS[nombre] = {"estado": "terminado", "resultado": funcion(*args)}
                return
            with nucleo.proceso(NOMBRES_TRABAJOS.get(nombre.split("-")[0], nombre)):
                TRABAJOS[nombre] = {"estado": "terminado", "resultado": funcion(*args)}
        except Exception as e:
            TRABAJOS[nombre] = {"estado": "error", "error": str(e)}

    threading.Thread(target=trabajo, daemon=True).start()
    return {"ok": True}


def dashboard():
    """Todo lo que muestra la pestaña Inicio, en una sola llamada."""
    import datetime as dt
    ajustes = nucleo.cargar_ajustes()
    ahora = time.time()
    hoy = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    servicios = servicios_con_estado()
    activos = [x for x in servicios if x["servicio"].get("activo")]
    estado_total = nucleo.cargar_estado()
    totales = {"archivos": 0, "bytes_liberados": 0}
    for e in estado_total.values():
        if isinstance(e, dict) and e.get("totales"):
            totales["archivos"] += e["totales"].get("archivos", 0)
            totales["bytes_liberados"] += e["totales"].get("bytes_liberados", 0)
    papelera = nucleo.listar_papelera()
    venc = [v for v in vencimientos.lista()["vencimientos"] if v["dias"] is not None and v["dias"] <= 60][:6]
    respaldos = [{"nombre": r.get("nombre"), "destino": r.get("destino"),
                  **(respaldo.estado().get(r["id"]) or {})} for r in respaldo.lista()]
    return {
        "version": nucleo.VERSION,
        "estado": {"pausado": bool(ajustes.get("pausado")), "detenido": bool(ajustes.get("detenido")),
                   "no_molestar": nucleo.motivo_no_molestar(), "programacion": nucleo.estado_programacion(),
                   "minutos": ajustes.get("revisar_cada_minutos"), "residente": nucleo.residente_activo(),
                   "windows": nucleo.ES_WINDOWS},
        "hoy": nucleo.resumen_desde(hoy),
        "semana": nucleo.resumen_desde(ahora - 7 * 86400),
        "totales": totales,
        "servicios": {"total": len(servicios), "activos": len(activos),
                      "en_prueba": [{"id": x["servicio"]["id"], "nombre": x["servicio"].get("nombre"),
                                     "n": (x.get("propuestas") or {}).get("n", 0)}
                                    for x in servicios if x["servicio"].get("modo_prueba")],
                      "proximas": sorted([{"id": x["servicio"]["id"], "nombre": x["servicio"].get("nombre"),
                                           "proxima": x["proxima"]} for x in activos if x["proxima"]],
                                         key=lambda x: x["proxima"])[:4],
                      "con_errores": [{"id": x["servicio"]["id"], "nombre": x["servicio"].get("nombre"),
                                       "errores": x["ultimo_resultado"]["errores"]}
                                      for x in servicios if (x.get("ultimo_resultado") or {}).get("errores")]},
        "aprendido": aprendizaje.propuestas()[:3],
        "vencimientos": venc,
        "discos": nucleo.unidades_fijas(), "umbral": ajustes.get("umbral_disco", 10),
        "papelera": {"n": len(papelera), "bytes": sum(p.get("bytes", 0) for p in papelera)},
        "respaldos": respaldos,
        "ultimos": nucleo.ultimos_movimientos(8),
    }


def limpiar_tema(t):
    """Colores del panel: {paleta, modo, propias: [{nombre, colores: [#hex x5]}]}."""
    import re
    es_hex = re.compile(r"#[0-9a-fA-F]{6}").fullmatch
    propias = []
    for p in (t.get("propias") or [])[:30]:
        colores = [c for c in (p.get("colores") or []) if isinstance(c, str) and es_hex(c)][:5]
        if len(colores) == 5:
            propias.append({"nombre": str(p.get("nombre") or "Mi combinación")[:40], "colores": colores})
    return {"paleta": str(t.get("paleta") or "")[:60],
            "modo": t.get("modo") if t.get("modo") in ("auto", "claro", "oscuro") else "auto",
            "propias": propias, "cuaderno": bool(t.get("cuaderno"))}


def qr_svg(texto):
    """Código QR en SVG (para abrir el panel en el celular apuntando con la cámara)."""
    if not texto:
        return ""
    try:
        import io
        import segno
    except ImportError:
        return ""
    salida = io.BytesIO()
    segno.make(texto, error="m").save(salida, kind="svg", scale=6, border=2, dark="#111111", light="#ffffff",
                                      xmldecl=False)
    return salida.getvalue().decode()


def ip_local():
    """La IP de este equipo en la red de casa (sin enviar nada: el socket UDP solo elige la ruta)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


TRABAJO_DUPLICADOS = {"estado": "inactivo"}


def iniciar_duplicados(carpetas, min_kb):
    if TRABAJO_DUPLICADOS.get("estado") == "buscando":
        return {"ok": False, "mensaje": "Ya hay una búsqueda en marcha."}
    TRABAJO_DUPLICADOS.clear()
    TRABAJO_DUPLICADOS.update(estado="buscando", progreso={}, grupos=[], cancelar=False,
                              inicio=time.strftime("%H:%M:%S"))

    def progreso(**k):
        TRABAJO_DUPLICADOS["progreso"] = k

    def trabajo():
        try:
            with nucleo.proceso("Buscando duplicados"):
                _trabajo()
        except Exception as e:
            TRABAJO_DUPLICADOS.update(estado="error", error=str(e))

    def _trabajo():
        if True:
            por_carpeta = {}
            grupos = nucleo.buscar_duplicados(carpetas, min_kb * 1024, progreso,
                                              lambda: TRABAJO_DUPLICADOS.get("cancelar"), por_carpeta)
            TRABAJO_DUPLICADOS["carpetas"] = nucleo.carpetas_que_se_repiten(grupos, por_carpeta)
            TRABAJO_DUPLICADOS["_todos"] = grupos
            TRABAJO_DUPLICADOS.update(grupos=grupos[:500], total_grupos=len(grupos),
                                      recuperable=sum(g["recuperable"] for g in grupos),
                                      estado="cancelado" if TRABAJO_DUPLICADOS.get("cancelar") else "terminado")

    threading.Thread(target=trabajo, daemon=True).start()
    return {"ok": True}


def servicios_con_estado():
    estado = nucleo.cargar_estado()
    resultado = []
    for s in nucleo.cargar_servicios():
        e = estado.get(s["id"], {})
        resultado.append({"servicio": s, "ultima": e.get("ultima"),
                          "ultimo_resultado": e.get("ultimo_resultado"),
                          "proxima": nucleo.proxima_ejecucion(s, e),
                          "propuestas": e.get("propuestas") if s.get("modo_prueba") else None})
    return resultado


class Manejador(BaseHTTPRequestHandler):
    en_red = False

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
        if self.en_red and ruta in SOLO_EN_EL_PC:
            return self._responder(403, {"error": "Esto solo se puede hacer desde el PC."})
        ultima_actividad = time.time()
        try:
            datos = self._leer()
            if ruta in PROCESOS_LARGOS:
                with nucleo.proceso(PROCESOS_LARGOS[ruta]):
                    return self._responder(200, self._api(ruta, datos))
            return self._responder(200, self._api(ruta, datos))
        except Exception as e:
            return self._responder(500, {"error": str(e)})

    def _api(self, ruta, datos):
        if ruta == "/api/inicio":
            return {"servicios": servicios_con_estado(), "categorias": list(nucleo.CATEGORIAS) + ["Otros"],
                    "procedencias": nucleo.PROCEDENCIAS, "pillow": nucleo.pillow_disponible(),
                    "pypdf": nucleo.pypdf_disponible(), "watchdog": watchdog_disponible(),
                    "carpetas_rapidas": nucleo.carpetas_rapidas(), "ajustes": nucleo.cargar_ajustes(),
                    "programacion": nucleo.estado_programacion(), "windows": nucleo.ES_WINDOWS,
                    "residente": nucleo.residente_activo(), "primera_vez": primera_vez(),
                    "version": nucleo.VERSION, "discos": nucleo.unidades_fijas(), "aprendido": len(aprendizaje.propuestas()),
                    "en_red": self.en_red}
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
            nucleo.lanzar_residente()
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
        if ruta == "/api/preferencias":
            ajustes = nucleo.cargar_ajustes()
            for clave in ("notificaciones", "icono_bandeja", "pausado"):
                if clave in datos:
                    ajustes[clave] = bool(datos[clave])
            if datos.get("papelera") in ("gestor", "windows"):
                ajustes["papelera"] = datos["papelera"]
            if "retencion_dias" in datos:
                ajustes["retencion_dias"] = max(1, min(365, int(datos["retencion_dias"])))
            if "mis_rfc" in datos:
                ajustes["mis_rfc"] = str(datos["mis_rfc"]).upper()
            if "umbral_disco" in datos:
                ajustes["umbral_disco"] = max(0, min(50, int(datos["umbral_disco"])))
            if "aviso_semanal" in datos:
                ajustes["aviso_semanal"] = bool(datos["aviso_semanal"])
            if isinstance(datos.get("tema"), dict):
                ajustes["tema"] = limpiar_tema(datos["tema"])
            if isinstance(datos.get("no_molestar"), dict):
                nm = datos["no_molestar"]
                ajustes["no_molestar"] = {"bateria": bool(nm.get("bateria")),
                                          "pantalla_completa": bool(nm.get("pantalla_completa")),
                                          "horas": bool(nm.get("horas")),
                                          "desde": str(nm.get("desde") or "22:00")[:5],
                                          "hasta": str(nm.get("hasta") or "07:00")[:5]}
            for clave in ("acceso_red", "aprender", "vencimientos", "renombrar_facturas"):
                if clave in datos:
                    ajustes[clave] = bool(datos[clave])
            if "detenido" in datos:
                ajustes["detenido"] = bool(datos["detenido"])
            if "asistente_visto" in datos:
                ajustes["asistente_visto"] = True
            nucleo.guardar_ajustes(ajustes)
            if ajustes.get("detenido"):
                nucleo.cerrar_residente()
            else:
                nucleo.lanzar_residente()
            return {"ok": True, "ajustes": ajustes}
        if ruta == "/api/estadisticas":
            estado = nucleo.cargar_estado()
            nombres = {s["id"]: s.get("nombre", "") for s in nucleo.cargar_servicios()}
            nombres["_duplicados"] = "Buscador de duplicados"
            filas = [{"nombre": nombres[sid], **e["totales"]} for sid, e in estado.items()
                     if sid in nombres and isinstance(e, dict) and e.get("totales")]
            copias = estado.get("_copias", {})
            return {"servicios": filas, "copias": copias,
                    "papelera": {"archivos": len(nucleo.listar_papelera()),
                                 "bytes": sum(e.get("bytes", 0) for e in nucleo.listar_papelera())}}
        if ruta == "/api/duplicados/iniciar":
            return iniciar_duplicados(datos.get("carpetas", []), int(datos.get("min_kb", 100)))
        if ruta == "/api/duplicados/estado":
            return {k: v for k, v in TRABAJO_DUPLICADOS.items() if k not in ("cancelar", "_todos")}
        if ruta == "/api/duplicados/de-carpeta":
            # Las copias que hay en "quitar" de archivos que también están en "conservar" (nunca la última copia).
            conservar, quitar_de = datos["conservar"], datos["quitar"]
            rutas, total = [], 0
            for g in TRABAJO_DUPLICADOS.get("_todos", []):
                en_conservar = [r for r in g["archivos"] if os.path.dirname(r) == conservar]
                en_quitar = [r for r in g["archivos"] if os.path.dirname(r) == quitar_de]
                if en_conservar and en_quitar:
                    rutas += en_quitar
                    total += g["bytes"] * len(en_quitar)
            return {"rutas": rutas, "bytes": total}
        if ruta == "/api/duplicados/combinar":
            return nucleo.combinar_carpetas(datos["conservar"], datos["vaciar"], simular=bool(datos.get("simular", True)))
        if ruta == "/api/procesos":
            return {"procesos": nucleo.procesos(), "ahora": time.time()}
        if ruta == "/api/mapa":
            return mapa.estado()
        if ruta == "/api/mapa/guardar":
            ajustes = nucleo.cargar_ajustes()
            m = {**mapa.config(), **{k: v for k, v in datos.items() if k in ("activo", "carpetas")}}
            m["carpetas"] = [str(c) for c in m.get("carpetas") or [] if c][:50]
            ajustes["mapa_archivos"] = m
            nucleo.guardar_ajustes(ajustes)
            if not m["activo"]:
                mapa.desactivar()
            nucleo.lanzar_residente()
            return mapa.estado()
        if ruta == "/api/mapa/escanear":
            return en_segundo_plano("mapa", mapa.escanear)
        if ruta == "/api/mapa/buscar":
            return {"archivos": mapa.buscar(datos.get("texto", ""))}
        if ruta == "/api/historial":
            filas = nucleo.bd.movimientos(datos.get("texto", ""), datos.get("desde"), datos.get("hasta"),
                                          limite=int(datos.get("limite") or 300), recientes_primero=True)
            return {"movimientos": filas, "total": nucleo.bd.total_movimientos()}
        if ruta == "/api/qr":
            return {"svg": qr_svg(datos.get("texto", ""))}
        if ruta == "/api/duplicados/cancelar":
            TRABAJO_DUPLICADOS["cancelar"] = True
            return {"ok": True}
        if ruta == "/api/duplicados/quitar":
            quitados, bytes_liberados, fallos = 0, 0, []
            for ruta_archivo in datos.get("rutas", []):
                try:
                    tam = os.path.getsize(ruta_archivo)
                    nucleo.quitar(ruta_archivo, "duplicado")
                    quitados, bytes_liberados = quitados + 1, bytes_liberados + tam
                except OSError as e:
                    fallos.append(f"{ruta_archivo}: {e}")
            nucleo.anotar_liberado(bytes_liberados, quitados)
            return {"ok": True, "quitados": quitados, "bytes": bytes_liberados, "fallos": fallos}
        if ruta == "/api/papelera":
            return {"entradas": nucleo.listar_papelera(), "ajustes": nucleo.cargar_ajustes()}
        if ruta == "/api/papelera/restaurar":
            hechos, fallos = [], []
            for pid in datos.get("ids", []):
                try:
                    hechos.append(nucleo.restaurar(pid))
                except OSError as e:
                    fallos.append(str(e))
            return {"ok": True, "restaurados": len(hechos), "fallos": fallos}
        if ruta == "/api/papelera/vaciar":
            return nucleo.purgar_papelera(todo=bool(datos.get("todo")), ids=datos.get("ids"))
        if ruta == "/api/copias":
            return {"copias": nucleo.cargar_ajustes().get("copias", []), "unidades": nucleo.unidades_conectadas(),
                    "estado": nucleo.cargar_estado().get("_copias", {})}
        if ruta == "/api/copias/guardar":
            ajustes = nucleo.cargar_ajustes()
            copias = datos.get("copias", [])
            for c in copias:
                c.setdefault("id", nucleo.nuevo_id())
            ajustes["copias"] = copias
            nucleo.guardar_ajustes(ajustes)
            nucleo.lanzar_residente()
            return {"ok": True, "copias": copias}
        if ruta == "/api/copias/ejecutar":
            copia = next(c for c in nucleo.cargar_ajustes().get("copias", []) if c["id"] == datos["id"])
            return nucleo.ejecutar_copia(copia)
        if ruta == "/api/dashboard":
            return dashboard()
        if ruta == "/api/aprendizaje":
            return {"propuestas": aprendizaje.propuestas()}
        if ruta == "/api/aprendizaje/aceptar":
            servicio = aprendizaje.aceptar(datos["id"])
            nucleo.lanzar_residente()
            return {"ok": True, "id": servicio["id"], "propuestas": aprendizaje.propuestas(),
                    "servicios": servicios_con_estado()}
        if ruta == "/api/aprendizaje/descartar":
            aprendizaje.descartar(datos["id"])
            return {"ok": True, "propuestas": aprendizaje.propuestas()}
        if ruta == "/api/vencimientos":
            return dict(vencimientos.lista(), trabajo=TRABAJOS.get("vencimientos"),
                        carpetas=vencimientos.carpetas_a_revisar(), tipos=[t for t, _ in vencimientos.TIPOS])
        if ruta == "/api/vencimientos/escanear":
            return en_segundo_plano("vencimientos", vencimientos.escanear, 3600)
        if ruta == "/api/vencimientos/cambiar":
            vencimientos.cambiar(datos["clave"], datos.get("fecha"), datos.get("ignorar"), datos.get("borrar"))
            return vencimientos.lista()
        if ruta == "/api/vencimientos/agregar":
            vencimientos.agregar(datos.get("nombre", ""), datos["fecha"], datos.get("tipo", ""))
            return vencimientos.lista()
        if ruta == "/api/respaldos":
            return {"respaldos": respaldo.lista(), "estado": respaldo.estado(),
                    "sugeridos": respaldo.destinos_sugeridos(), "documentos": nucleo.carpeta_conocida("Documentos"),
                    "trabajos": {k[9:]: v for k, v in TRABAJOS.items() if k.startswith("respaldo-")}}
        if ruta == "/api/respaldos/guardar":
            lista = []
            for r in datos.get("respaldos", []):
                problema = respaldo.validar(r.get("origen"), r.get("destino"))
                if problema:
                    return {"ok": False, "mensaje": problema}
                lista.append({"id": r.get("id") or nucleo.nuevo_id(), "nombre": str(r.get("nombre") or "Respaldo"),
                              "origen": os.path.normpath(r["origen"]), "destino": os.path.normpath(r["destino"]),
                              "cada_horas": max(1, int(r.get("cada_horas") or 24)),
                              "dias_versiones": max(1, int(r.get("dias_versiones") or 90)),
                              "activo": bool(r.get("activo", True))})
            ajustes = nucleo.cargar_ajustes()
            ajustes["respaldos"] = lista
            nucleo.guardar_ajustes(ajustes)
            avisos = [a for a in (respaldo.aviso_nube(r["origen"], r["destino"]) for r in lista) if a]
            return {"ok": True, "respaldos": lista, "avisos": avisos}
        if ruta == "/api/respaldos/ejecutar":
            r = next(x for x in respaldo.lista() if x["id"] == datos["id"])
            return en_segundo_plano("respaldo-" + r["id"], respaldo.ejecutar, r)
        if ruta == "/api/respaldos/versiones":
            r = next(x for x in respaldo.lista() if x["id"] == datos["id"])
            return {"versiones": respaldo.buscar_versiones(r["destino"], datos.get("texto", ""))}
        if ruta == "/api/respaldos/restaurar":
            r = next(x for x in respaldo.lista() if x["id"] == datos["id"])
            return {"ok": True, "ruta": respaldo.restaurar_version(r, datos["ruta"])}
        if ruta == "/api/red":
            url = f"http://{ip_local()}:{PUERTO_RED}/"
            return {"activo": bool(nucleo.cargar_ajustes().get("acceso_red")), "hay_clave": hay_clave(),
                    "url": url, "qr": qr_svg(url), "residente": nucleo.residente_activo()}
        if ruta in ("/api/aplanar/simular", "/api/aplanar/ejecutar"):
            opciones = {k: datos[k] for k in ("nombre_con_carpeta", "borrar_vacias", "identicos") if k in datos}
            return nucleo.aplanar(datos.get("carpeta", ""), simular=ruta.endswith("simular"), **opciones)
        if ruta == "/api/aplanar/deshacer":
            with nucleo.Bloqueo():
                return nucleo.deshacer(nucleo.ID_APLANAR)
        if ruta == "/api/plantillas":
            return {"plantillas": plantillas.catalogo(int(datos.get("dias") or 14)),
                    "documentos": plantillas.mapa_documentos()[0]}
        if ruta == "/api/plantillas/crear":
            servicio = plantillas.crear(datos["clave"], datos.get("indices"), datos.get("origenes"),
                                        int(datos.get("dias") or 14), datos.get("modo_prueba", True))
            nucleo.lanzar_residente()
            return {"ok": True, "id": servicio["id"], "servicios": servicios_con_estado()}
        if ruta == "/api/prueba/aprobar":
            registro = nucleo.aprobar_prueba(datos["id"])
            return {"registro": registro, "servicios": servicios_con_estado()}
        if ruta == "/api/prueba/terminar":
            nucleo.terminar_prueba(datos["id"], datos.get("activar", True))
            return {"ok": True, "servicios": servicios_con_estado()}
        if ruta == "/api/prueba/revisar":
            servicio = next(s for s in nucleo.cargar_servicios() if s["id"] == datos["id"])
            nucleo.proponer(servicio, motivo="desde el panel")
            return {"servicios": servicios_con_estado()}
        if ruta == "/api/buscar":
            return nucleo.buscar_movidos(datos.get("texto", ""), datos.get("desde"), datos.get("hasta"))
        if ruta == "/api/abrir":
            nucleo.abrir_en_explorador(datos.get("ruta", ""))
            return {"ok": True}
        if ruta == "/api/espacio":
            return nucleo.analizar_espacio(int(datos.get("min_mb") or 50))
        if ruta == "/api/espacio/papelera":
            rutas = set(datos.get("rutas") or [])
            permitidas = [os.path.normpath(p) for p in nucleo.carpetas_rapidas().values()]
            hechos, errores, liberado = 0, [], 0
            for r in rutas:
                if not any(nucleo._dentro_de(r, c) for c in permitidas) or not os.path.isfile(r):
                    errores.append(f"{r}: fuera de tus carpetas")
                    continue
                try:
                    tam = os.path.getsize(r)
                    nucleo.quitar(r, "liberar espacio")
                    hechos += 1
                    liberado += tam
                except Exception as e:
                    errores.append(f"{r}: {e}")
            nucleo.anotar_liberado(liberado, hechos)
            return {"ok": True, "hechos": hechos, "errores": errores, "liberado": liberado}
        if ruta == "/api/asistente/analizar":
            return nucleo.analizar_carpeta(datos.get("carpeta") or nucleo.carpeta_conocida("Descargas"))
        if ruta == "/api/asistente/crear":
            servicio = nucleo.crear_desde_asistente(datos["carpeta"], datos.get("reglas", []), datos.get("limpiar"))
            return {"ok": True, "id": servicio["id"], "servicios": servicios_con_estado()}
        if ruta == "/api/exportar":
            ajustes = nucleo.cargar_ajustes()
            return {"gestor": 1, "exportado": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "servicios": nucleo.cargar_servicios(),
                    "ajustes": {k: v for k, v in ajustes.items() if k not in ("pausado",)}}
        if ruta == "/api/importar":
            datos_importados = datos.get("datos") or {}
            if datos_importados.get("gestor") != 1 or not isinstance(datos_importados.get("servicios"), list):
                return {"ok": False, "mensaje": "Ese archivo no es una configuración de GESTOR."}
            nuevos = datos_importados["servicios"]
            if datos.get("modo") == "reemplazar":
                servicios = nuevos
            else:
                por_id = {s["id"]: s for s in nucleo.cargar_servicios()}
                por_id.update({s["id"]: s for s in nuevos})
                servicios = list(por_id.values())
            for s_ in servicios:
                s_["activo"] = bool(s_.get("activo")) and datos.get("mantener_activos", False)
            nucleo.guardar_servicios(servicios)
            if datos_importados.get("ajustes"):
                ajustes = nucleo.cargar_ajustes()
                ajustes.update({k: v for k, v in datos_importados["ajustes"].items()
                                if k in ("revisar_cada_minutos", "notificaciones", "icono_bandeja",
                                         "papelera", "retencion_dias", "copias")})
                nucleo.guardar_ajustes(ajustes)
            return {"ok": True, "mensaje": f"{len(nuevos)} servicios importados (desactivados, revísalos).",
                    "servicios": servicios_con_estado()}
        if ruta == "/api/cerrar":
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return {"ok": True}
        raise ValueError(f"Ruta desconocida: {ruta}")


def vigilar_inactividad():
    while True:
        time.sleep(2)
        if time.time() - ultima_actividad > INACTIVIDAD_SEGUNDOS or nucleo.debo_cerrarme():
            os._exit(0)


class ManejadorRed(Manejador):
    """El mismo panel, desde otros equipos de la red de casa. Siempre con contraseña."""
    en_red = True

    def _host_valido(self):
        import ipaddress
        try:
            cliente = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return (cliente.is_private or cliente.is_loopback) and bool(self.headers.get("Host")) and hay_clave()

    def _origen_valido(self):
        return self.headers.get("Origin") == f'http://{self.headers.get("Host")}'


def servidor_en_red():
    return ThreadingHTTPServer(("0.0.0.0", PUERTO_RED), ManejadorRed)


def main():
    try:
        relevo = nucleo.tomar_el_relevo()  # si hay otra versión de GESTOR abierta, se cierra
    except Exception:
        relevo = {"cerrados": 0}
    servidor = None
    for _ in range(8 if relevo["cerrados"] else 1):  # el puerto tarda un momento en quedar libre
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
            break
        except OSError:
            time.sleep(1)
    if not servidor:
        # Ya hay un panel de esta versión abierto: se reutiliza.
        webbrowser.open(f"http://127.0.0.1:{PUERTO}/")
        return
    try:
        nucleo.lanzar_residente()
    except Exception:
        pass
    threading.Thread(target=vigilar_inactividad, daemon=True).start()
    url = f"http://127.0.0.1:{PUERTO}/"
    print(f"Panel de GESTOR en {url}  (cierra esta ventana o usa 'Cerrar panel' para salir)")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
