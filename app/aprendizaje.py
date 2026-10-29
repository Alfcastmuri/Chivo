"""GESTOR: aprender de ti. Cuando mueves a mano archivos a una carpeta de Documentos, GESTOR
busca qué tienen en común (una palabra del nombre) y te propone una regla para hacerlo solo.

El proceso residente vigila Documentos y llama a observar(); cada cierto tiempo, a pensar().
"""

import datetime as dt
import os
import re
import time

import nucleo

ARCHIVO = os.path.join(nucleo.DATOS, "aprendizaje.json")
MAX_OBSERVACIONES = 600
MINIMO_EJEMPLOS = 2
NOMBRE_SERVICIO = "Aprendido de ti"

# Palabras que no dicen nada de a dónde va un archivo.
VACIAS = set("""
de del la las el los y e o u en con para por al un una unos unas su sus mi mis tu tus
copia copy final nuevo nueva new version ver rev borrador draft doc docx documento document archivo file
scan escaneo escaneado img image imagen foto photo screenshot captura pdf jpg png xlsx xls txt zip
page pagina hoja parte part sin titulo untitled descarga download whatsapp telegram
enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre
ene feb mar abr may jun jul ago sep oct nov dic jan apr aug dec
""".split())


def cargar():
    d = nucleo.leer_json(ARCHIVO, {})
    for k, v in (("observaciones", []), ("propuestas", []), ("descartadas", []), ("aceptadas", [])):
        d.setdefault(k, v)
    return d


def guardar(d):
    nucleo.escribir_json(ARCHIVO, d)


def palabras(nombre):
    base = nucleo.sin_acentos(os.path.splitext(os.path.basename(nombre))[0].lower())
    vistas = []
    for p in re.split(r"[^a-z0-9ñ&]+", base):
        if len(p) < 3 or p in VACIAS or p.isdigit() or re.fullmatch(r"\d+[a-z]{0,2}|[a-z]\d+", p):
            continue
        if p not in vistas:
            vistas.append(p)
    return vistas


def carpeta_aprendible(ruta, documentos=None):
    """La subcarpeta de Documentos donde cayó el archivo (no la raíz ni carpetas de GESTOR o programas)."""
    documentos = documentos or nucleo.carpeta_conocida("Documentos")
    carpeta = os.path.dirname(ruta)
    if not nucleo._dentro_de(carpeta, documentos) or nucleo._norm(carpeta) == nucleo._norm(documentos):
        return None
    relativa = os.path.relpath(carpeta, documentos)
    partes = relativa.split(os.sep)
    if partes[0].lower().startswith("de ") or partes[0].startswith(".") or len(partes) > 4:
        return None  # "De Descargas", "De Escritorio": son de GESTOR
    # Subcarpetas de año o de mes ("Facturas\CFE\2026") no son el sitio: lo es su carpeta padre.
    while partes and re.fullmatch(r"(19|20)\d{2}(-\d{2})?|\d{2}-[A-Za-zéá]+|\d{1,2}", partes[-1]):
        partes.pop()
    return os.path.join(documentos, *partes) if partes else None


def _hecho_por_gestor(ruta, minutos=20):
    """¿Lo movió GESTOR? Se mira el final del índice del buscador."""
    limite = time.time() - minutos * 60
    objetivo = nucleo._norm(ruta)
    try:
        with open(nucleo.ARCHIVO_INDICE, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400_000))
            lineas = f.read().decode("utf-8", "ignore").splitlines()[1:]
    except OSError:
        return False
    import json
    for linea in reversed(lineas):
        try:
            r = json.loads(linea)
        except ValueError:
            continue
        if r["t"] < limite:
            break
        if r.get("d") and nucleo._norm(r["d"]) == objetivo:
            return True
    return False


def observar(ruta, origen=None):
    """Anota que apareció un archivo en una carpeta de Documentos (lo mueve el residente)."""
    if not nucleo.cargar_ajustes().get("aprender", True):
        return False
    nombre = os.path.basename(ruta)
    if nucleo._ignorado(nombre, nucleo.IGNORAR_SIEMPRE) or nombre.startswith((".", "~")):
        return False
    if origen and nucleo._norm(os.path.dirname(origen)) == nucleo._norm(os.path.dirname(ruta)):
        return False  # solo lo renombraron
    carpeta = carpeta_aprendible(ruta)
    if not carpeta:
        return False
    d = cargar()
    if any(o["ruta"] == ruta for o in d["observaciones"][-50:]):
        return False
    d["observaciones"].append({"ruta": ruta, "carpeta": carpeta, "palabras": palabras(nombre),
                               "ext": os.path.splitext(nombre)[1].lower(), "t": time.time(), "revisar": True})
    d["observaciones"] = d["observaciones"][-MAX_OBSERVACIONES:]
    guardar(d)
    return True


def _ya_cubierto(palabra, carpeta, servicios):
    """¿Hay ya una regla que manda esa palabra a esa carpeta?"""
    for s in servicios:
        for r in s.get("reglas", []):
            destino = r.get("destino") or ""
            raiz = nucleo._raiz_fija(destino) or destino
            if not raiz or not (nucleo._dentro_de(raiz, carpeta) or nucleo._dentro_de(carpeta, raiz)):
                continue
            valor = nucleo.sin_acentos(str((r.get("si") or {}).get("nombre_valor") or "").lower())
            if palabra in valor:
                return True
    return False


def pensar():
    """Revisa lo observado y crea propuestas nuevas. Devuelve las propuestas nuevas."""
    d = cargar()
    pendientes = [o for o in d["observaciones"] if o.pop("revisar", False)]
    if not pendientes:
        return []
    # Lo que movió el propio GESTOR no cuenta.
    d["observaciones"] = [o for o in d["observaciones"]
                          if not (any(o is p for p in pendientes) and _hecho_por_gestor(o["ruta"]))]
    por_palabra = {}
    for o in d["observaciones"]:
        for p in o["palabras"]:
            por_palabra.setdefault(p, {}).setdefault(o["carpeta"], set()).add(os.path.basename(o["ruta"]).lower())
    servicios = nucleo.cargar_servicios()
    ya = {(p["palabra"], p["carpeta"]) for p in d["propuestas"]} | \
        {(x["palabra"], x["carpeta"]) for x in d["descartadas"] + d["aceptadas"]}
    nuevas = []
    for palabra, carpetas in por_palabra.items():
        mejor = max(carpetas, key=lambda c: len(carpetas[c]))
        ejemplos = sorted(carpetas[mejor])
        otras = sum(len(v) for c, v in carpetas.items() if c != mejor)
        if len(ejemplos) < MINIMO_EJEMPLOS or otras * 3 > len(ejemplos) or (palabra, mejor) in ya:
            continue
        if _ya_cubierto(palabra, mejor, servicios):
            continue
        nuevas.append({"id": nucleo.nuevo_id(), "palabra": palabra, "carpeta": mejor, "ejemplos": ejemplos[:5],
                       "n": len(ejemplos), "fecha": dt.datetime.now().isoformat(timespec="seconds")})
    # Si dos palabras van siempre juntas ("estado" y "cuenta"), basta con una propuesta.
    nuevas.sort(key=lambda p: (-p["n"], -len(p["palabra"])))
    filtradas = []
    for p in nuevas:
        if any(q["carpeta"] == p["carpeta"] and q["ejemplos"] == p["ejemplos"] for q in filtradas):
            continue
        filtradas.append(p)
    d["propuestas"].extend(filtradas)
    guardar(d)
    for p in filtradas:
        nucleo.avisar("GESTOR aprendió algo",
                      f'Mueves a «{os.path.basename(p["carpeta"])}» los archivos con «{p["palabra"]}». '
                      "¿Lo hago yo la próxima vez? Míralo en el panel.")
    return filtradas


def propuestas():
    return cargar()["propuestas"]


def aceptar(pid, origenes=None):
    """Convierte la propuesta en una regla del servicio "Aprendido de ti" (que arranca en modo prueba)."""
    import plantillas
    d = cargar()
    p = next((x for x in d["propuestas"] if x["id"] == pid), None)
    if not p:
        raise ValueError("Esa propuesta ya no existe.")
    regla = {"id": nucleo.nuevo_id(), "si": {"nombre_modo": "regex", "nombre_valor": plantillas.patron(p["palabra"])},
             "accion": "mover", "destino": p["carpeta"], "fecha": "modificacion", "nuevo_nombre": ""}
    servicios = nucleo.cargar_servicios()
    servicio = next((s for s in servicios if s.get("nombre") == NOMBRE_SERVICIO), None)
    if not servicio:
        servicio = {
            "id": nucleo.nuevo_id(), "nombre": NOMBRE_SERVICIO, "activo": True, "modo_prueba": True,
            "origenes": origenes or [nucleo.carpeta_conocida("Descargas"), nucleo.carpeta_conocida("Escritorio")],
            "subcarpetas": False, "horario": {"tipo": "intervalo", "cada": 1, "unidad": "horas"},
            "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
            "mover_hermanos": True, "esperar_minutos": 10, "ignorar": [], "reglas": []}
        servicios.append(servicio)
    servicio["reglas"].insert(0, regla)
    nucleo.guardar_servicios(servicios)
    d["propuestas"] = [x for x in d["propuestas"] if x["id"] != pid]
    d["aceptadas"].append({"palabra": p["palabra"], "carpeta": p["carpeta"]})
    guardar(d)
    return servicio


def descartar(pid):
    d = cargar()
    p = next((x for x in d["propuestas"] if x["id"] == pid), None)
    if p:
        d["descartadas"].append({"palabra": p["palabra"], "carpeta": p["carpeta"]})
        d["propuestas"] = [x for x in d["propuestas"] if x["id"] != pid]
        guardar(d)
