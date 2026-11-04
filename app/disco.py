"""GESTOR: mapa del disco al estilo WinDirStat.

Recorre una carpeta o un disco entero y devuelve un árbol compacto con lo que ocupa cada cosa,
para dibujarlo en el panel como rectángulos proporcionales a su tamaño (coloreados por tipo).
Los archivos pequeños de cada carpeta se agrupan en un solo bloque para que el dibujo sea ligero.
"""

import os
import time

import bd
import nucleo

MAX_BLOQUES = 7000  # tamaño mínimo de un bloque: lo que ocupa todo / MAX_BLOQUES


def recorrer(raiz, cancelado=lambda: False):
    """Árbol completo {n, c: [subcarpetas], f: [(nombre, bytes, ext)], s} y estadísticas por extensión."""
    raiz_nodo = {"n": raiz, "c": [], "f": [], "s": 0}
    pila, extensiones, vistos = [(raiz, raiz_nodo)], {}, 0
    nucleo.avance(hechos=0, total=None, etapa="Midiendo " + raiz)
    while pila:
        if cancelado():
            return None, None
        ruta, nodo = pila.pop()
        try:
            entradas = os.scandir(ruta)
        except OSError:
            continue
        with entradas:
            for e in entradas:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if getattr(e, "is_junction", lambda: False)() or nucleo._dentro_de(e.path, nucleo.DATOS):
                            continue
                        hijo = {"n": e.name, "c": [], "f": [], "s": 0}
                        nodo["c"].append(hijo)
                        pila.append((e.path, hijo))
                    elif e.is_file(follow_symlinks=False):
                        tam = e.stat(follow_symlinks=False).st_size
                        ext = os.path.splitext(e.name)[1].lower()[:12]
                        nodo["f"].append((e.name, tam, ext))
                        x = extensiones.setdefault(ext, [0, 0])
                        x[0] += tam
                        x[1] += 1
                        vistos += 1
                except OSError:
                    continue
        if vistos and vistos % 2000 < 50:
            nucleo.avance(hechos=vistos, etapa=f"Midiendo {raiz}: {vistos:,} archivos")
    _sumar(raiz_nodo)
    return raiz_nodo, extensiones


def _sumar(nodo):
    nodo["s"] = sum(t for _, t, _ in nodo["f"]) + sum(_sumar(h) for h in nodo["c"])
    nodo["k"] = len(nodo["f"]) + sum(h["k"] for h in nodo["c"])  # cuántos archivos tiene dentro
    return nodo["s"]


def _compactar(nodo, umbral):
    """[nombre, bytes, ext|None, hijos|None, archivos]; lo pequeño se junta en un bloque «~»."""
    hijos, chicos, n_chicos = [], 0, 0
    for h in nodo["c"]:
        if h["s"] >= umbral:
            hijos.append(_compactar(h, umbral))
        elif h["s"]:
            chicos += h["s"]
            n_chicos += h["k"]
    for nombre, tam, ext in nodo["f"]:
        if tam >= umbral:
            hijos.append([nombre, tam, ext, None, 1])
        elif tam:
            chicos += tam
            n_chicos += 1
    if chicos:
        hijos.append([f"{n_chicos:,} archivos pequeños", chicos, "~", None, n_chicos])
    hijos.sort(key=lambda h: -h[1])
    return [nodo["n"], nodo["s"], None, hijos, nodo["k"]]


def analizar(raiz, cancelado=lambda: False):
    raiz = os.path.normpath(raiz)
    if not os.path.isdir(raiz):
        raise ValueError("Esa carpeta no existe.")
    inicio = time.time()
    arbol, extensiones = recorrer(raiz, cancelado)
    if arbol is None:
        return {"ok": False, "cancelado": True}
    umbral = max(1, arbol["s"] // MAX_BLOQUES)
    tipos = sorted(([e or "(sin extensión)", b, n, nucleo.categoria_de(e)] for e, (b, n) in extensiones.items()),
                   key=lambda x: -x[1])
    resultado = {"ok": True, "raiz": raiz, "bytes": arbol["s"], "archivos": arbol["k"],
                 "arbol": _compactar(arbol, umbral), "tipos": tipos[:60], "segundos": round(time.time() - inicio, 1),
                 "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")}
    bd.escribir("disco:ultimo", resultado)
    return resultado


def ultimo():
    return bd.leer("disco:ultimo", None)


def lugares():
    """Lo que se puede analizar con un clic: los discos y tu carpeta de usuario."""
    salida = [{"nombre": "Tu carpeta de usuario", "ruta": os.path.expanduser("~")}]
    for u in nucleo.unidades_fijas():
        ruta = u["letra"] + "\\" if nucleo.ES_WINDOWS else u["letra"]
        salida.append({"nombre": f'Disco {u["letra"]}', "ruta": ruta, "total": u["total"], "libre": u["libre"]})
    return salida


def _tamano(ruta):
    if os.path.isfile(ruta):
        return os.path.getsize(ruta)
    total = 0
    for raiz, _, archivos in os.walk(ruta):
        for n in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, n))
            except OSError:
                pass
    return total


def borrar(ruta):
    """Quita del disco lo elegido en el mapa: a la papelera de GESTOR (o la de Windows), así se puede recuperar.

    Solo dentro de la carpeta medida, y nunca carpetas del sistema, la raíz de un disco, tu carpeta de usuario
    o los datos de GESTOR.
    """
    res = ultimo() or {}
    raiz = res.get("raiz") or ""
    ruta = os.path.abspath(ruta or "")
    if not raiz or not nucleo._dentro_de(ruta, raiz) or nucleo._norm(ruta) == nucleo._norm(raiz):
        raise ValueError("Solo se puede borrar algo de dentro de la carpeta medida.")
    permitida, _ = nucleo.revisar_carpeta(ruta)
    protegidas = [os.path.expanduser("~"), nucleo.DATOS, os.path.splitdrive(ruta)[0] + os.sep]
    if not permitida or any(nucleo._norm(ruta) == nucleo._norm(p) for p in protegidas) or nucleo._dentro_de(ruta, nucleo.DATOS):
        raise ValueError("Esa carpeta está protegida: GESTOR no la borra.")
    if not os.path.exists(ruta):
        raise ValueError("Ya no existe (quizá la moviste o la borraste).")
    tam = _tamano(ruta)
    op = {"accion": "papelera", "origen": ruta, "destino": "", "bytes": tam, "carpeta": os.path.isdir(ruta)}
    op["papelera_id"] = nucleo.quitar(ruta, "mapa del disco")
    if op["papelera_id"]:  # en la papelera de GESTOR: el tamaño real de la carpeta, no el de su entrada
        indice = nucleo.leer_json(nucleo.ARCHIVO_PAPELERA, [])
        for e in indice:
            if e["id"] == op["papelera_id"]:
                e["bytes"] = tam
        nucleo.escribir_json(nucleo.ARCHIVO_PAPELERA, indice)
    nucleo.indexar({"nombre": "Mapa del disco"}, [op], quien="tu")
    return {"ok": True, "bytes": tam, "papelera": "gestor" if op["papelera_id"] else "windows"}
