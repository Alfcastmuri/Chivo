"""GESTOR: plantillas prehechas para cada tipo de carpeta.

Documentos se ordena hacia las subcarpetas que ya existen (Facturas, Contratos, Bancos...).
Las demás plantillas mandan los documentos a esas mismas carpetas de Documentos; solo si no
hay ninguna que encaje usan una carpeta genérica dentro de Documentos.
"""

import os
import re

import nucleo

# Tipos de documento: (clave, nombres de carpeta que lo representan, palabras en el nombre del
# archivo, palabras en el contenido o None). Los nombres se comparan sin acentos ni mayúsculas.
TIPOS = [
    ("facturas", ["facturas", "factura", "invoices", "cfdi", "comprobantes fiscales", "xml facturas"],
     "factura|cfdi|invoice", None),
    ("recibos", ["recibos", "tickets", "pagos", "comprobantes", "comprobantes de pago", "recibos de pago"],
     "recibo|ticket|comprobante de pago|comprobante_pago|transferencia|spei", None),
    ("servicios", ["servicios", "luz agua gas", "recibos de servicios", "casa"],
     "cfe|telmex|izzi|totalplay|megacable|predial|agua|naturgy|gas natural|telcel|at&t", None),
    ("bancos", ["bancos", "banco", "estados de cuenta", "finanzas", "tarjetas", "inversiones"],
     "estado de cuenta|estado_cuenta|edocta|bbva|santander|banorte|banamex|citibanamex|hsbc|scotiabank|"
     "inbursa|nu mexico|afore", "estado de cuenta|saldo anterior|saldo promedio"),
    ("nominas", ["nominas", "nomina", "recibos de nomina", "sueldos", "payroll"],
     "nomina|payroll|recibo de pago de sueldo", "percepciones|deducciones"),
    ("impuestos", ["impuestos", "sat", "declaraciones", "fiscal", "contabilidad", "hacienda"],
     "declaracion|acuse|opinion de cumplimiento|constancia de situacion fiscal|csf|isr|iva",
     "servicio de administracion tributaria|acuse de recibo"),
    ("contratos", ["contratos", "legal", "escrituras", "juridico", "acuerdos"],
     "contrato|convenio|acuerdo|escritura|poder notarial|arrendamiento", None),
    ("seguros", ["seguros", "polizas", "seguro"], "poliza|seguro|aseguradora|gnp|axa|qualitas|mapfre", None),
    ("salud", ["salud", "medicos", "medico", "clinicos", "hospital", "recetas medicas"],
     "receta|laboratorio|analisis clinico|estudio|consulta|radiografia|ultrasonido|imss|issste", None),
    ("identificaciones", ["identificaciones", "personales", "documentos personales", "identidad", "ine",
                          "papeles"],
     "ine|curp|pasaporte|acta de nacimiento|licencia de conducir|cartilla|comprobante de domicilio", None),
    ("escuela", ["escuela", "estudios", "universidad", "colegio", "cursos", "certificados", "titulos",
                 "academico"],
     "certificado|diploma|boleta|kardex|titulo|cedula profesional|constancia de estudios|tarea", None),
    ("trabajo", ["trabajo", "oficina", "empresa", "proyectos", "clientes"], "propuesta|cotizacion|reporte|minuta",
     None),
    ("cv", ["cv", "curriculum", "curriculums", "empleo"], "cv|curriculum|resume|hoja de vida", None),
    ("manuales", ["manuales", "instructivos", "garantias"], "manual|instructivo|guia de usuario|garantia", None),
    ("viajes", ["viajes", "vuelos", "reservaciones"], "boarding|pase de abordar|itinerario|reservacion|vuelo|hotel",
     None),
    ("coche", ["coche", "auto", "carro", "vehiculo", "vehiculos"],
     "tenencia|verificacion|refrendo|tarjeta de circulacion|factura del auto", None),
]

# Carpetas de programas que viven en Documentos y no son para guardar documentos.
CARPETAS_DE_PROGRAMAS = {
    "my games", "mis juegos", "zoom", "windowspowershell", "powershell", "custom office templates",
    "plantillas personalizadas de office", "onenote notebooks", "blocs de notas de onenote", "fax",
    "scanned documents", "documentos escaneados", "outlook files", "archivos de outlook", "iisexpress",
    "my web sites", "sql server management studio", "visual studio", "github", "arduino", "adobe",
    "rockstar games", "ea games", "battlefield", "electronic arts", "ubisoft", "snagit", "camtasia",
    "my music", "my pictures", "my videos", "mi musica", "mis imagenes", "mis videos", "fiddler2",
    "virtual machines", "dosbox", "steam", "obs", "audacity", "sound recordings", "grabaciones de sonido",
    "my received files", "mis archivos recibidos", "gestor",
}

EXT_PROGRAMA = {".dll", ".exe", ".sav", ".ini", ".cfg", ".dat", ".bin", ".vssettings", ".ps1", ".psm1",
                ".pak", ".db", ".sqlite", ".config", ".lock"}
EXT_DOCUMENTO = set(nucleo.CATEGORIAS["Documentos"] + nucleo.CATEGORIAS["Hojas de cálculo"]
                    + nucleo.CATEGORIAS["Presentaciones"] + [".xml", ".jpg", ".jpeg", ".png"])


def _clave(nombre):
    """Nombre de carpeta comparable: sin acentos, minúsculas y sin numeración ("01 - Facturas")."""
    n = nucleo.sin_acentos(nombre.lower()).strip()
    n = re.sub(r"^[\d\s._\-)]+", "", n)
    return re.sub(r"[_\-]+", " ", n).strip()


def patron(palabras):
    """Expresión que busca palabras enteras (con plural) en el nombre: «ine» no casa con «online»."""
    partes = [r"[\s_.\-]+".join(re.escape(w) for w in p.strip().split()) for p in palabras.split("|") if p.strip()]
    return r"(?<![a-z0-9])(?:" + "|".join(partes) + r")(?:s|es)?(?![a-z])"


def subcarpetas(raiz):
    try:
        return sorted(e.name for e in os.scandir(raiz) if e.is_dir() and not e.name.startswith((".", "$")))
    except OSError:
        return []


def es_de_programa(ruta):
    """Una carpeta que parece de un programa (partidas guardadas, configuración) y no de documentos."""
    if _clave(os.path.basename(ruta)) in CARPETAS_DE_PROGRAMAS:
        return True
    docs = prog = 0
    for carpeta, dirs, archivos in os.walk(ruta):
        if carpeta.count(os.sep) - ruta.count(os.sep) >= 2:
            dirs[:] = []
        for n in archivos[:200]:
            ext = os.path.splitext(n)[1].lower()
            docs += ext in EXT_DOCUMENTO
            prog += ext in EXT_PROGRAMA
        if docs + prog > 300:
            break
    return prog > 0 and docs == 0


def buscar_subcarpeta(raiz, sinonimos):
    """La subcarpeta de raiz que corresponde a alguno de los sinónimos, o None."""
    claves = {_clave(s) for s in sinonimos}
    for nombre in subcarpetas(raiz):
        if _clave(nombre) in claves:
            return os.path.join(raiz, nombre)
    return None


def mapa_documentos(documentos=None):
    """{clave de tipo: carpeta existente en Documentos} + carpetas propias que no encajan en ningún tipo."""
    documentos = documentos or nucleo.carpeta_conocida("Documentos")
    tipos, usadas = {}, set()
    for clave, sinonimos, _, _ in TIPOS:
        ruta = buscar_subcarpeta(documentos, sinonimos)
        if ruta and ruta not in usadas:
            tipos[clave] = ruta
            usadas.add(ruta)
    otras = []
    for nombre in subcarpetas(documentos):
        ruta = os.path.join(documentos, nombre)
        if ruta in usadas or len(_clave(nombre)) < 3 or es_de_programa(ruta):
            continue
        otras.append(ruta)
    return tipos, otras


def _regla(si, destino, texto, marcada=True, accion="mover", **extra):
    r = {"id": nucleo.nuevo_id(), "si": si, "accion": accion, "destino": destino,
         "fecha": "modificacion", "nuevo_nombre": ""}
    r.update(extra)
    return {"texto": texto, "marcada": marcada, "regla": r}


def reglas_documentos(documentos, por_año=False, crear_faltantes=False, sin_uso_dias=None):
    """Reglas que mandan cada documento a su carpeta de Documentos. Lo que no encaja no se toca."""
    tipos, otras = mapa_documentos(documentos)
    extra_si = {"sin_uso_dias": sin_uso_dias} if sin_uso_dias else {}
    docs = ["Documentos", "Hojas de cálculo", "Presentaciones"]
    salida = []
    for clave, sinonimos, palabras, contenido in TIPOS:
        carpeta = tipos.get(clave)
        nueva = carpeta is None
        if nueva:
            if clave != "facturas" and not crear_faltantes:
                continue
            carpeta = os.path.join(documentos, sinonimos[0].capitalize())
        nombre_carpeta = os.path.basename(carpeta)
        aviso = " (se creará)" if nueva else ""
        if clave == "facturas":
            destino = os.path.join(carpeta, "{proveedor}", "{año}")
            salida.append(_regla(dict(extra_si, factura=True, extensiones=".pdf,.xml"), destino,
                                 f"Facturas (PDF/XML del SAT) → {nombre_carpeta}\\{{proveedor}}\\{{año}}, con nombre «2026-10 CFE $1,234.50»{aviso}",
                                 marcada=not nueva))
            continue
        destino = os.path.join(carpeta, "{año}") if por_año else carpeta
        salida.append(_regla(dict(extra_si, categorias=docs, nombre_modo="regex", nombre_valor=patron(palabras)),
                             destino, f"{nombre_carpeta}: nombre con «{palabras.split('|')[0]}»…{aviso}",
                             marcada=not nueva))
        if contenido:
            salida.append(_regla(dict(extra_si, extensiones=".pdf,.docx,.txt", contenido_modo="contiene",
                                      contenido_valor=contenido), destino,
                                 f"{nombre_carpeta}: por lo que dice el PDF{aviso}", marcada=not nueva))
    for carpeta in otras:
        nombre = os.path.basename(carpeta)
        palabra = _clave(nombre)
        destino = os.path.join(carpeta, "{año}") if por_año else carpeta
        salida.append(_regla(dict(extra_si, categorias=docs, nombre_modo="regex", nombre_valor=patron(palabra)),
                             destino, f"{nombre}: archivos con «{palabra}» en el nombre (carpeta tuya)"))
    return salida


def _servicio(nombre, origenes, reglas, **extra):
    s = {
        "id": nucleo.nuevo_id(), "nombre": nombre, "activo": True, "modo_prueba": True,
        "origenes": origenes, "subcarpetas": False,
        "horario": {"tipo": "intervalo", "cada": 8, "unidad": "horas"},
        "conflicto": "renombrar", "identicos": "papelera", "fecha_captura_fotos": True,
        "limpiar_nombres": False, "fecha_al_inicio": False, "borrar_carpetas_vacias": False,
        "mover_hermanos": True, "esperar_minutos": 10, "ignorar": [], "reglas": reglas,
    }
    s.update(extra)
    return s


def _rutas():
    return {k: nucleo.carpeta_conocida(k) for k in ("Descargas", "Documentos", "Escritorio", "Imágenes",
                                                       "Vídeos", "Música")}


def _foto_destino(r):
    return os.path.join(r["Imágenes"], "{procedencia}", "{año}", "{mes}")


def _vaciar(nombre_origen, r, dias, extra_reglas_antes=(), extra_reglas_despues=(), **extra):
    """Plantilla común de Descargas y Escritorio: lo que lleva N días sin usarse sale hacia su sitio."""
    origen = r[nombre_origen]
    espera = {"sin_uso_dias": dias}
    generica = os.path.join(r["Documentos"], f"De {nombre_origen}", "{año}", "{mes}")
    reglas = list(extra_reglas_antes)
    reglas += [
        _regla({"categorias": ["Instaladores"], "sin_uso_dias": 30}, "",
               "Instaladores (.exe, .msi) sin usar en 30 días → papelera de GESTOR (30 días para recuperarlos)",
               accion="papelera"),
        _regla({"zip_descomprimido": True, "sin_uso_dias": 3}, "",
               "ZIP ya descomprimidos (hay una carpeta con su nombre al lado) → papelera de GESTOR",
               accion="papelera"),
    ]
    reglas += reglas_documentos(r["Documentos"], sin_uso_dias=dias)
    reglas += [
        _regla(dict(espera, categorias=["Imágenes"]), _foto_destino(r),
               f"Fotos e imágenes → Imágenes\\{{procedencia}}\\{{año}}\\{{mes}} (tras {dias} días)"),
        _regla(dict(espera, categorias=["Vídeos"]), os.path.join(r["Vídeos"], "{año}"),
               f"Vídeos → Vídeos\\{{año}} (tras {dias} días)"),
        _regla(dict(espera, categorias=["Música"]), r["Música"], f"Música y audios → Música (tras {dias} días)"),
        _regla(dict(espera, categorias=["Documentos", "Hojas de cálculo", "Presentaciones"]), generica,
               f"Resto de documentos → Documentos\\De {nombre_origen}\\{{año}}\\{{mes}} (tras {dias} días)"),
        _regla(dict(espera, categorias=["Comprimidos"]), generica,
               f"ZIP y RAR sin descomprimir → Documentos\\De {nombre_origen}\\… (tras {dias} días)"),
    ]
    reglas += list(extra_reglas_despues)
    return _servicio(
        f"Vaciar {nombre_origen}", [origen], reglas, esperar_minutos=10,
        carpetas={"activo": True, "dias": dias,
                  "destino": os.path.join(r["Documentos"], f"De {nombre_origen}", "Carpetas", "{año}")},
        carpeta_mantener="Mantener", **extra)


def catalogo(dias=14):
    """Plantillas disponibles: [{clave, nombre, descripcion, servicio, reglas: [{texto, marcada, regla}]}]."""
    r = _rutas()
    escritorio_accesos = [
        _regla({"categorias": ["Accesos directos"]},
               os.path.join(r["Escritorio"], "Accesos directos", "{tipo_acceso}"),
               "Accesos directos → Escritorio\\Accesos directos\\Programas, Juegos, Sitios web… (se quedan "
               "en el Escritorio)"),
    ]
    plantillas = [
        ("vaciar_descargas", "Vaciar Descargas",
         f"Lo que lleva {dias} días sin usarse sale de Descargas: documentos a sus carpetas de Documentos, "
         "fotos a Imágenes, carpetas enteras a Documentos\\De Descargas\\Carpetas. Instaladores viejos y ZIP ya "
         "descomprimidos van a la papelera de GESTOR. Descargas\\Mantener no se toca.",
         _vaciar("Descargas", r, dias)),
        ("ordenar_descargas", "Ordenar Descargas (sin sacarlo de ahí)",
         "Clasifica lo que llega a Descargas en subcarpetas dentro de Descargas, al momento.",
         _servicio("Ordenar Descargas", [r["Descargas"]], [
             _regla({"categorias": ["Imágenes"]}, os.path.join(r["Descargas"], "Imágenes"), "Imágenes → Descargas\\Imágenes"),
             _regla({"categorias": ["Documentos", "Hojas de cálculo", "Presentaciones"]},
                    os.path.join(r["Descargas"], "Documentos", "{año}"), "Documentos → Descargas\\Documentos\\{año}"),
             _regla({"categorias": ["Instaladores"]}, os.path.join(r["Descargas"], "Instaladores"),
                    "Instaladores → Descargas\\Instaladores"),
             _regla({"categorias": ["Comprimidos"]}, os.path.join(r["Descargas"], "Comprimidos"),
                    "ZIP y RAR → Descargas\\Comprimidos"),
             _regla({"categorias": ["Vídeos"]}, os.path.join(r["Descargas"], "Vídeos"), "Vídeos → Descargas\\Vídeos"),
             _regla({"categorias": ["Música"]}, os.path.join(r["Descargas"], "Música"), "Música → Descargas\\Música"),
         ], horario={"tipo": "instante"})),
        ("documentos", "Ordenar Documentos",
         "Los archivos sueltos de Documentos van a las carpetas que ya tienes (Facturas, Contratos, Bancos…). "
         "No crea carpetas nuevas salvo que lo marques; lo que no encaja se queda donde está.",
         _servicio("Ordenar Documentos", [r["Documentos"]], reglas_documentos(r["Documentos"], crear_faltantes=True),
                   esperar_minutos=30)),
        ("vaciar_escritorio", "Vaciar Escritorio",
         f"Igual que Descargas: lo que lleva {dias} días sin usarse pasa a Documentos (carpetas incluidas). "
         "Los accesos directos se quedan en el Escritorio, ordenados en Escritorio\\Accesos directos. "
         "Escritorio\\Mantener no se toca.",
         _vaciar("Escritorio", r, dias, extra_reglas_antes=escritorio_accesos, ordenar_accesos=True)),
        ("imagenes", "Ordenar Imágenes",
         "Fotos sueltas en Imágenes por procedencia (Cámara, WhatsApp, Capturas…), año y mes, usando la fecha "
         "de captura.",
         _servicio("Ordenar Imágenes", [r["Imágenes"]], [
             _regla({"categorias": ["Imágenes", "Vídeos"]}, _foto_destino(r),
                    "Fotos y vídeos → Imágenes\\{procedencia}\\{año}\\{mes}"),
         ], esperar_minutos=30)),
        ("capturas", "Capturas de pantalla",
         "Las capturas (Imágenes\\Capturas de pantalla o Screenshots) por año y mes.",
         _servicio("Ordenar capturas", [os.path.join(r["Imágenes"], n) for n in ("Capturas de pantalla",
                                                                                          "Screenshots")
                                         if os.path.isdir(os.path.join(r["Imágenes"], n))]
                   or [os.path.join(r["Imágenes"], "Screenshots")], [
             _regla({"categorias": ["Imágenes"]}, os.path.join("{origen}", "{año}", "{mes}"),
                    "Capturas → {año}\\{mes} dentro de la misma carpeta"),
         ], horario={"tipo": "diario", "horas": ["13:00"]})),
        ("videos", "Ordenar Vídeos", "Vídeos sueltos en Vídeos por año.",
         _servicio("Ordenar Vídeos", [r["Vídeos"]], [
             _regla({"categorias": ["Vídeos"]}, os.path.join(r["Vídeos"], "{año}"), "Vídeos → Vídeos\\{año}"),
         ], esperar_minutos=60)),
        ("musica", "Ordenar Música", "Notas de voz (.opus, .m4a de WhatsApp) aparte de la música.",
         _servicio("Ordenar Música", [r["Música"]], [
             _regla({"extensiones": ".opus", "procedencias": ["WhatsApp"]},
                    os.path.join(r["Música"], "Notas de voz", "{año}"), "Notas de voz de WhatsApp → Música\\Notas de voz\\{año}"),
             _regla({"nombre_modo": "contiene", "nombre_valor": "ptt|grabacion|voice|audio-"},
                    os.path.join(r["Música"], "Notas de voz", "{año}"), "Grabaciones de voz → Música\\Notas de voz\\{año}"),
         ], esperar_minutos=60)),
        ("facturas", "Facturas en cualquier carpeta",
         "Busca facturas (PDF con su XML del SAT) en la carpeta que elijas y las lleva a Documentos\\Facturas\\"
         "{proveedor}\\{año}. El XML viaja con su PDF.",
         _servicio("Archivar facturas", [r["Descargas"]], [
             _regla({"factura": True}, os.path.join(mapa_documentos(r["Documentos"])[0].get(
                 "facturas", os.path.join(r["Documentos"], "Facturas")), "{proveedor}", "{año}"),
                 "Facturas → Facturas\\{proveedor}\\{año}"),
         ], esperar_minutos=5)),
        ("escaneados", "Documentos escaneados",
         "Lo que sale del escáner se manda a la carpeta de Documentos que le toca según su contenido.",
         _servicio("Ordenar escaneados", [buscar_subcarpeta(r["Documentos"], ["scanned documents",
                                                                              "documentos escaneados", "escaneos",
                                                                              "escaneados"])
                                          or os.path.join(r["Documentos"], "Scanned Documents")],
                   reglas_documentos(r["Documentos"]), esperar_minutos=5)),
    ]
    salida = []
    for clave, nombre, descripcion, servicio in plantillas:
        envueltas = servicio.pop("reglas")
        salida.append({"clave": clave, "nombre": nombre, "descripcion": descripcion,
                       "origenes": servicio["origenes"], "servicio": servicio, "reglas": envueltas,
                       "ya_existe": any(s.get("nombre") == servicio["nombre"] for s in nucleo.cargar_servicios())})
    return salida


def crear(clave, indices=None, origenes=None, dias=14, modo_prueba=True):
    """Crea el servicio de una plantilla con las reglas marcadas. Arranca activo y en modo prueba."""
    p = next((p for p in catalogo(dias) if p["clave"] == clave), None)
    if not p:
        raise ValueError("No existe esa plantilla.")
    servicio = p["servicio"]
    elegidas = [e["regla"] for i, e in enumerate(p["reglas"])
                if (i in indices if indices is not None else e["marcada"])]
    if not elegidas:
        raise ValueError("Marca al menos una regla.")
    servicio["reglas"] = elegidas
    if origenes:
        for o in origenes:
            ok, aviso = nucleo.revisar_carpeta(o)
            if not ok:
                raise ValueError(f"{o}: {aviso}")
        servicio["origenes"] = origenes
    servicio["modo_prueba"] = bool(modo_prueba)
    servicios = nucleo.cargar_servicios()
    servicios.append(servicio)
    nucleo.guardar_servicios(servicios)
    return servicio
