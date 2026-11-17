"""GESTOR: facturas y recordatorios de pago.

Lee tus recibos y facturas (PDF, XML de CFDI y, con el OCR de Windows, fotos de recibos) y saca:
- lo que hay que pagar y cuándo: «CFE vence el 15, son $1,234». Avisa 3 días antes y el mismo día;
- lo que gastaste con cada proveedor, para el informe mensual.

Como los vencimientos, el análisis es incremental: unos segundos en cada revisión del motor.
Los recibos pendientes llevan la etiqueta «pendiente de pagar»; al marcarlos como pagados, «pagado».
"""

import datetime as dt
import os
import re
import time

import bd
import nucleo
import vencimientos

ARCHIVO = os.path.join(nucleo.DATOS, "pagos.json")
EXT = {".pdf", ".xml"}
AVISAR_DIAS = (3, 0)
ETIQUETA_PENDIENTE = "pendiente de pagar"
ETIQUETA_PAGADO = "pagado"

_LIMITE = re.compile(
    r"(fecha\s+l[ií]mite(?:\s+de\s+pago)?|l[ií]mite\s+de\s+pago|p[aá]gue(?:se)?\s+antes\s+del?|pagar\s+antes\s+del?|"
    r"fecha\s+de\s+vencimiento(?:\s+del?\s+pago)?|vencimiento\s+del?\s+pago|fecha\s+para\s+pagar|"
    r"payment\s+due(?:\s+date)?|due\s+date)", re.IGNORECASE)
_MONTO = [re.compile(p + r"\s*[:\-]?[^\d\n]{0,25}\$?\s*([\d,]+\.\d{2})", re.IGNORECASE) for p in (
    r"(?:total|importe|monto|saldo|cantidad)\s+a\s+pagar", r"pago\s+para\s+no\s+generar\s+intereses",
    r"total\s+del?\s+periodo", r"\btotal\b(?!\s*(?:de\s+)?(?:impuestos|trasladados|retenidos))", r"amount\s+due")]
_F_TEXTO_CORTA = re.compile(r"\b(\d{1,2})[\s/\-.]+([a-záéíóú]{3,10})\.?[\s/\-.]+(\d{2})\b", re.IGNORECASE)
_F_DMA_CORTA = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b")
# Nombres que se reconocen en el texto de un recibo aunque no sea una factura con emisor.
_CONOCIDOS = ["CFE", "Telmex", "Telcel", "izzi", "Totalplay", "Megacable", "Sky", "AT&T", "Naturgy", "Infonavit",
              "BBVA", "Banamex", "Santander", "Banorte", "HSBC", "Scotiabank", "Inbursa", "American Express",
              "Liverpool", "Palacio de Hierro", "Coppel", "Elektra", "Mercado Pago", "Stori", "Rappi",
              "Netflix", "Spotify", "Amazon", "Predial", "Tenencia", "SACMEX", "Agua"]


def cargar():
    d = nucleo.leer_json(ARCHIVO, {})
    for k, v in (("archivos", {}), ("estados", {}), ("avisos", {}), ("manuales", [])):
        d.setdefault(k, v)
    return d


def guardar(d):
    nucleo.escribir_json(ARCHIVO, d)


def carpetas_a_revisar():
    extra = nucleo.cargar_ajustes().get("carpetas_pagos") or []
    return [nucleo.carpeta_conocida("Documentos"), nucleo.carpeta_conocida("Descargas")] + [c for c in extra if c]


def _extensiones():
    ext = set(EXT)
    if nucleo.ES_WINDOWS:
        import ocr
        if ocr.activo():
            ext |= ocr.EXT_IMAGEN
    return ext


def _fechas(texto):
    fechas = vencimientos.fechas_en(texto)
    for d, mes, a in _F_TEXTO_CORTA.findall(texto):
        m = vencimientos._MESES.get(nucleo.sin_acentos(mes.lower())[:3])
        if m:
            fechas.append(vencimientos._fecha(2000 + int(a), m, d))
    for d, m, a in _F_DMA_CORTA.findall(texto):
        fechas.append(vencimientos._fecha(2000 + int(a), m, d))
    return [f for f in fechas if f]


def fecha_limite(texto):
    """La fecha límite de pago de un recibo: la primera fecha después de «fecha límite de pago», etc."""
    for m in _LIMITE.finditer(texto or ""):
        fechas = _fechas(texto[m.end():m.end() + 60])
        if fechas:
            return fechas[0]
    return None


def monto(texto):
    for patron in _MONTO:
        encontrados = patron.findall(texto or "")
        if encontrados:
            try:
                return float(encontrados[0].replace(",", ""))
            except ValueError:
                pass
    return None


def proveedor_de(ruta, texto, factura):
    corto = nucleo.proveedor_corto(factura.get("proveedor") or "")
    if corto:
        return corto
    for nombre in (os.path.basename(ruta), (texto or "")[:3000]):
        for conocido in _CONOCIDOS:
            if re.search(r"(?<![A-Za-z])" + re.escape(conocido) + r"(?![A-Za-z])", nombre,
                         0 if conocido.isupper() else re.IGNORECASE):
                return conocido
    return factura.get("rfc") or ""


def analizar(ruta):
    """{tipo: "pago"|"factura", proveedor, total, fecha, limite} o None si no es un recibo ni una factura."""
    texto = nucleo.texto_de(ruta) if not ruta.lower().endswith(".xml") else ""
    factura = nucleo.datos_factura(ruta)
    limite = fecha_limite(texto)
    if not limite and not factura.get("es_factura"):
        return None
    total = monto(texto)
    if total is None:
        try:
            total = float(factura.get("total") or "")
        except ValueError:
            total = None
    fecha = (factura.get("fecha") or "")[:10]
    return {"tipo": "pago" if limite else "factura", "proveedor": proveedor_de(ruta, texto, factura),
            "total": total, "fecha": fecha, "limite": limite.isoformat() if limite else ""}


def escanear(segundos=20, limite=30000):
    """Analiza los recibos nuevos o cambiados durante unos segundos. Devuelve True si terminó."""
    d = cargar()
    archivos = d["archivos"]
    inicio, vistos, por_leer, terminado = time.time(), set(), [], True
    extensiones = _extensiones()
    for raiz in carpetas_a_revisar():
        if not raiz or not os.path.isdir(raiz):
            continue
        for carpeta, subcarpetas, nombres in os.walk(raiz):
            subcarpetas[:] = [s for s in subcarpetas if not s.startswith((".", "$"))
                              and not nucleo._dentro_de(os.path.join(carpeta, s), nucleo.DATOS)]
            nucleo.avance(sumar=len(nombres), etapa="Leyendo recibos y facturas")
            for n in nombres:
                if os.path.splitext(n)[1].lower() not in extensiones or nucleo._ignorado(n, nucleo.IGNORAR_SIEMPRE):
                    continue
                ruta = os.path.join(carpeta, n)
                if ruta in vistos:
                    continue
                vistos.add(ruta)
                if len(vistos) > limite:
                    break
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                previo = archivos.get(ruta)
                if previo and previo.get("mtime") == int(st.st_mtime):
                    continue
                if st.st_size > 30 * 1024 * 1024:
                    archivos[ruta] = {"mtime": int(st.st_mtime), "tipo": None}
                    continue
                por_leer.append((ruta, int(st.st_mtime)))
    if nucleo.ES_WINDOWS:
        import ocr
        # Las fotos se leen en lote: un solo PowerShell para muchas.
        fotos = [r for r, _ in por_leer if os.path.splitext(r)[1].lower() in ocr.EXT_IMAGEN][:40]
        if fotos:
            ocr.leer_lote(fotos, segundos=max(30, segundos * 3))
    for ruta, mtime in por_leer:
        if time.time() - inicio > segundos:
            terminado = False
            break
        try:
            datos = analizar(ruta) or {"tipo": None}
        except Exception:
            datos = {"tipo": None}
        datos["mtime"] = mtime
        archivos[ruta] = datos
    if terminado:
        for ruta in [r for r in archivos if r not in vistos]:
            del archivos[ruta]
        d["ultimo_escaneo"] = time.time()
    guardar(d)
    _etiquetar(d)
    return terminado


def clave(p):
    return f'{p.get("proveedor") or ""}|{p.get("limite") or p.get("fecha") or ""}|{p.get("total") or ""}'


def _unicos(d, tipo=None):
    """Una fila por recibo: el PDF y su XML (o dos copias del mismo PDF) cuentan una vez."""
    vistos = {}
    for ruta, a in sorted(d["archivos"].items()):
        if not a.get("tipo") or (tipo and a["tipo"] != tipo):
            continue
        k = clave(a)
        if k not in vistos or ruta.lower().endswith(".pdf"):
            vistos[k] = {**a, "ruta": ruta, "clave": k}
    for m in d["manuales"]:
        if not tipo or m.get("tipo", "pago") == tipo:
            vistos[m["id"]] = {**m, "clave": m["id"], "manual": True}
    return list(vistos.values())


def lista(hoy=None):
    """Pagos pendientes (y los pagados del último mes), del más urgente al más lejano."""
    hoy = hoy or dt.date.today()
    d = cargar()
    filas = []
    for p in _unicos(d, "pago"):
        estado = d["estados"].get(p["clave"], "pendiente")
        if estado == "ignorado" or not p.get("limite"):
            continue
        dias = (dt.date.fromisoformat(p["limite"]) - hoy).days
        if dias < -45 or (estado == "pagado" and dias < -30):
            continue
        filas.append({"clave": p["clave"], "ruta": p.get("ruta", ""), "nombre": os.path.basename(p.get("ruta", "")) or p.get("nombre", ""),
                      "proveedor": p.get("proveedor") or "Recibo", "total": p.get("total"), "limite": p["limite"],
                      "dias": dias, "estado": estado, "manual": bool(p.get("manual"))})
    filas.sort(key=lambda f: (f["estado"] == "pagado", f["dias"]))
    pendiente = sum(f["total"] or 0 for f in filas if f["estado"] == "pendiente")
    return {"pagos": filas, "pendiente": pendiente, "ultimo_escaneo": d.get("ultimo_escaneo")}


def gastos(desde, hasta):
    """Lo gastado por proveedor entre dos fechas (date), según la fecha de la factura o del recibo."""
    d = cargar()
    por = {}
    for p in _unicos(d):
        f = p.get("fecha") or p.get("limite") or ""
        try:
            fecha = dt.date.fromisoformat(f[:10])
        except ValueError:
            continue
        if not (desde <= fecha < hasta) or not p.get("total"):
            continue
        nombre = p.get("proveedor") or "Sin nombre"
        g = por.setdefault(nombre, {"proveedor": nombre, "total": 0.0, "n": 0})
        g["total"] += p["total"]
        g["n"] += 1
    return sorted(por.values(), key=lambda g: -g["total"])


def _etiquetar(d=None):
    """Los recibos pendientes llevan la etiqueta «pendiente de pagar»; los pagados, «pagado»."""
    d = d or cargar()
    for p in _unicos(d, "pago"):
        if p.get("manual") or not p.get("ruta"):
            continue
        estado = d["estados"].get(p["clave"], "pendiente")
        if estado == "pagado":
            bd.quitar_etiqueta(p["ruta"], ETIQUETA_PENDIENTE)
            bd.poner_etiqueta(p["ruta"], ETIQUETA_PAGADO)
        elif estado == "pendiente":
            bd.poner_etiqueta(p["ruta"], ETIQUETA_PENDIENTE)
        else:
            bd.quitar_etiqueta(p["ruta"], ETIQUETA_PENDIENTE)


def cambiar(clave_pago, estado):
    """estado: "pagado", "pendiente" o "ignorado"."""
    if estado not in ("pagado", "pendiente", "ignorado"):
        raise ValueError("Estado no válido")
    d = cargar()
    if estado == "pendiente":
        d["estados"].pop(clave_pago, None)
    else:
        d["estados"][clave_pago] = estado
    guardar(d)
    _etiquetar(d)


def agregar(proveedor, limite, total=None):
    dt.date.fromisoformat(limite)
    d = cargar()
    d["manuales"].append({"id": "m" + nucleo.nuevo_id(), "tipo": "pago", "proveedor": proveedor.strip() or "Pago",
                          "limite": limite, "total": float(total) if total not in (None, "") else None, "fecha": ""})
    guardar(d)


def borrar_manual(id_pago):
    d = cargar()
    d["manuales"] = [m for m in d["manuales"] if m["id"] != id_pago]
    guardar(d)


def texto_aviso(p):
    fecha = dt.date.fromisoformat(p["limite"])
    cuando = "hoy" if p["dias"] <= 0 else ("mañana" if p["dias"] == 1 else f"el {fecha.day}")
    total = f', son ${p["total"]:,.2f}' if p.get("total") else ""
    return f'{p["proveedor"]} vence {cuando}{total}.'


def avisar_proximos(hoy=None):
    hoy = hoy or dt.date.today()
    d = cargar()
    cambiado = False
    for p in lista(hoy)["pagos"]:
        if p["estado"] != "pendiente" or p["dias"] < -1:
            continue
        hechos = d["avisos"].setdefault(p["clave"], [])
        for umbral in AVISAR_DIAS:
            if p["dias"] <= umbral and umbral not in hechos:
                hechos.extend(u for u in AVISAR_DIAS if u >= umbral and u not in hechos)
                cambiado = True
                nucleo.avisar("Recordatorio de pago", texto_aviso(p))
                break
    if cambiado:
        guardar(d)


def mantenimiento():
    if not nucleo.cargar_ajustes().get("pagos", True):
        return
    escanear(segundos=15)
    avisar_proximos()
