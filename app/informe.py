"""GESTOR: informe mensual en PDF.

El día 1 de cada mes (o cuando lo pidas en el panel) crea en Documentos\\GESTOR\\Informes un PDF con:
lo que se ordenó (por servicio, por tipo y por día), el espacio liberado, los gastos por proveedor,
los pagos pendientes, los próximos vencimientos y cómo están los discos.

El PDF se escribe a mano (sin librerías): texto con Helvetica y barras de colores.
"""

import calendar
import datetime as dt
import os
import time

import bd
import nucleo

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
ACENTO = (0.23, 0.42, 0.85)
TEXTO = (0.13, 0.15, 0.2)
SUAVE = (0.45, 0.48, 0.55)
FONDO = (0.95, 0.96, 0.98)
COLORES = [(0.23, 0.42, 0.85), (0.18, 0.65, 0.5), (0.95, 0.6, 0.15), (0.85, 0.3, 0.35), (0.55, 0.4, 0.8),
           (0.2, 0.65, 0.8), (0.6, 0.6, 0.2), (0.8, 0.45, 0.6), (0.4, 0.5, 0.6), (0.3, 0.7, 0.3)]


# --------------------------------------------------------------------------- PDF mínimo

class PDF:
    ANCHO, ALTO, MARGEN = 595, 842, 48

    def __init__(self):
        self.paginas = []
        self.nueva()

    def nueva(self):
        self.ops = []
        self.paginas.append(self.ops)
        self.y = self.ALTO - self.MARGEN

    def espacio(self, alto):
        if self.y - alto < self.MARGEN:
            self.nueva()

    @staticmethod
    def _esc(s):
        s = str(s).encode("cp1252", "replace").decode("cp1252")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    @staticmethod
    def ancho(s, tam, negrita=False):
        return len(str(s)) * tam * (0.56 if negrita else 0.5)

    def texto(self, x, y, s, tam=10, negrita=False, color=TEXTO, derecha=False):
        if derecha:
            x -= self.ancho(s, tam, negrita)
        r, g, b = color
        self.ops.append(f"BT /{'F2' if negrita else 'F1'} {tam} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                        f"{x:.1f} {y:.1f} Td ({self._esc(s)}) Tj ET")

    def rect(self, x, y, w, h, color):
        r, g, b = color
        self.ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.1f} {y:.1f} {max(w, 0):.1f} {h:.1f} re f")

    def guardar(self, ruta):
        objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        hijos = []
        for ops in self.paginas:
            contenido = "\n".join(ops).encode("cp1252", "replace")
            objetos.append(b"<< /Length %d >>\nstream\n" % len(contenido) + contenido + b"\nendstream")
            objetos.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                           b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (self.ANCHO, self.ALTO, len(objetos)))
            hijos.append(len(objetos))
        objetos[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{h} 0 R" for h in hijos).encode(), len(hijos))
        salida, posiciones = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, obj in enumerate(objetos, 1):
            posiciones.append(len(salida))
            salida += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        xref = len(salida)
        salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        salida += b"".join(b"%010d 00000 n \n" % p for p in posiciones)
        salida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(bytes(salida))


# --------------------------------------------------------------------------- piezas del informe

def _seccion(pdf, titulo, ayuda=""):
    pdf.espacio(60)
    pdf.y -= 22
    pdf.texto(pdf.MARGEN, pdf.y, titulo, 13, True)
    pdf.rect(pdf.MARGEN, pdf.y - 6, 36, 2.5, ACENTO)
    pdf.y -= 12
    if ayuda:
        pdf.y -= 8
        pdf.texto(pdf.MARGEN, pdf.y, ayuda, 8.5, color=SUAVE)
    pdf.y -= 6


def _barras(pdf, filas, formato=str, vacio="Nada este mes."):
    """filas: [(etiqueta, valor)] → barras horizontales con el valor a la derecha."""
    if not filas:
        pdf.y -= 14
        pdf.texto(pdf.MARGEN, pdf.y, vacio, 9.5, color=SUAVE)
        return
    maximo = max(v for _, v in filas) or 1
    x0, ancho = pdf.MARGEN + 150, pdf.ANCHO - 2 * pdf.MARGEN - 150 - 80
    for i, (etiqueta, valor) in enumerate(filas):
        pdf.espacio(18)
        pdf.y -= 17
        etiqueta = str(etiqueta)
        pdf.texto(pdf.MARGEN, pdf.y + 2, etiqueta if len(etiqueta) <= 28 else etiqueta[:27] + "…", 9.5)
        pdf.rect(x0, pdf.y, ancho, 11, FONDO)
        pdf.rect(x0, pdf.y, ancho * valor / maximo, 11, COLORES[i % len(COLORES)])
        pdf.texto(pdf.ANCHO - pdf.MARGEN, pdf.y + 2, formato(valor), 9.5, True, derecha=True)


def _lista(pdf, filas, vacio):
    """filas: [(izquierda, derecha)]."""
    if not filas:
        pdf.y -= 14
        pdf.texto(pdf.MARGEN, pdf.y, vacio, 9.5, color=SUAVE)
        return
    for izq, der in filas:
        pdf.espacio(16)
        pdf.y -= 15
        izq = str(izq)
        pdf.texto(pdf.MARGEN, pdf.y, izq if len(izq) <= 70 else izq[:69] + "…", 9.5)
        pdf.texto(pdf.ANCHO - pdf.MARGEN, pdf.y, der, 9.5, True, derecha=True)


def _pesos(v):
    return "${:,.2f}".format(v)


def periodo(anio=None, mes=None):
    """(inicio, fin) del mes pedido o, si no se dice, del mes anterior."""
    if not anio:
        hoy = dt.date.today().replace(day=1) - dt.timedelta(days=1)
        anio, mes = hoy.year, hoy.month
    inicio = dt.date(anio, mes, 1)
    fin = inicio + dt.timedelta(days=calendar.monthrange(anio, mes)[1])
    return inicio, fin


def carpeta_informes():
    return os.path.join(nucleo.carpeta_conocida("Documentos"), "GESTOR", "Informes")


def datos(anio=None, mes=None):
    import pagos
    import vencimientos
    inicio, fin = periodo(anio, mes)
    t0 = time.mktime(inicio.timetuple())
    t1 = time.mktime(fin.timetuple())
    r = bd.resumen_periodo(t0, t1)
    gestor = [s for s in r["servicios"] if s["quien"] != "tu"]
    por_servicio = {}
    for s in gestor:
        por_servicio[s["servicio"] or "Sin nombre"] = por_servicio.get(s["servicio"] or "Sin nombre", 0) + s["n"]
    por_tipo = {}
    for ext in r["extensiones"]:
        cat = nucleo.categoria_de(ext)
        por_tipo[cat] = por_tipo.get(cat, 0) + 1
    dias = [0] * (fin - inicio).days
    for t in r["tiempos"]:
        i = (dt.date.fromtimestamp(t) - inicio).days
        if 0 <= i < len(dias):
            dias[i] += 1
    gastos = pagos.gastos(inicio, fin)
    return {
        "inicio": inicio, "fin": fin,
        "ordenados": sum(s["n"] for s in gestor),
        "tuyos": sum(s["n"] for s in r["servicios"] if s["quien"] == "tu"),
        "liberado": sum(s["bytes_papelera"] for s in r["servicios"]),
        "por_servicio": sorted(por_servicio.items(), key=lambda x: -x[1])[:10],
        "por_tipo": sorted(por_tipo.items(), key=lambda x: -x[1])[:8],
        "dias": dias,
        "gastos": gastos,
        "gasto_total": sum(g["total"] for g in gastos),
        "pendientes": [p for p in pagos.lista()["pagos"] if p["estado"] == "pendiente"][:12],
        "vencimientos": [v for v in vencimientos.lista()["vencimientos"]
                         if v["dias"] is not None and 0 <= v["dias"] <= 60][:12],
        "discos": nucleo.unidades_fijas(),
    }


def generar(anio=None, mes=None, ruta=None):
    d = datos(anio, mes)
    nombre_mes = f'{MESES[d["inicio"].month]} de {d["inicio"].year}'
    ruta = ruta or os.path.join(carpeta_informes(), f'Informe GESTOR {d["inicio"]:%Y-%m}.pdf')
    pdf = PDF()
    m, w = pdf.MARGEN, pdf.ANCHO - 2 * pdf.MARGEN
    # Encabezado
    pdf.rect(0, pdf.ALTO - 110, pdf.ANCHO, 110, ACENTO)
    pdf.texto(m, pdf.ALTO - 58, "Informe de GESTOR", 24, True, color=(1, 1, 1))
    pdf.texto(m, pdf.ALTO - 82, nombre_mes.capitalize(), 13, color=(0.9, 0.93, 1))
    pdf.y = pdf.ALTO - 130
    # Tarjetas
    tarjetas = [("Archivos ordenados", f'{d["ordenados"]:,}'), ("Movidos por ti", f'{d["tuyos"]:,}'),
                ("Espacio liberado", nucleo.tamano_legible(d["liberado"])), ("Gastos registrados", _pesos(d["gasto_total"]))]
    ancho_t = (w - 3 * 10) / 4
    for i, (titulo, valor) in enumerate(tarjetas):
        x = m + i * (ancho_t + 10)
        pdf.rect(x, pdf.y - 58, ancho_t, 58, FONDO)
        pdf.rect(x, pdf.y - 58, 3, 58, COLORES[i])
        pdf.texto(x + 12, pdf.y - 22, titulo, 8.5, color=SUAVE)
        pdf.texto(x + 12, pdf.y - 44, valor, 15, True)
    pdf.y -= 70
    # Actividad por día
    _seccion(pdf, "Actividad del mes", "Archivos que GESTOR ordenó cada día.")
    maximo = max(d["dias"]) or 1
    alto, ancho_b = 70, w / max(len(d["dias"]), 1)
    pdf.y -= alto + 4
    pdf.rect(m, pdf.y, w, alto, FONDO)
    for i, n in enumerate(d["dias"]):
        if n:
            pdf.rect(m + i * ancho_b + 1, pdf.y, ancho_b - 2, alto * n / maximo, ACENTO)
    for i in (0, len(d["dias"]) // 2, len(d["dias"]) - 1):
        pdf.texto(m + i * ancho_b, pdf.y - 11, str(i + 1), 7.5, color=SUAVE)
    pdf.y -= 12
    _seccion(pdf, "Por servicio")
    _barras(pdf, d["por_servicio"], lambda v: f"{v:,}")
    _seccion(pdf, "Por tipo de archivo")
    _barras(pdf, d["por_tipo"], lambda v: f"{v:,}")
    _seccion(pdf, "Gastos por proveedor", "Según las facturas y recibos que GESTOR encontró en Documentos y Descargas.")
    _barras(pdf, [(g["proveedor"], g["total"]) for g in d["gastos"][:10]], _pesos, "No encontré facturas de este mes.")
    _seccion(pdf, "Pagos pendientes")
    _lista(pdf, [(f'{p["proveedor"]} · vence {dt.date.fromisoformat(p["limite"]):%d/%m/%Y}',
                  _pesos(p["total"]) if p.get("total") else "") for p in d["pendientes"]], "No hay pagos pendientes.")
    _seccion(pdf, "Próximos vencimientos (60 días)")
    _lista(pdf, [(f'{v["tipo"]}: {v["nombre"]}', f'{dt.date.fromisoformat(v["fecha"]):%d/%m/%Y}')
                 for v in d["vencimientos"]], "Nada vence en los próximos 60 días.")
    _seccion(pdf, "Discos")
    _barras(pdf, [(f'{u["letra"]}  ({nucleo.tamano_legible(u["libre"])} libres)', round(100 - u["libre"] * 100 / u["total"]))
                  for u in d["discos"] if u.get("total")], lambda v: f"{v} % usado", "Sin datos de discos.")
    for i, ops in enumerate(pdf.paginas, 1):
        pdf.ops = ops
        pdf.texto(m, 24, f"Generado por GESTOR {nucleo.VERSION} el {dt.datetime.now():%d/%m/%Y %H:%M}", 7.5, color=SUAVE)
        pdf.texto(pdf.ANCHO - m, 24, f"Página {i} de {len(pdf.paginas)}", 7.5, color=SUAVE, derecha=True)
    pdf.guardar(ruta)
    return {"ok": True, "ruta": ruta, "mensaje": f"Informe de {nombre_mes} guardado en {ruta}"}


def lista():
    c = carpeta_informes()
    if not os.path.isdir(c):
        return []
    return [{"ruta": os.path.join(c, n), "nombre": n, "bytes": os.path.getsize(os.path.join(c, n))}
            for n in sorted(os.listdir(c), reverse=True) if n.lower().endswith(".pdf")][:24]


def mantenimiento(hoy=None):
    """El día 1 (o la primera revisión del mes) genera el informe del mes anterior y avisa."""
    if not nucleo.cargar_ajustes().get("informe_mensual", True):
        return
    inicio, _ = periodo()
    clave = f"{inicio:%Y-%m}"
    if bd.leer("informe:ultimo", "") == clave:
        return
    r = generar()
    bd.escribir("informe:ultimo", clave)
    nucleo.avisar("Informe mensual listo", f'Tu informe de {MESES[inicio.month]} está en Documentos\\GESTOR\\Informes.')
    return r
