"""GESTOR: base de datos (SQLite, incluida en Python: no hay que instalar nada).

Todo lo que GESTOR recuerda vive en un solo archivo, gestor.db, dentro de la carpeta de datos:
- datos:       la configuración y el estado (servicios, ajustes, estado...), una fila por clave.
- movimientos: cada archivo que se movió, copió o fue a la papelera, para siempre.
- archivos:    dónde está cada uno de tus archivos ahora mismo (si activas el mapa de archivos).

SQLite aguanta que el panel, el motor y el icono escriban a la vez sin pisarse ni corromperse,
que era lo que pasaba con los .json cuando Windows o el antivirus los tenían abiertos.
"""

import json
import os
import sqlite3
import threading
import time
import unicodedata

_hilo = threading.local()
_ruta = None

ESQUEMA = """
CREATE TABLE IF NOT EXISTS datos (clave TEXT PRIMARY KEY, valor TEXT NOT NULL, t REAL);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY, t REAL NOT NULL, servicio TEXT, accion TEXT, origen TEXT, destino TEXT,
    zip TEXT, papelera_id TEXT, carpeta INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0,
    quien TEXT DEFAULT 'gestor', busqueda TEXT);
CREATE INDEX IF NOT EXISTS mov_t ON movimientos(t);
CREATE TABLE IF NOT EXISTS archivos (
    ruta TEXT PRIMARY KEY, carpeta TEXT, nombre TEXT, busqueda TEXT, ext TEXT,
    bytes INTEGER, mtime REAL, visto REAL);
CREATE INDEX IF NOT EXISTS arch_carpeta ON archivos(carpeta);
"""


def iniciar(carpeta_datos):
    global _ruta
    _ruta = os.path.join(carpeta_datos, "gestor.db")


def sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn").lower()


def con():
    c = getattr(_hilo, "c", None)
    if c is None or getattr(_hilo, "ruta", None) != _ruta:
        c = sqlite3.connect(_ruta, timeout=60, isolation_level=None, check_same_thread=False)
        c.execute("PRAGMA busy_timeout=60000")
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(ESQUEMA)
        _hilo.c, _hilo.ruta = c, _ruta
    return c


class transaccion:
    """BEGIN IMMEDIATE ... COMMIT: lo que se lee y se escribe dentro no lo pisa otro proceso."""

    def __enter__(self):
        self.c = con()
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, tipo, *_):
        self.c.execute("ROLLBACK" if tipo else "COMMIT")


# --------------------------------------------------------------------------- datos (clave → JSON)

def _migrar(clave, archivo):
    """La primera vez, trae el .json antiguo a la base (reintenta si Windows lo tiene bloqueado)."""
    if not archivo or not os.path.exists(archivo):
        return None
    for intento in range(10):
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                valor = json.load(f)
            break
        except PermissionError:
            time.sleep(0.3)
        except (OSError, ValueError):
            return None
    else:
        return None
    with transaccion() as c:
        if c.execute("SELECT 1 FROM datos WHERE clave=?", (clave,)).fetchone() is None:
            c.execute("INSERT INTO datos VALUES (?,?,?)", (clave, json.dumps(valor, ensure_ascii=False), time.time()))
    try:
        os.replace(archivo, archivo + ".migrado")
    except OSError:
        pass
    return valor


def leer(clave, por_defecto=None, archivo=None):
    fila = con().execute("SELECT valor FROM datos WHERE clave=?", (clave,)).fetchone()
    if fila is None:
        valor = _migrar(clave, archivo)
        return por_defecto if valor is None else valor
    return json.loads(fila[0])


def existe(clave, archivo=None):
    return con().execute("SELECT 1 FROM datos WHERE clave=?", (clave,)).fetchone() is not None or \
        bool(archivo and os.path.exists(archivo))


def escribir(clave, valor):
    con().execute("INSERT OR REPLACE INTO datos VALUES (?,?,?)",
                  (clave, json.dumps(valor, ensure_ascii=False), time.time()))


def borrar(clave):
    con().execute("DELETE FROM datos WHERE clave=?", (clave,))


def leer_grupo(prefijo):
    """{subclave: valor} de todas las filas «prefijo:subclave»."""
    filas = con().execute("SELECT clave, valor FROM datos WHERE clave >= ? AND clave < ?",
                          (prefijo + ":", prefijo + ";")).fetchall()
    return {k[len(prefijo) + 1:]: json.loads(v) for k, v in filas}


def escribir_grupo(prefijo, cambios, quitar=()):
    with transaccion() as c:
        for k, v in cambios.items():
            c.execute("INSERT OR REPLACE INTO datos VALUES (?,?,?)",
                      (f"{prefijo}:{k}", json.dumps(v, ensure_ascii=False), time.time()))
        for k in quitar:
            c.execute("DELETE FROM datos WHERE clave=?", (f"{prefijo}:{k}",))


# --------------------------------------------------------------------------- movimientos (historial)

def anotar_movimientos(filas):
    """filas: [{t, servicio, accion, origen, destino, zip, papelera_id, carpeta, bytes, quien}]"""
    if not filas:
        return
    with transaccion() as c:
        c.executemany(
            "INSERT INTO movimientos (t, servicio, accion, origen, destino, zip, papelera_id, carpeta, bytes, quien, busqueda)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(f["t"], f.get("servicio", ""), f["accion"], f["origen"], f.get("destino") or "", f.get("zip"),
              f.get("papelera_id"), int(bool(f.get("carpeta"))), int(f.get("bytes") or 0), f.get("quien") or "gestor",
              sin_acentos(os.path.basename(f["origen"]) + " " + os.path.basename(f.get("destino") or "")))
             for f in filas])


def migrar_indice(archivo):
    """Trae el indice.jsonl antiguo a la tabla de movimientos (una sola vez)."""
    if not os.path.exists(archivo):
        return
    filas = []
    try:
        with open(archivo, encoding="utf-8") as f:
            for linea in f:
                try:
                    r = json.loads(linea)
                except ValueError:
                    continue
                filas.append({"t": r["t"], "servicio": r.get("s", ""), "accion": r["a"], "origen": r["o"],
                              "destino": r.get("d"), "zip": r.get("z"), "papelera_id": r.get("p"),
                              "carpeta": r.get("c"), "bytes": r.get("b", 0)})
    except OSError:
        return
    anotar_movimientos(filas)
    try:
        os.replace(archivo, archivo + ".migrado")
    except OSError:
        pass


def _mov(fila):
    t, servicio, accion, origen, destino, z, p, carpeta, b, quien = fila
    return {"t": t, "s": servicio, "a": accion, "o": origen, "d": destino, "z": z, "p": p, "c": bool(carpeta),
            "b": b, "quien": quien}


COLUMNAS = "t, servicio, accion, origen, destino, zip, papelera_id, carpeta, bytes, quien"


def movimientos(texto="", desde=None, hasta=None, limite=200, recientes_primero=False):
    sql, args = f"SELECT {COLUMNAS} FROM movimientos WHERE 1=1", []
    for palabra in sin_acentos(texto).split():
        sql += " AND busqueda LIKE ?"
        args.append(f"%{palabra}%")
    if desde:
        sql += " AND t >= ?"
        args.append(desde)
    if hasta:
        sql += " AND t <= ?"
        args.append(hasta)
    sql += " ORDER BY t " + ("DESC" if recientes_primero else "ASC") + ", id" + (" DESC" if recientes_primero else "")
    if limite:
        sql += " LIMIT ?"
        args.append(limite)
    return [_mov(f) for f in con().execute(sql, args)]


def resumen_movimientos(desde):
    f = con().execute("SELECT SUM(accion!='papelera'), SUM(accion='papelera'), "
                      "SUM(CASE WHEN accion='papelera' THEN bytes ELSE 0 END) FROM movimientos WHERE t >= ?",
                      (desde,)).fetchone()
    return {"movidos": f[0] or 0, "papelera": f[1] or 0, "bytes_papelera": f[2] or 0}


def total_movimientos():
    return con().execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


# --------------------------------------------------------------------------- mapa de archivos

def archivo_visto(filas):
    """filas: [(ruta, bytes, mtime)]"""
    ahora = time.time()
    with transaccion() as c:
        c.executemany("INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?,?,?)",
                      [(r, os.path.dirname(r), os.path.basename(r), sin_acentos(os.path.basename(r)),
                        os.path.splitext(r)[1].lower(), b, m, ahora) for r, b, m in filas])


def _dentro(ruta):
    """(sql, args) para «esta ruta o algo dentro de ella», sin comodines de LIKE."""
    prefijo = ruta.rstrip("\\/") + os.sep
    return "(ruta=? OR substr(ruta,1,?)=?)", [ruta, len(prefijo), prefijo]


def archivo_borrado(rutas):
    with transaccion() as c:
        for r in rutas:
            sql, args = _dentro(r)
            c.execute("DELETE FROM archivos WHERE " + sql, args)


def archivo_movido(antes, despues):
    """Un archivo o una carpeta entera cambió de sitio."""
    with transaccion() as c:
        sql, args = _dentro(antes)
        filas = c.execute("SELECT ruta FROM archivos WHERE " + sql, args).fetchall()
        for (r,) in filas:
            nueva = despues + r[len(antes):]
            c.execute("UPDATE OR REPLACE archivos SET ruta=?, carpeta=?, nombre=?, busqueda=?, ext=? WHERE ruta=?",
                      (nueva, os.path.dirname(nueva), os.path.basename(nueva), sin_acentos(os.path.basename(nueva)),
                       os.path.splitext(nueva)[1].lower(), r))


def olvidar_no_vistos(raiz, antes_de):
    """Tras recorrer una carpeta entera, lo que no se vio ya no existe."""
    with transaccion() as c:
        sql, args = _dentro(raiz)
        c.execute(f"DELETE FROM archivos WHERE {sql} AND visto < ?", args + [antes_de])


def buscar_archivos(texto, limite=200):
    sql, args = "SELECT ruta, bytes, mtime FROM archivos WHERE 1=1", []
    for palabra in sin_acentos(texto).split():
        sql += " AND busqueda LIKE ?"
        args.append(f"%{palabra}%")
    sql += " ORDER BY mtime DESC LIMIT ?"
    args.append(limite)
    return [{"ruta": r, "bytes": b, "mtime": m} for r, b, m in con().execute(sql, args)]


def contar_archivos():
    f = con().execute("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM archivos").fetchone()
    return {"archivos": f[0], "bytes": f[1]}


def vaciar_archivos():
    con().execute("DELETE FROM archivos")
