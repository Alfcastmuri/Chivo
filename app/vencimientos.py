"""GESTOR: vencimientos. Lee la fecha de vigencia de pólizas, INE, pasaportes, contratos...
y avisa un mes antes (y una semana antes, y el día) de que venzan.

El análisis es incremental: cada revisión del motor dedica unos segundos y recuerda lo ya leído,
así que la primera vez puede tardar varias revisiones en terminar.
"""

import datetime as dt
import os
import re
import time

import nucleo

ARCHIVO = os.path.join(nucleo.DATOS, "vencimientos.json")
EXT = {".pdf", ".docx", ".txt"}
AVISAR_DIAS = (30, 7, 0)

# (tipo, palabras en el nombre o el contenido). Se comparan sin acentos.
TIPOS = [
    ("Póliza de seguro", ["poliza", "seguro", "aseguradora", "cobertura"]),
    ("INE", ["ine", "credencial para votar", "instituto nacional electoral"]),
    ("Pasaporte", ["pasaporte", "passport"]),
    ("Visa", ["visa"]),
    ("Licencia de conducir", ["licencia de conducir", "licencia"]),
    ("Contrato", ["contrato", "arrendamiento", "convenio"]),
    ("Garantía", ["garantia", "warranty"]),
    ("Coche", ["tarjeta de circulacion", "verificacion vehicular", "tenencia", "refrendo"]),
    ("Membresía", ["membresia", "suscripcion", "anualidad"]),
    ("Certificado", ["certificado", "certificacion", "cedula"]),
]

_CLAVE = re.compile(
    r"(vigencia|vigente\s+hasta|v[aá]lid[oa]\s+hasta|vence|vencimiento|fecha\s+de\s+(?:expiraci[oó]n|caducidad|"
    r"vencimiento|t[eé]rmino|terminaci[oó]n)|expira|caduca|fin\s+de\s+(?:la\s+)?vigencia|hasta\s+el|"
    r"date\s+of\s+expiry|expiry\s+date|expiration(?:\s+date)?|valid\s+(?:until|thru|through)|good\s+thru)",
    re.IGNORECASE)
_MESES = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "aug": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
_F_DMA = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_F_AMD = re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b")
_F_TEXTO = re.compile(r"\b(\d{1,2})(?:\s+de)?[\s/\-.]+([a-záéíóú]{3,10})\.?(?:\s+de(?:l)?)?[\s/\-.]+(\d{4})\b",
                      re.IGNORECASE)
_F_ANIO = re.compile(r"\b(20\d{2})\b")


def _fecha(a, m, d):
    try:
        f = dt.date(int(a), int(m), int(d))
    except ValueError:
        return None
    return f if 2000 <= f.year <= 2100 else None


def fechas_en(texto):
    """Fechas completas que aparecen en un trozo de texto (dd/mm/aaaa, aaaa-mm-dd, 15 de marzo de 2027)."""
    fechas = []
    for d, m, a in _F_DMA.findall(texto):
        fechas.append(_fecha(a, m, d))
    for a, m, d in _F_AMD.findall(texto):
        fechas.append(_fecha(a, m, d))
    for d, mes, a in _F_TEXTO.findall(texto):
        m = _MESES.get(nucleo.sin_acentos(mes.lower())[:3])
        if m:
            fechas.append(_fecha(a, m, d))
    return [f for f in fechas if f]


def fecha_vencimiento(texto):
    """La fecha de vencimiento de un documento: la última fecha que sigue a "vigencia", "vence", etc.

    "VIGENCIA 2020 - 2030" (como en la INE) se toma como el 31 de diciembre del último año.
    """
    candidatas, fragmento = [], ""
    for m in _CLAVE.finditer(texto or ""):
        ventana = texto[m.end():m.end() + 120]
        fechas = fechas_en(ventana)
        if not fechas:
            anios = [int(a) for a in _F_ANIO.findall(ventana[:30])]
            fechas = [dt.date(max(anios), 12, 31)] if anios else []
        if fechas:
            mejor = max(fechas)
            if not candidatas or mejor > max(candidatas):
                fragmento = re.sub(r"\s+", " ", texto[m.start():m.end() + 60]).strip()
            candidatas.append(mejor)
    return (max(candidatas), fragmento) if candidatas else (None, "")


def tipo_de(nombre, texto=""):
    """(tipo, por_nombre): el tipo de documento según su nombre o, si no, su contenido."""
    n = nucleo.sin_acentos(os.path.splitext(nombre)[0].lower())
    t = nucleo.sin_acentos((texto or "")[:5000].lower())
    for tipo, palabras in TIPOS:
        for p in palabras:
            if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", n):
                return tipo, True
    for tipo, palabras in TIPOS:
        for p in palabras:
            if len(p) > 4 and re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t):
                return tipo, False
    return None, False


def cargar():
    d = nucleo.leer_json(ARCHIVO, {})
    for k, v in (("archivos", {}), ("manuales", []), ("ignorados", []), ("cambios", {}), ("avisos", {})):
        d.setdefault(k, v)
    return d


def guardar(d):
    nucleo.escribir_json(ARCHIVO, d)


def carpetas_a_revisar():
    extra = nucleo.cargar_ajustes().get("carpetas_vencimientos") or []
    return [nucleo.carpeta_conocida("Documentos")] + [c for c in extra if c]


def analizar(ruta):
    """{tipo, fecha, fragmento} de un archivo, o None si no parece un documento que venza."""
    nombre = os.path.basename(ruta)
    texto = nucleo.texto_de(ruta)
    tipo, por_nombre = tipo_de(nombre, texto)
    if not tipo:
        return None
    fecha, fragmento = fecha_vencimiento(texto)
    if not fecha and not por_nombre:
        return None  # por el contenido y sin fecha: probablemente no es un documento que venza
    return {"tipo": tipo, "fecha": fecha.isoformat() if fecha else "", "fragmento": fragmento[:160]}


def escanear(segundos=20, limite=30000):
    """Analiza los documentos nuevos o cambiados durante unos segundos. Devuelve True si terminó."""
    d = cargar()
    archivos = d["archivos"]
    inicio, vistos, terminado = time.time(), set(), True
    for raiz in carpetas_a_revisar():
        if not os.path.isdir(raiz):
            continue
        for carpeta, subcarpetas, nombres in os.walk(raiz):
            subcarpetas[:] = [s for s in subcarpetas if not s.startswith((".", "$"))]
            nucleo.avance(sumar=len(nombres), etapa="Leyendo documentos")
            for n in nombres:
                if os.path.splitext(n)[1].lower() not in EXT or nucleo._ignorado(n, nucleo.IGNORAR_SIEMPRE):
                    continue
                ruta = os.path.join(carpeta, n)
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
                if time.time() - inicio > segundos:
                    terminado = False
                    continue
                if st.st_size > 30 * 1024 * 1024:
                    archivos[ruta] = {"mtime": int(st.st_mtime), "tipo": None}
                    continue
                datos = analizar(ruta) or {"tipo": None}
                datos["mtime"] = int(st.st_mtime)
                archivos[ruta] = datos
    if terminado:
        # Lo que ya no existe (o se movió) se olvida; su nueva ubicación se analiza aparte.
        for ruta in [r for r in archivos if r not in vistos]:
            del archivos[ruta]
        d["ultimo_escaneo"] = time.time()
    guardar(d)
    return terminado


def lista(hoy=None):
    """Todos los vencimientos conocidos, del más próximo al más lejano."""
    hoy = hoy or dt.date.today()
    d = cargar()
    filas = []
    for ruta, a in d["archivos"].items():
        if not a.get("tipo") or ruta in d["ignorados"]:
            continue
        fecha = d["cambios"].get(ruta) or a.get("fecha")
        filas.append({"clave": ruta, "ruta": ruta, "nombre": os.path.basename(ruta), "tipo": a["tipo"],
                      "fecha": fecha or "", "fragmento": a.get("fragmento", ""), "manual": False,
                      "corregida": ruta in d["cambios"]})
    for m in d["manuales"]:
        filas.append({"clave": m["id"], "ruta": m.get("ruta", ""), "nombre": m["nombre"], "tipo": m.get("tipo") or "Otro",
                      "fecha": m["fecha"], "fragmento": "", "manual": True, "corregida": False})
    for f in filas:
        f["dias"] = (dt.date.fromisoformat(f["fecha"]) - hoy).days if f["fecha"] else None
    filas.sort(key=lambda f: (f["dias"] is None, f["dias"] if f["dias"] is not None else 0))
    return {"vencimientos": filas, "ultimo_escaneo": d.get("ultimo_escaneo")}


def avisar_proximos(hoy=None):
    """Avisa a 30 días, a 7 días y el mismo día. Cada aviso, una sola vez."""
    hoy = hoy or dt.date.today()
    d = cargar()
    enviados = d["avisos"]
    cambiado = False
    for f in lista(hoy)["vencimientos"]:
        if f["dias"] is None or f["dias"] < -1:
            continue
        clave = f'{f["clave"]}|{f["fecha"]}'
        hechos = enviados.setdefault(clave, [])
        for umbral in AVISAR_DIAS:
            if f["dias"] <= umbral and umbral not in hechos:
                hechos.extend(u for u in AVISAR_DIAS if u >= umbral and u not in hechos)
                cambiado = True
                cuando = "hoy" if f["dias"] <= 0 else ("mañana" if f["dias"] == 1 else f'en {f["dias"]} días')
                fecha = dt.date.fromisoformat(f["fecha"]).strftime("%d/%m/%Y")
                nucleo.avisar(f'Vence {cuando}: {f["tipo"]}', f'{f["nombre"]} vence el {fecha}.')
                break
    if cambiado:
        guardar(d)


def mantenimiento():
    """Lo llama el motor: unos segundos de análisis y los avisos que toquen."""
    if not nucleo.cargar_ajustes().get("vencimientos", True):
        return
    escanear(segundos=15)
    avisar_proximos()


def cambiar(clave, fecha=None, ignorar=False, borrar=False):
    d = cargar()
    if borrar:
        d["manuales"] = [m for m in d["manuales"] if m["id"] != clave]
    elif ignorar:
        if clave not in d["ignorados"]:
            d["ignorados"].append(clave)
        d["manuales"] = [m for m in d["manuales"] if m["id"] != clave]
    else:
        dt.date.fromisoformat(fecha)  # valida
        manual = next((m for m in d["manuales"] if m["id"] == clave), None)
        if manual:
            manual["fecha"] = fecha
        else:
            d["cambios"][clave] = fecha
    guardar(d)


def agregar(nombre, fecha, tipo="", ruta=""):
    dt.date.fromisoformat(fecha)
    d = cargar()
    d["manuales"].append({"id": "m" + nucleo.nuevo_id(), "nombre": nombre.strip() or "Documento",
                          "fecha": fecha, "tipo": tipo, "ruta": ruta})
    guardar(d)
