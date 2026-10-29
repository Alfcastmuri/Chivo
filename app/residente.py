"""GESTOR: proceso residente. Icono junto al reloj, notificaciones y modo "al instante".

Consume muy poco: espera eventos del sistema de archivos (watchdog) y revisa cada pocos
segundos si hay avisos nuevos o cambios en la configuración. Solo hay uno a la vez.

  gestor.py --residente              con icono en la bandeja (si pystray está disponible)
  gestor.py --residente --sin-icono  solo el modo al instante, sin icono
"""

import datetime as dt
import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

import nucleo

QUIETUD_SEGUNDOS = 8      # tras el último cambio en una carpeta, se espera esto antes de actuar
ESPERA_ARCHIVO = 5        # un archivo tiene que llevar esto sin modificarse para moverlo
REVISION_SEGUNDOS = 2


def registrar_error():
    with open(nucleo.ARCHIVO_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"--- {dt.datetime.now().isoformat(timespec='seconds')} residente\n")
        f.write(traceback.format_exc())


def servicios_al_instante():
    return [s for s in nucleo.cargar_servicios()
            if s.get("activo") and (s.get("horario") or {}).get("tipo") == "instante"]


class Vigilante:
    """Vigila las carpetas de los servicios "al instante" y los ejecuta cuando hay cambios."""

    def __init__(self):
        self.observador = None
        self.firma = None
        self.pendientes = {}        # id de servicio -> momento del último cambio
        self.candado = threading.Lock()
        self.disponible = True
        try:
            import watchdog  # noqa: F401
        except ImportError:
            self.disponible = False

    def marcar(self, servicio_id):
        with self.candado:
            self.pendientes[servicio_id] = time.time()

    def recargar(self):
        servicios = servicios_al_instante()
        firma = json.dumps([(s["id"], s.get("origenes"), s.get("subcarpetas")) for s in servicios])
        if firma == self.firma:
            return
        self.firma = firma
        self.detener()
        if not servicios or not self.disponible:
            return
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        vigilante = self

        class Manejador(FileSystemEventHandler):
            def __init__(self, servicio_id):
                self.servicio_id = servicio_id

            def on_any_event(self, evento):
                if evento.is_directory or evento.event_type not in ("created", "moved", "modified", "closed"):
                    return
                vigilante.marcar(self.servicio_id)

        self.observador = Observer()
        for s in servicios:
            for origen in s.get("origenes", []):
                if os.path.isdir(origen) and nucleo.revisar_carpeta(origen)[0]:
                    self.observador.schedule(Manejador(s["id"]), origen, recursive=bool(s.get("subcarpetas")))
            self.marcar(s["id"])  # al arrancar, ordena lo que llegó mientras estaba apagado
        self.observador.start()

    def detener(self):
        if self.observador:
            self.observador.stop()
            self.observador.join(timeout=5)
            self.observador = None

    def atender(self):
        if not self.pendientes:
            return
        if nucleo.cargar_ajustes().get("pausado") or nucleo.motivo_no_molestar():
            return  # se queda pendiente y se ordena cuando deje de molestar
        ahora = time.time()
        with self.candado:
            listos = [sid for sid, t in self.pendientes.items() if ahora - t >= QUIETUD_SEGUNDOS]
            for sid in listos:
                del self.pendientes[sid]
        for sid in listos:
            servicio = next((s for s in servicios_al_instante() if s["id"] == sid), None)
            if servicio:
                try:
                    nucleo.ejecutar_y_anotar(servicio, motivo="al instante", esperar_segundos=ESPERA_ARCHIVO)
                except Exception:
                    registrar_error()


class Aprendiz:
    """Vigila Documentos para "aprender de ti": qué archivos mueves a mano y a qué carpeta."""

    ESPERA = 60          # se espera a que GESTOR anote sus propios movimientos antes de juzgar
    PENSAR_CADA = 300

    def __init__(self):
        self.observador = None
        self.carpeta = None
        self.eventos = []    # (momento, destino, origen)
        self.candado = threading.Lock()
        self.ultimo_pensar = 0
        self.observados = 0

    def recargar(self):
        activo = nucleo.cargar_ajustes().get("aprender", True) and not nucleo.cargar_ajustes().get("detenido")
        carpeta = nucleo.carpeta_conocida("Documentos") if activo else None
        if carpeta == self.carpeta:
            return
        self.detener()
        self.carpeta = carpeta
        if not carpeta or not os.path.isdir(carpeta):
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return
        aprendiz = self

        class Manejador(FileSystemEventHandler):
            def on_created(self, evento):
                if not evento.is_directory:
                    aprendiz.anotar(evento.src_path, None)

            def on_moved(self, evento):
                if not evento.is_directory:
                    aprendiz.anotar(evento.dest_path, evento.src_path)

        self.observador = Observer()
        self.observador.schedule(Manejador(), carpeta, recursive=True)
        self.observador.start()

    def anotar(self, destino, origen):
        with self.candado:
            if len(self.eventos) < 500:
                self.eventos.append((time.time(), destino, origen))

    def atender(self):
        import aprendizaje
        ahora = time.time()
        with self.candado:
            listos = [e for e in self.eventos if ahora - e[0] >= self.ESPERA]
            self.eventos = [e for e in self.eventos if ahora - e[0] < self.ESPERA]
        for _, destino, origen in listos:
            if os.path.isfile(destino) and aprendizaje.observar(destino, origen):
                self.observados += 1
        if self.observados and ahora - self.ultimo_pensar >= self.PENSAR_CADA:
            self.ultimo_pensar = ahora
            self.observados = 0
            aprendizaje.pensar()

    def detener(self):
        if self.observador:
            self.observador.stop()
            self.observador.join(timeout=5)
            self.observador = None


class PanelEnRed:
    """El panel en la red de casa (para el celular). Solo si se activa en Ajustes y hay contraseña."""

    def __init__(self):
        self.servidor = None

    def recargar(self):
        import panel
        quiere = bool(nucleo.cargar_ajustes().get("acceso_red")) and panel.hay_clave()
        if quiere and not self.servidor:
            try:
                self.servidor = panel.servidor_en_red()
                threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
            except OSError:
                self.servidor = None
        elif not quiere and self.servidor:
            self.detener()

    def detener(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
            self.servidor = None


class Bandeja:
    """Icono junto al reloj con menú y notificaciones. Necesita pystray y Pillow."""

    def __init__(self, al_salir):
        import pystray
        from PIL import Image, ImageDraw

        self.pystray = pystray
        imagen = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(imagen)
        d.rounded_rectangle((4, 14, 60, 56), radius=8, fill=(47, 111, 222, 255))
        d.rounded_rectangle((4, 8, 30, 22), radius=5, fill=(47, 111, 222, 255))
        d.rectangle((16, 30, 48, 34), fill=(255, 255, 255, 255))
        d.rectangle((16, 40, 40, 44), fill=(255, 255, 255, 255))
        self.al_salir = al_salir
        self.icono = pystray.Icon("GESTOR", imagen, "GESTOR", menu=self._menu())

    def _menu(self):
        p = self.pystray

        def servicios_menu():
            elementos = [p.MenuItem(s.get("nombre", "Sin nombre"), self._ejecutar(s["id"]))
                         for s in nucleo.cargar_servicios() if s.get("activo")]
            return elementos or [p.MenuItem("No hay servicios activos", None, enabled=False)]

        return p.Menu(
            p.MenuItem("Abrir panel", self._abrir_panel, default=True),
            p.MenuItem("Ejecutar ahora", p.Menu(servicios_menu)),
            p.MenuItem(lambda _: "Reanudar" if nucleo.cargar_ajustes().get("pausado") else "Pausar todo",
                       self._pausar),
            p.MenuItem("Notificaciones", self._notificaciones,
                       checked=lambda _: nucleo.cargar_ajustes().get("notificaciones", True)),
            p.Menu.SEPARATOR,
            p.MenuItem("Cerrar GESTOR (detener todo)", self._salir),
        )

    def _abrir_panel(self, *_):
        import subprocess
        if nucleo.EMPAQUETADO:
            comando = [sys.executable]
        else:
            comando = [nucleo._pythonw(), os.path.join(nucleo.BASE, "gestor.py")]
        subprocess.Popen(comando, creationflags=0x08000000 if nucleo.ES_WINDOWS else 0)

    def _ejecutar(self, servicio_id):
        def accion(*_):
            servicio = next((s for s in nucleo.cargar_servicios() if s["id"] == servicio_id), None)
            if servicio:
                threading.Thread(target=self._ejecutar_hilo, args=(servicio,), daemon=True).start()
        return accion

    def _ejecutar_hilo(self, servicio):
        try:
            r = nucleo.ejecutar_y_anotar(servicio, motivo="desde la bandeja")
            if not r["operaciones"] and not r["errores"]:
                self.notificar(servicio.get("nombre", "GESTOR"), "No había nada que ordenar.")
        except Exception as e:
            self.notificar("GESTOR", str(e))

    def _pausar(self, *_):
        ajustes = nucleo.cargar_ajustes()
        ajustes["pausado"] = not ajustes.get("pausado")
        nucleo.guardar_ajustes(ajustes)
        self.notificar("GESTOR", "En pausa: no se ordenará nada." if ajustes["pausado"] else "Funcionando de nuevo.")

    def _notificaciones(self, *_):
        ajustes = nucleo.cargar_ajustes()
        ajustes["notificaciones"] = not ajustes.get("notificaciones", True)
        nucleo.guardar_ajustes(ajustes)

    def _salir(self, *_):
        # Detenido: el motor no vuelve a abrir el icono ni ordena nada hasta que lo enciendas en el panel.
        ajustes = nucleo.cargar_ajustes()
        ajustes["detenido"] = True
        nucleo.guardar_ajustes(ajustes)
        self.icono.stop()
        self.al_salir()

    def notificar(self, titulo, texto):
        try:
            self.icono.notify(texto, titulo)
        except Exception:
            pass

    def actualizar(self):
        pausado = nucleo.cargar_ajustes().get("pausado")
        self.icono.title = "GESTOR (en pausa)" if pausado else "GESTOR"
        self.icono.update_menu()


def main(args):
    # Un solo residente a la vez: el puerto hace de cerrojo y permite saber si está en marcha.
    try:
        nucleo.tomar_el_relevo()  # si hay otra versión abierta, se cierra y esta ocupa su lugar
    except Exception:
        registrar_error()
    cerrojo = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for intento in range(10):
        try:
            cerrojo.bind(("127.0.0.1", nucleo.PUERTO_RESIDENTE))
            cerrojo.listen(5)
            break
        except OSError:
            if intento == 9 or not nucleo.EMPAQUETADO:
                return
            time.sleep(1)
    threading.Thread(target=lambda: [c.close() for c, _ in iter(cerrojo.accept, None)], daemon=True).start()
    try:
        with open(nucleo.ARCHIVO_PID_RESIDENTE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    vigilante = Vigilante()
    aprendiz = Aprendiz()
    en_red = PanelEnRed()
    import mapa
    vigia = mapa.Vigia()
    salir = threading.Event()
    bandeja = None
    if "--sin-icono" not in args and nucleo.cargar_ajustes().get("icono_bandeja", True):
        try:
            bandeja = Bandeja(salir.set)
        except Exception:
            bandeja = None  # sin pystray o sin escritorio: sigue sin icono

    def bucle():
        posicion = os.path.getsize(nucleo.ARCHIVO_AVISOS) if os.path.exists(nucleo.ARCHIVO_AVISOS) else 0
        ultima_firma, ultima_recarga = None, 0
        unidades_antes = None
        while not salir.is_set():
            try:
                ahora = time.time()
                if nucleo.debo_cerrarme():
                    salir.set()
                    break
                if ahora - ultima_recarga >= 10:
                    ultima_recarga = ahora
                    vigilante.recargar()
                    aprendiz.recargar()
                    en_red.recargar()
                    vigia.recargar()
                    if not nucleo.necesita_residente():
                        salir.set()
                        break
                    # Copias a USB: en cuanto se conecta la unidad.
                    if not nucleo.cargar_ajustes().get("pausado"):
                        pendientes, unidades_antes = nucleo.copias_pendientes(unidades_antes)
                        for copia in pendientes:
                            threading.Thread(target=nucleo.ejecutar_copia, args=(copia,), daemon=True).start()
                    if bandeja:
                        firma = json.dumps(nucleo.cargar_ajustes(), sort_keys=True)
                        if firma != ultima_firma:
                            ultima_firma = firma
                            bandeja.actualizar()
                vigilante.atender()
                aprendiz.atender()
                vigia.atender()
                avisos, posicion = nucleo.leer_avisos_desde(posicion)
                if bandeja:
                    for a in avisos[-3:]:
                        bandeja.notificar(a["titulo"], a["texto"])
            except Exception:
                registrar_error()
            salir.wait(REVISION_SEGUNDOS)
        vigilante.detener()
        aprendiz.detener()
        en_red.detener()
        vigia.detener()
        if bandeja:
            bandeja.icono.stop()

    hilo = threading.Thread(target=bucle, daemon=True)
    hilo.start()
    if bandeja:
        bandeja.icono.run()  # bloquea hasta "Salir"; en Windows el icono necesita el hilo principal
        salir.set()
    hilo.join()
    cerrojo.close()


def main_seguro(args):
    try:
        main(args)
    except Exception:
        registrar_error()
