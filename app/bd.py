"""GESTOR: base de datos (SQLite, incluida en Python: no hay que instalar nada).

Todo lo que GESTOR recuerda vive en un solo archivo, gestor.db, dentro de la carpeta de datos:
- datos:       la configuración y el estado (servicios, ajustes, estado...), una fila por clave.
- movimientos: cada archivo que se movió, copió o fue a la papelera, para siempre.
- archivos:    dónde está cada uno de tus archivos ahora mismo (si activas el mapa de archivos).
- etiquetas y notas que le pones a tus archivos (siguen al archivo cuando se mueve).
- textos:      lo que GESTOR leyó en fotos y PDF escaneados (OCR), para no volver a leerlos.

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
CREATE INDEX IF NOT EXISTS arch_mtime ON archivos(mtime);
CREATE TABLE IF NOT EXISTS etiquetas (ruta TEXT, etiqueta TEXT, busqueda TEXT, t REAL, PRIMARY KEY (ruta, etiqueta));
CREATE INDEX IF NOT EXISTS etq_busqueda ON etiquetas(busqueda);
CREATE TABLE IF NOT EXISTS notas (ruta TEXT PRIMARY KEY, texto TEXT, busqueda TEXT, t REAL);
CREATE TABLE IF NOT EXISTS textos (ruta TEXT PRIMARY KEY, mtime REAL, texto TEXT, t REAL);
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


def actividad_diaria(dias=30):
    """Para las gráficas del Inicio: archivos ordenados y enviados a la papelera, día por día (hora local)."""
    import datetime as dt
    hoy = dt.date.today()
    inicio = dt.datetime.combine(hoy - dt.timedelta(days=dias - 1), dt.time()).timestamp()
    cuenta = {(hoy - dt.timedelta(days=i)).isoformat(): [0, 0] for i in range(dias)}
    filas = con().execute("SELECT date(t, 'unixepoch', 'localtime'), SUM(accion!='papelera'), SUM(accion='papelera') "
                          "FROM movimientos WHERE t >= ? GROUP BY 1", (inicio,)).fetchall()
    for dia, movidos, papelera in filas:
        if dia in cuenta:
            cuenta[dia] = [movidos or 0, papelera or 0]
    return [{"d": d, "n": v[0], "p": v[1]} for d, v in sorted(cuenta.items())]


def resumen_periodo(desde, hasta):
    """Para el informe mensual: movimientos por servicio, por extensión y por día entre dos fechas."""
    c = con()
    por_servicio = c.execute("SELECT servicio, quien, COUNT(*), SUM(CASE WHEN accion='papelera' THEN bytes ELSE 0 END) "
                             "FROM movimientos WHERE t >= ? AND t < ? GROUP BY servicio, quien ORDER BY COUNT(*) DESC",
                             (desde, hasta)).fetchall()
    origenes = c.execute("SELECT origen, t FROM movimientos WHERE t >= ? AND t < ? AND quien='gestor'",
                         (desde, hasta)).fetchall()
    return {"servicios": [{"servicio": s or "", "quien": q, "n": n, "bytes_papelera": b or 0}
                          for s, q, n, b in por_servicio],
            "extensiones": [os.path.splitext(o or "")[1].lower() for o, _ in origenes],
            "tiempos": [t for _, t in origenes]}


def total_movimientos():
    return con().execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


# --------------------------------------------------------------------------- mapa de archivos

def archivo_visto(filas, sello=None):
    """filas: [(ruta, bytes, mtime)]. sello: la marca de «visto» de un recorrido completo."""
    ahora = sello or time.time()
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
    seguir(antes, despues)
    with transaccion() as c:
        sql, args = _dentro(antes)
        filas = c.execute("SELECT ruta FROM archivos WHERE " + sql, args).fetchall()
        for (r,) in filas:
            nueva = despues + r[len(antes):]
            c.execute("UPDATE OR REPLACE archivos SET ruta=?, carpeta=?, nombre=?, busqueda=?, ext=? WHERE ruta=?",
                      (nueva, os.path.dirname(nueva), os.path.basename(nueva), sin_acentos(os.path.basename(nueva)),
                       os.path.splitext(nueva)[1].lower(), r))


def sello_recorrido():
    """Marca para un recorrido nuevo, siempre mayor que cualquier «visto» anterior
    (en Windows el reloj avanza a saltos y dos recorridos seguidos pueden dar la misma hora)."""
    ultimo = con().execute("SELECT MAX(visto) FROM archivos").fetchone()[0] or 0
    return max(time.time(), ultimo + 0.001)


def olvidar_no_vistos(raiz, antes_de):
    """Tras recorrer una carpeta entera, lo que no se vio ya no existe."""
    with transaccion() as c:
        sql, args = _dentro(raiz)
        c.execute(f"DELETE FROM archivos WHERE {sql} AND visto < ?", args + [antes_de])


def buscar_archivos(texto, limite=200):
    """Por nombre, etiqueta o nota: cada palabra tiene que aparecer en alguno de los tres."""
    sql, args = "SELECT ruta, bytes, mtime FROM archivos a WHERE 1=1", []
    for palabra in sin_acentos(texto).split():
        sql += (" AND (a.busqueda LIKE ? OR EXISTS (SELECT 1 FROM etiquetas e WHERE e.ruta=a.ruta AND e.busqueda LIKE ?)"
                " OR EXISTS (SELECT 1 FROM notas n WHERE n.ruta=a.ruta AND n.busqueda LIKE ?))")
        args += [f"%{palabra}%"] * 3
    sql += " ORDER BY mtime DESC LIMIT ?"
    args.append(limite)
    return [{"ruta": r, "bytes": b, "mtime": m} for r, b, m in con().execute(sql, args)]


def archivos_entre(desde, hasta, limite=3000):
    """Los archivos del mapa modificados entre dos fechas (para la línea de tiempo)."""
    return [{"ruta": r, "bytes": b, "mtime": m} for r, b, m in con().execute(
        "SELECT ruta, bytes, mtime FROM archivos WHERE mtime >= ? AND mtime < ? ORDER BY mtime DESC LIMIT ?",
        (desde, hasta, limite))]


def archivos_bajo(carpeta):
    """(ruta, bytes) de todo lo que el mapa conoce dentro de una carpeta (para el mapa del disco)."""
    sql, args = _dentro(carpeta)
    return con().execute("SELECT ruta, bytes FROM archivos WHERE " + sql, args).fetchall()


def hay_otra_copia(ruta, nombre, tam):
    """¿El mapa conoce otro archivo con el mismo nombre y tamaño?"""
    return con().execute("SELECT 1 FROM archivos WHERE nombre=? AND bytes=? AND ruta<>? LIMIT 1",
                         (nombre, tam, ruta)).fetchone() is not None


# --------------------------------------------------------------------------- etiquetas y notas

def seguir(antes, despues):
    """Las etiquetas, notas y textos leídos siguen al archivo (o a la carpeta) cuando se mueve."""
    sql, args = _dentro(antes)
    with transaccion() as c:
        for tabla in ("etiquetas", "notas", "textos"):
            for (r,) in c.execute(f"SELECT DISTINCT ruta FROM {tabla} WHERE " + sql, args).fetchall():
                nueva = despues + r[len(antes):]
                c.execute(f"UPDATE OR REPLACE {tabla} SET ruta=? WHERE ruta=?", (nueva, r))


def poner_etiqueta(ruta, etiqueta):
    etiqueta = " ".join((etiqueta or "").split())[:60]
    if etiqueta:
        con().execute("INSERT OR IGNORE INTO etiquetas VALUES (?,?,?,?)",
                      (ruta, etiqueta, sin_acentos(etiqueta), time.time()))


def quitar_etiqueta(ruta, etiqueta):
    con().execute("DELETE FROM etiquetas WHERE ruta=? AND etiqueta=?", (ruta, etiqueta))


def poner_nota(ruta, texto):
    texto = (texto or "").strip()[:2000]
    if texto:
        con().execute("INSERT OR REPLACE INTO notas VALUES (?,?,?,?)", (ruta, texto, sin_acentos(texto), time.time()))
    else:
        con().execute("DELETE FROM notas WHERE ruta=?", (ruta,))


def etiquetas_de(rutas):
    """{ruta: {"etiquetas": [...], "nota": "..."}} de una lista de rutas."""
    salida = {r: {"etiquetas": [], "nota": ""} for r in rutas}
    rutas = list(salida)
    for i in range(0, len(rutas), 500):
        trozo = rutas[i:i + 500]
        marcas = ",".join("?" * len(trozo))
        for r, e in con().execute(f"SELECT ruta, etiqueta FROM etiquetas WHERE ruta IN ({marcas}) ORDER BY etiqueta", trozo):
            salida[r]["etiquetas"].append(e)
        for r, t in con().execute(f"SELECT ruta, texto FROM notas WHERE ruta IN ({marcas})", trozo):
            salida[r]["nota"] = t
    return salida


def todas_las_etiquetas():
    return [{"etiqueta": e, "n": n} for e, n in con().execute(
        "SELECT etiqueta, COUNT(*) FROM etiquetas GROUP BY etiqueta ORDER BY COUNT(*) DESC, etiqueta")]


def buscar_etiquetados(texto, limite=200, exacta=None):
    """Rutas con esa etiqueta (exacta) o cuyas etiquetas o nota contienen todas las palabras."""
    if exacta:
        return [r for (r,) in con().execute("SELECT ruta FROM etiquetas WHERE etiqueta=? ORDER BY t DESC LIMIT ?",
                                            (exacta, limite))]
    palabras = sin_acentos(texto).split()
    if not palabras:
        return []
    sql = "SELECT ruta FROM (SELECT ruta, busqueda FROM etiquetas UNION ALL SELECT ruta, busqueda FROM notas) GROUP BY ruta HAVING 1=1"
    args = []
    for p in palabras:
        sql += " AND SUM(busqueda LIKE ?) > 0"
        args.append(f"%{p}%")
    sql += " LIMIT ?"
    return [r for (r,) in con().execute(sql, args + [limite])]


# --------------------------------------------------------------------------- textos leídos (OCR)

def texto_guardado(ruta, mtime):
    f = con().execute("SELECT texto FROM textos WHERE ruta=? AND mtime=?", (ruta, mtime)).fetchone()
    return f[0] if f else None


def guardar_texto(ruta, mtime, texto):
    con().execute("INSERT OR REPLACE INTO textos VALUES (?,?,?,?)", (ruta, mtime, texto or "", time.time()))


def contar_archivos():
    f = con().execute("SELECT COUNT(*), COALESCE(SUM(bytes),0) FROM archivos").fetchone()
    return {"archivos": f[0], "bytes": f[1]}


def vaciar_archivos():
    con().execute("DELETE FROM archivos")
