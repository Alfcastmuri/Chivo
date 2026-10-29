"""GESTOR: mapa de archivos. Sabe dónde está cada uno de tus archivos en todo momento.

- Un recorrido completo al activarlo (y uno de repaso cada día) llena la tabla «archivos» de gestor.db.
- Después, el proceso residente escucha los cambios del disco (watchdog) y la actualiza al instante:
  archivos nuevos, renombrados, movidos o borrados. Lo que mueves tú también queda en el historial.
- Se activa y desactiva en el panel (Buscar → Mapa de archivos). Al desactivarlo se borra el mapa.
"""

import os
import threading
import time

import bd
import nucleo

POR_DEFECTO = {"activo": True, "carpetas": []}
REPASO_HORAS = 24
LOTE = 500
_NO_ENTRAR = {"$recycle.bin", "system volume information", "appdata", "node_modules", ".git", "__pycache__",
              "windows", "program files", "program files (x86)", "programdata", "$windows.~bt", "$winreagent"}


def config():
    return {**POR_DEFECTO, **(nucleo.cargar_ajustes().get("mapa_archivos") or {})}


def raices():
    elegidas = [c for c in config()["carpetas"] if c]
    if elegidas:
        return [c for c in elegidas if os.path.isdir(c)]
    salida = []
    for nombre in ("Documentos", "Descargas", "Escritorio", "Imágenes", "Vídeos", "Música"):
        c = nucleo.carpeta_conocida(nombre)
        if c and os.path.isdir(c) and all(not nucleo._dentro_de(c, x) for x in salida):
            salida.append(c)
    return salida


def ignorar(ruta):
    nombre = os.path.basename(ruta)
    if nucleo._dentro_de(ruta, nucleo.DATOS) or nombre.startswith("~$"):
        return True
    if nucleo._ignorado(nombre, ["*.tmp", "*.crdownload", "*.part", "*.partial", "*.download", "desktop.ini",
                                 "thumbs.db", ".ds_store"]):
        return True
    # Solo cuentan las carpetas por debajo de la raíz vigilada: la propia raíz puede estar dentro de
    # AppData (por ejemplo, una carpeta temporal) y no por eso hay que ignorar todo lo que contiene.
    for raiz in _raices_cache():
        if nucleo._dentro_de(ruta, raiz):
            relativa = os.path.relpath(ruta, raiz)
            return any(p.lower() in _NO_ENTRAR or p.startswith(".")
                       for p in relativa.replace("\\", "/").split("/")[:-1])
    return False


_cache = {"t": 0, "raices": []}


def _raices_cache():
    if time.time() - _cache["t"] > 10:
        _cache.update(t=time.time(), raices=raices())
    return _cache["raices"]


def progreso():
    return bd.leer("mapa:progreso", {}) or {}


def _anotar_progreso(**cambios):
    p = progreso()
    p.update(cambios)
    bd.escribir("mapa:progreso", p)


def escanear(cancelado=lambda: False):
    """Recorre todas las carpetas del mapa. Anota el avance para la barra de progreso del panel."""
    lista = raices()
    _cache.update(t=time.time(), raices=lista)
    inicio = bd.sello_recorrido()
    previo = bd.contar_archivos()["archivos"]
    _anotar_progreso(estado="escaneando", inicio=inicio, fin=None, hechos=0, total_estimado=previo or None,
                     carpeta="", raices=lista)
    hechos = 0
    for raiz in lista:
        lote = []
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            if cancelado():
                _anotar_progreso(estado="cancelado", fin=time.time())
                return False
            subcarpetas[:] = [d for d in subcarpetas if not d.startswith(".") and d.lower() not in _NO_ENTRAR
                              and not nucleo._dentro_de(os.path.join(carpeta, d), nucleo.DATOS)]
            for n in archivos:
                ruta = os.path.join(carpeta, n)
                if ignorar(ruta):
                    continue
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                lote.append((ruta, st.st_size, st.st_mtime))
                if len(lote) >= LOTE:
                    bd.archivo_visto(lote, inicio)
                    hechos += len(lote)
                    lote = []
                    _anotar_progreso(hechos=hechos, carpeta=carpeta)
        if lote:
            bd.archivo_visto(lote, inicio)
            hechos += len(lote)
        bd.olvidar_no_vistos(raiz, inicio)
    _anotar_progreso(estado="listo", fin=time.time(), hechos=hechos, total_estimado=hechos, carpeta="")
    return True


def hace_falta_repaso():
    p = progreso()
    if p.get("estado") == "escaneando" and time.time() - (p.get("inicio") or 0) < 6 * 3600:
        return False
    return not p.get("fin") or p.get("estado") != "listo" or time.time() - p["fin"] > REPASO_HORAS * 3600 \
        or sorted(p.get("raices") or []) != sorted(raices())


def desactivar():
    bd.vaciar_archivos()
    bd.borrar("mapa:progreso")


def estado():
    c = bd.contar_archivos()
    return {**config(), "raices": raices(), "progreso": progreso(), **c}


def buscar(texto, limite=200, etiqueta=None):
    """Por nombre, etiqueta o nota. Los archivos con etiqueta salen aunque el mapa esté apagado."""
    filas = [] if etiqueta else (bd.buscar_archivos(texto, limite) if config()["activo"] else [])
    conocidas = {r["ruta"] for r in filas}
    for ruta in bd.buscar_etiquetados(texto, limite, exacta=etiqueta):
        if ruta not in conocidas:
            try:
                st = os.stat(ruta)
                filas.append({"ruta": ruta, "bytes": st.st_size, "mtime": st.st_mtime})
            except OSError:
                filas.append({"ruta": ruta, "bytes": 0, "mtime": 0})
            conocidas.add(ruta)
    marcas = bd.etiquetas_de([r["ruta"] for r in filas])
    return [{**r, "nombre": os.path.basename(r["ruta"]), "carpeta": os.path.dirname(r["ruta"]),
             "existe": os.path.exists(r["ruta"]), **marcas.get(r["ruta"], {})} for r in filas[:limite]]


def tras_operaciones(operaciones):
    """Lo que acaba de hacer GESTOR se refleja en el mapa sin esperar al vigía."""
    for op in operaciones:
        o, d = op.get("origen"), op.get("destino")
        if op.get("accion") in ("mover", "renombrar") and o and d:
            bd.archivo_movido(o, d)
        elif op.get("accion") in ("papelera", "archivar") and o:
            bd.archivo_borrado([o])
        elif op.get("accion") == "copiar" and d and os.path.isfile(d):
            st = os.stat(d)
            bd.archivo_visto([(d, st.st_size, st.st_mtime)])


def _lo_hizo_gestor(origen, segundos=180):
    objetivo = nucleo._norm(origen)
    return any(nucleo._norm(r["o"]) == objetivo for r in nucleo._leer_indice(time.time() - segundos))


class Vigia:
    """Escucha los cambios del disco y mantiene el mapa al día. Vive en el proceso residente."""

    def __init__(self):
        self.observador = None
        self.raices = None
        self.eventos = []
        self.candado = threading.Lock()
        self.escaneo = None
        self.cancelar = threading.Event()

    def recargar(self):
        ajustes = nucleo.cargar_ajustes()
        activo = config()["activo"] and not ajustes.get("detenido")
        nuevas = raices() if activo else []
        if nuevas != self.raices:
            self.detener()
            self.raices = nuevas
            if nuevas:
                self._vigilar(nuevas)
        if activo and hace_falta_repaso() and not (self.escaneo and self.escaneo.is_alive()):
            self.cancelar.clear()
            self.escaneo = threading.Thread(target=self._escanear, daemon=True)
            self.escaneo.start()

    def _escanear(self):
        try:
            escanear(self.cancelar.is_set)
        except Exception:
            _anotar_progreso(estado="error", fin=time.time())

    def _vigilar(self, lista):
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return
        vigia = self

        class Manejador(FileSystemEventHandler):
            def on_any_event(self, ev):
                if ev.event_type in ("created", "modified", "deleted", "moved"):
                    with vigia.candado:
                        if len(vigia.eventos) < 20000:
                            vigia.eventos.append((ev.event_type, ev.src_path, getattr(ev, "dest_path", None),
                                                  ev.is_directory, time.time()))

        self.observador = Observer()
        for r in lista:
            try:
                self.observador.schedule(Manejador(), r, recursive=True)
            except OSError:
                pass
        self.observador.start()

    def atender(self):
        """Aplica los cambios acumulados (se llama cada pocos segundos)."""
        ahora = time.time()
        with self.candado:
            listos = [e for e in self.eventos if ahora - e[4] >= 3]
            self.eventos = [e for e in self.eventos if ahora - e[4] < 3]
        if not listos:
            return
        vistos, borrados, mios = {}, [], []
        for tipo, src, dest, es_carpeta, t in listos:
            if tipo == "moved" and dest:
                if ignorar(dest) and ignorar(src):
                    continue
                bd.archivo_movido(src, dest)
                vistos.pop(src, None)
                if not es_carpeta and not ignorar(dest):
                    vistos[dest] = True
                if not ignorar(src) and not ignorar(dest) and not _lo_hizo_gestor(src):
                    misma = nucleo._norm(os.path.dirname(src)) == nucleo._norm(os.path.dirname(dest))
                    mios.append({"t": t, "servicio": "Tú", "accion": "renombrar" if misma else "mover",
                                 "origen": src, "destino": dest, "carpeta": es_carpeta, "quien": "tu"})
            elif tipo == "deleted":
                if ignorar(src):
                    continue
                borrados.append(src)
                vistos.pop(src, None)
                if not _lo_hizo_gestor(src):
                    mios.append({"t": t, "servicio": "Tú", "accion": "borrado", "origen": src, "destino": "",
                                 "carpeta": es_carpeta, "quien": "tu"})
            elif not es_carpeta and not ignorar(src):
                vistos[src] = True
        if borrados:
            bd.archivo_borrado(borrados)
        filas = []
        for ruta in vistos:
            try:
                st = os.stat(ruta)
                filas.append((ruta, st.st_size, st.st_mtime))
            except OSError:
                pass
        if filas:
            bd.archivo_visto(filas)
        if mios:
            bd.anotar_movimientos(mios)

    def detener(self):
        self.cancelar.set()
        if self.observador:
            self.observador.stop()
            self.observador.join(timeout=5)
            self.observador = None
