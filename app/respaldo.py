"""GESTOR: respaldo con versiones. Copia una carpeta (Documentos) a OneDrive, Google Drive o un disco.

Destino\\Actual        espejo de la carpeta tal como está hoy
Destino\\Versiones\\AAAA-MM-DD HHMM\\...   lo que cambió o se borró, tal como estaba antes

Nunca se pierde nada: antes de sobrescribir o quitar algo de "Actual", se guarda en "Versiones".
Las versiones más viejas que N días se borran.
"""

import datetime as dt
import os
import re
import shutil
import time

import nucleo

CARPETA_ACTUAL = "Actual"
CARPETA_VERSIONES = "Versiones"


def destinos_sugeridos():
    """OneDrive, Google Drive y discos externos que haya en el equipo."""
    sugeridos = []
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        ruta = os.environ.get(var)
        if ruta and os.path.isdir(ruta) and all(nucleo._norm(ruta) != nucleo._norm(s["ruta"]) for s in sugeridos):
            sugeridos.append({"nombre": "OneDrive", "ruta": os.path.join(ruta, "Respaldo GESTOR")})
    candidatos = [os.path.join(os.path.expanduser("~"), "Google Drive")]
    if nucleo.ES_WINDOWS:
        for letra in "DEFGHIJKLMNOPQRSTUVWXYZ":
            candidatos += [f"{letra}:\\Mi unidad", f"{letra}:\\My Drive"]
    for c in candidatos:
        if os.path.isdir(c):
            sugeridos.append({"nombre": "Google Drive", "ruta": os.path.join(c, "Respaldo GESTOR")})
            break
    for u in nucleo.unidades_conectadas():
        sugeridos.append({"nombre": f'Disco {u["letra"]} ({u["etiqueta"]})',
                          "ruta": os.path.join(nucleo._raiz_unidad(u["letra"]), "Respaldo GESTOR")})
    return sugeridos


def validar(origen, destino):
    if not origen or not destino:
        return "Elige la carpeta a respaldar y dónde guardarla."
    if nucleo._dentro_de(destino, origen) or nucleo._dentro_de(origen, destino):
        return "El respaldo no puede estar dentro de la carpeta que respalda (ni al revés)."
    return ""


def aviso_nube(origen, destino):
    """Si Documentos ya vive en OneDrive, respaldar en OneDrive solo añade las versiones."""
    for var in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        nube = os.environ.get(var)
        if nube and nucleo._dentro_de(origen, nube) and nucleo._dentro_de(destino, nube):
            return "Tu carpeta ya está en OneDrive: este respaldo guarda versiones, pero en la misma nube."
    return ""


def _sello(ahora=None):
    return (ahora or dt.datetime.now()).strftime("%Y-%m-%d %H%M")


def _guardar_version(actual, versiones, relativa, sello):
    destino = os.path.join(versiones, sello, relativa)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(actual, nucleo._nombre_libre(destino))


def respaldar(origen, destino, cancelado=lambda: False):
    """Pone al día Destino\\Actual y guarda en Destino\\Versiones lo que cambia o desaparece."""
    actual = os.path.join(destino, CARPETA_ACTUAL)
    versiones = os.path.join(destino, CARPETA_VERSIONES)
    sello = _sello()
    copiados = versionados = bytes_copiados = 0
    errores, vistos = [], set()
    for carpeta, subcarpetas, archivos in os.walk(origen):
        if cancelado():
            return {"cancelado": True}
        subcarpetas[:] = [d for d in subcarpetas if not d.startswith((".", "$"))
                          and not nucleo._dentro_de(os.path.join(carpeta, d), destino)]
        relativa_carpeta = os.path.relpath(carpeta, origen)
        nucleo.avance(sumar=len(archivos), etapa="Copiando " + relativa_carpeta.replace(".", "", 1)[:60])
        for nombre in archivos:
            if nucleo._ignorado(nombre, nucleo.IGNORAR_SIEMPRE):
                continue
            relativa = os.path.normpath(os.path.join(relativa_carpeta, nombre))
            vistos.add(relativa.lower() if nucleo.ES_WINDOWS else relativa)
            a = os.path.join(origen, relativa)
            b = os.path.join(actual, relativa)
            try:
                sa = os.stat(a)
                if os.path.exists(b):
                    sb = os.stat(b)
                    if sb.st_size == sa.st_size and abs(sb.st_mtime - sa.st_mtime) < 2:
                        continue
                    _guardar_version(b, versiones, relativa, sello)
                    versionados += 1
                os.makedirs(os.path.dirname(b), exist_ok=True)
                shutil.copy2(a, b)
                copiados += 1
                bytes_copiados += sa.st_size
            except OSError as e:
                errores.append(f"{a}: {e}")
    # Lo que ya no está en el origen sale de "Actual" hacia "Versiones" (no se borra).
    borrados = 0
    if os.path.isdir(actual):
        for carpeta, _, archivos in os.walk(actual):
            for nombre in archivos:
                b = os.path.join(carpeta, nombre)
                relativa = os.path.normpath(os.path.relpath(b, actual))
                if (relativa.lower() if nucleo.ES_WINDOWS else relativa) in vistos:
                    continue
                try:
                    _guardar_version(b, versiones, relativa, sello)
                    borrados += 1
                except OSError as e:
                    errores.append(f"{b}: {e}")
        for carpeta, _, _ in sorted(os.walk(actual), key=lambda x: -len(x[0])):
            if carpeta != actual:
                try:
                    os.rmdir(carpeta)
                except OSError:
                    pass
    return {"copiados": copiados, "versionados": versionados, "borrados": borrados,
            "bytes": bytes_copiados, "errores": errores}


def purgar_versiones(destino, dias):
    """Borra las versiones de hace más de N días. Devuelve cuántas carpetas de versión quitó."""
    versiones = os.path.join(destino, CARPETA_VERSIONES)
    if not dias or not os.path.isdir(versiones):
        return 0
    limite = dt.datetime.now() - dt.timedelta(days=float(dias))
    quitadas = 0
    for nombre in os.listdir(versiones):
        try:
            fecha = dt.datetime.strptime(nombre, "%Y-%m-%d %H%M")
        except ValueError:
            continue
        if fecha < limite:
            shutil.rmtree(os.path.join(versiones, nombre), ignore_errors=True)
            quitadas += 1
    return quitadas


def lista():
    return nucleo.cargar_ajustes().get("respaldos") or []


def estado():
    return nucleo.cargar_estado().get("_respaldos", {})


def ejecutar(r):
    """Ejecuta un respaldo (uno a la vez) y anota el resultado."""
    cerrojo = os.path.join(nucleo.DATOS, f"respaldo-{re.sub(r'[^a-zA-Z0-9]', '', r['id'])}.lock")
    try:
        if os.path.exists(cerrojo) and time.time() - os.path.getmtime(cerrojo) > 12 * 3600:
            os.remove(cerrojo)
        os.close(os.open(cerrojo, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return {"ok": False, "mensaje": "Ese respaldo ya está en marcha."}
    try:
        problema = validar(r.get("origen"), r.get("destino"))
        if problema:
            return {"ok": False, "mensaje": problema}
        if not os.path.isdir(r["origen"]):
            return {"ok": False, "mensaje": "La carpeta a respaldar no existe."}
        raiz_destino = os.path.splitdrive(r["destino"])[0] + os.sep if nucleo.ES_WINDOWS else "/"
        if not os.path.isdir(raiz_destino):
            return {"ok": False, "mensaje": "El disco de destino no está conectado."}
        os.makedirs(r["destino"], exist_ok=True)
        with nucleo.proceso("Respaldo " + (r.get("nombre") or "")):
            res = respaldar(r["origen"], r["destino"])
        res["versiones_quitadas"] = purgar_versiones(r["destino"], r.get("dias_versiones", 90))
        est = nucleo.cargar_estado()
        est.setdefault("_respaldos", {})[r["id"]] = {
            "ultima": dt.datetime.now().isoformat(timespec="seconds"), "copiados": res["copiados"],
            "versionados": res["versionados"] + res["borrados"], "bytes": res["bytes"],
            "errores": len(res["errores"])}
        nucleo.guardar_estado(est)
        if res["copiados"] or res["errores"]:
            texto = f'{res["copiados"]} archivos al día'
            if res["versionados"] + res["borrados"]:
                texto += f', {res["versionados"] + res["borrados"]} versiones guardadas'
            if res["errores"]:
                texto += f', {len(res["errores"])} con error'
            nucleo.avisar(f'Respaldo {r.get("nombre") or ""}'.strip(), texto)
        res["errores"] = res["errores"][:50]
        res["ok"] = True
        return res
    finally:
        try:
            os.remove(cerrojo)
        except OSError:
            pass


def pendientes(ahora=None):
    ahora = ahora or dt.datetime.now()
    est = estado()
    salida = []
    for r in lista():
        if not r.get("activo", True):
            continue
        ultima = (est.get(r["id"]) or {}).get("ultima")
        cada = dt.timedelta(hours=float(r.get("cada_horas") or 24))
        if not ultima or ahora - dt.datetime.fromisoformat(ultima) >= cada:
            salida.append(r)
    return salida


def mantenimiento():
    """Lo llama el motor: ejecuta los respaldos a los que les toca."""
    for r in pendientes():
        ejecutar(r)


def buscar_versiones(destino, texto, limite=200):
    """Versiones guardadas de los archivos cuyo nombre contiene el texto, de la más nueva a la más vieja."""
    versiones = os.path.join(destino, CARPETA_VERSIONES)
    palabras = [p for p in nucleo.sin_acentos((texto or "").lower()).split() if p]
    resultados = []
    if not os.path.isdir(versiones):
        return resultados
    for sello in sorted(os.listdir(versiones), reverse=True):
        base = os.path.join(versiones, sello)
        for carpeta, _, archivos in os.walk(base):
            for n in archivos:
                if palabras and not all(p in nucleo.sin_acentos(n.lower()) for p in palabras):
                    continue
                ruta = os.path.join(carpeta, n)
                try:
                    tam = os.path.getsize(ruta)
                except OSError:
                    continue
                resultados.append({"version": sello, "ruta": ruta, "relativa": os.path.relpath(ruta, base),
                                   "bytes": tam})
                if len(resultados) >= limite:
                    return resultados
    return resultados


def restaurar_version(r, ruta_version):
    """Devuelve una versión a su sitio. Si allí hay otro archivo, ese va antes a la papelera de GESTOR."""
    versiones = os.path.join(r["destino"], CARPETA_VERSIONES)
    if not nucleo._dentro_de(ruta_version, versiones) or not os.path.isfile(ruta_version):
        raise ValueError("Esa versión no existe.")
    relativa = os.path.relpath(ruta_version, versiones).split(os.sep, 1)[1]
    original = os.path.join(r["origen"], relativa)
    if os.path.exists(original):
        nucleo.quitar(original, "sustituido por una versión del respaldo")
    os.makedirs(os.path.dirname(original), exist_ok=True)
    shutil.copy2(ruta_version, original)
    return original
