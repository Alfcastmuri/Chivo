import datetime as dt
import json
import os
import struct
import sys
import tempfile
import time
import unittest

DATOS = tempfile.mkdtemp()
os.environ["GESTOR_DATOS"] = DATOS
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import nucleo  # noqa: E402


def jpeg_con_exif(fecha, marca=None, modelo=None):
    """JPEG mínimo con DateTimeOriginal y, opcionalmente, marca y modelo de cámara."""
    textos = [(0x010F, marca), (0x0110, modelo)]
    textos = [(e, v.encode() + b"\x00") for e, v in textos if v]
    n0 = 1 + len(textos)
    exif_ifd = 8 + 2 + n0 * 12 + 4
    datos = exif_ifd + 2 + 12 + 4
    fecha_b = fecha.encode() + b"\x00"
    ifd0 = struct.pack(">H", n0)
    extra = b""
    p = datos + len(fecha_b)
    for etiqueta, valor in textos:
        ifd0 += struct.pack(">HHII", etiqueta, 2, len(valor), p + len(extra))
        extra += valor
    ifd0 += struct.pack(">HHII", 0x8769, 4, 1, exif_ifd) + b"\x00" * 4
    exif = struct.pack(">H", 1) + struct.pack(">HHII", 0x9003, 2, len(fecha_b), datos) + b"\x00" * 4
    tiff = b"MM\x00\x2a\x00\x00\x00\x08" + ifd0 + exif + fecha_b + extra
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


class PruebaServicio(unittest.TestCase):
    def setUp(self):
        self.raiz = tempfile.mkdtemp()
        self.origen = os.path.join(self.raiz, "Descargas")
        self.destino = os.path.join(self.raiz, "Ordenado")
        os.makedirs(self.origen)
        self.hace_una_hora = time.time() - 3600

    def crear(self, nombre, contenido=b"x", viejo=True):
        ruta = os.path.join(self.origen, nombre)
        with open(ruta, "wb") as f:
            f.write(contenido)
        if viejo:
            os.utime(ruta, (self.hace_una_hora, self.hace_una_hora))
        return ruta

    def servicio(self, reglas, **extra):
        s = {"id": nucleo.nuevo_id(), "nombre": "prueba", "activo": True, "origenes": [self.origen],
             "subcarpetas": False, "horario": {"tipo": "manual"}, "conflicto": "renombrar",
             "esperar_minutos": 10, "ignorar": [], "reglas": reglas}
        s.update(extra)
        return s

    def test_ordena_respeta_ignorados_y_deshace(self):
        self.crear("foto.jpg", jpeg_con_exif("2019:05:20 10:00:00"))
        self.crear("Factura enero.pdf")
        self.crear("notas.txt")
        self.crear("descarga.crdownload")
        self.crear("acceso.lnk")
        self.crear("recien.pdf", viejo=False)
        os.makedirs(os.path.join(self.destino, "Documentos"))
        open(os.path.join(self.destino, "Documentos", "notas.txt"), "w").close()

        s = self.servicio([
            {"si": {"categorias": ["Imágenes"]}, "accion": "mover",
             "destino": os.path.join(self.destino, "Fotos", "{año}", "{mes}"), "fecha": "captura"},
            {"si": {"nombre_valor": "factura", "extensiones": [".pdf"]}, "accion": "mover",
             "destino": os.path.join(self.destino, "Facturas"), "nuevo_nombre": "{año}_{nombre}"},
            {"si": {}, "accion": "mover", "destino": os.path.join(self.destino, "{categoria}")},
        ])
        registro = nucleo.ejecutar_servicio(s)
        self.assertEqual(registro["errores"], [])
        self.assertTrue(os.path.exists(os.path.join(self.destino, "Fotos", "2019", "05-Mayo", "foto.jpg")))
        anio = str(dt.datetime.fromtimestamp(self.hace_una_hora).year)
        self.assertTrue(os.path.exists(os.path.join(self.destino, "Facturas", f"{anio}_Factura enero.pdf")))
        self.assertTrue(os.path.exists(os.path.join(self.destino, "Documentos", "notas (1).txt")))
        self.assertEqual(sorted(os.listdir(self.origen)), ["acceso.lnk", "descarga.crdownload", "recien.pdf"])

        resultado = nucleo.deshacer(s["id"])
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["devueltos"], 3)
        self.assertIn("foto.jpg", os.listdir(self.origen))

    def test_simular_no_toca_nada(self):
        self.crear("a.pdf")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}])
        resultado = nucleo.ejecutar_servicio(s, simular=True)
        self.assertEqual(len(resultado["operaciones"]), 1)
        self.assertEqual(os.listdir(self.origen), ["a.pdf"])

    def test_no_reordena_destinos_dentro_del_origen(self):
        self.crear("a.pdf")
        os.makedirs(os.path.join(self.origen, "Documentos"))
        ya = os.path.join(self.origen, "Documentos", "b.pdf")
        open(ya, "w").close()
        os.utime(ya, (self.hace_una_hora, self.hace_una_hora))
        s = self.servicio([{"si": {}, "accion": "mover",
                            "destino": os.path.join("{origen}", "{categoria}")}], subcarpetas=True)
        plan, _ = nucleo.planificar(s)
        self.assertEqual([os.path.basename(o["origen"]) for o in plan], ["a.pdf"])


class PruebaIdenticos(PruebaServicio):
    def test_identico_va_a_papelera_y_distinto_se_renombra(self):
        os.makedirs(self.destino)
        for nombre, contenido in (("igual.pdf", b"mismo"), ("distinto.pdf", b"viejo"), ("otro.pdf", b"aa")):
            with open(os.path.join(self.destino, nombre), "wb") as f:
                f.write(contenido)
        with open(os.path.join(self.destino, "otro (1).pdf"), "wb") as f:
            f.write(b"bb")
        self.crear("igual.pdf", b"mismo")
        self.crear("distinto.pdf", b"nuevo")
        self.crear("otro.pdf", b"bb")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}])
        plan = {os.path.basename(o["origen"]): o for o in nucleo.planificar(s)[0]}
        self.assertEqual(plan["igual.pdf"]["accion"], "papelera")
        self.assertEqual(plan["otro.pdf"]["identico_a"], os.path.join(self.destino, "otro (1).pdf"))
        self.assertEqual(plan["distinto.pdf"]["destino"], os.path.join(self.destino, "distinto (1).pdf"))

        s["identicos"] = "conflicto"
        plan = {os.path.basename(o["origen"]): o for o in nucleo.planificar(s)[0]}
        self.assertEqual(plan["igual.pdf"]["destino"], os.path.join(self.destino, "igual (1).pdf"))


class PruebaProcedencia(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.mkdtemp()

    def proc(self, nombre, contenido=b"x", subcarpeta=""):
        carpeta = os.path.join(self.carpeta, subcarpeta)
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, nombre)
        with open(ruta, "wb") as f:
            f.write(contenido)
        return nucleo.procedencia_de(ruta)

    def test_por_nombre(self):
        casos = {
            "IMG-20231005-WA0012.jpg": "WhatsApp",
            "VID-20231005-WA0003.mp4": "WhatsApp",
            "WhatsApp Image 2023-10-05 at 10.12.33.jpeg": "WhatsApp",
            "Imagen de WhatsApp 2023-10-05 a las 10.12.33_1a2b.jpg": "WhatsApp",
            "photo_2023-10-05_10-12-33.jpg": "Telegram",
            "Screenshot_20231005-101233.png": "Captura de pantalla",
            "Captura de pantalla 2023-10-05 101233.png": "Captura de pantalla",
            "Scan_0001.pdf": "Escáner",
            "IMG_20231005_101233.jpg": "Cámara",
            "PXL_20231005_101233123.mp4": "Cámara",
            "DSC_1234.JPG": "Cámara",
            "factura.pdf": "Desconocida",
        }
        for nombre, esperado in casos.items():
            self.assertEqual(self.proc(nombre)["procedencia"], esperado, nombre)

    def test_por_exif_y_carpeta(self):
        r = self.proc("foto.jpg", jpeg_con_exif("2020:01:02 03:04:05", "Canon", "Canon EOS 80D"))
        self.assertEqual(r["procedencia"], "Cámara")
        self.assertEqual(r["camara"], "Canon EOS 80D")
        r = self.proc("x.jpg", jpeg_con_exif("2020:01:02 03:04:05", "samsung", "SM-G991B"))
        self.assertEqual(r["camara"], "samsung SM-G991B")
        self.assertEqual(self.proc("sin_nombre.jpg", subcarpeta="WhatsApp Images")["procedencia"], "WhatsApp")

    def test_fecha_en_el_nombre(self):
        self.assertEqual(nucleo.fecha_en_nombre("IMG-20231005-WA0012.jpg"), dt.datetime(2023, 10, 5))
        self.assertEqual(nucleo.fecha_en_nombre("Screenshot_2023-10-05-10-12.png"), dt.datetime(2023, 10, 5))
        self.assertIsNone(nucleo.fecha_en_nombre("IMG_1234.jpg"))
        self.assertIsNone(nucleo.fecha_en_nombre("pedido 20231399.pdf"))

    def test_variable_y_condicion(self):
        ruta = os.path.join(self.carpeta, "IMG-20231005-WA0012.jpg")
        open(ruta, "wb").close()
        fecha = dt.datetime(2023, 10, 5)
        self.assertTrue(nucleo.expandir("{procedencia}/{año}", ruta, self.carpeta, fecha)
                        .startswith("WhatsApp"))
        st = os.stat(ruta)
        self.assertTrue(nucleo.cumple({"procedencias": ["WhatsApp"]}, ruta, st, time.time()))
        self.assertFalse(nucleo.cumple({"procedencias": ["Cámara"]}, ruta, st, time.time()))


class PruebaFunciones(PruebaServicio):
    def test_limpiar_nombre(self):
        self.assertEqual(nucleo.limpiar_nombre("Factura (1)"), "Factura")
        self.assertEqual(nucleo.limpiar_nombre("Copia de informe - copia (2)"), "informe")
        self.assertEqual(nucleo.limpiar_nombre("foto   💥 playa!!"), "foto playa")
        fecha = dt.datetime(2024, 3, 9)
        self.assertEqual(nucleo.limpiar_nombre("notas", fecha), "2024-03-09 notas")
        self.assertEqual(nucleo.limpiar_nombre("20240309_notas", fecha), "2024-03-09 notas")
        self.assertEqual(nucleo.limpiar_nombre("09-03-2024 notas", fecha), "2024-03-09 notas")

    def test_duplicado_tras_limpiar_va_a_carpeta(self):
        os.makedirs(self.destino)
        with open(os.path.join(self.destino, "informe.pdf"), "wb") as f:
            f.write(b"igual")
        self.crear("informe (1).pdf", b"igual")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}],
                          limpiar_nombres=True, identicos="carpeta")
        r = nucleo.ejecutar_y_anotar(s)
        op = r["operaciones"][0]
        self.assertTrue(op["duplicado"] and op["tras_limpiar"])
        self.assertTrue(os.path.exists(os.path.join(self.origen, "Duplicados", "informe (1).pdf")))
        avisos, _ = nucleo.leer_avisos_desde(0)
        self.assertTrue(any(a["titulo"] == "Duplicados detectados" for a in avisos))

    def test_papelera_propia_restaurar_y_deshacer(self):
        self.crear("viejo.exe")
        s = self.servicio([{"si": {}, "accion": "papelera"}])
        r = nucleo.ejecutar_y_anotar(s)
        self.assertEqual(os.listdir(self.origen), [])
        pid = r["operaciones"][0]["papelera_id"]
        self.assertTrue(any(e["id"] == pid for e in nucleo.listar_papelera()))
        self.assertTrue(nucleo.deshacer(s["id"])["ok"])
        self.assertEqual(os.listdir(self.origen), ["viejo.exe"])
        self.assertFalse(any(e["id"] == pid for e in nucleo.listar_papelera()))

    def test_purgar_papelera(self):
        ruta = self.crear("tirar.txt")
        pid = nucleo.quitar(ruta)
        self.assertEqual(nucleo.purgar_papelera()["borrados"], 0)  # aún no caduca
        self.assertEqual(nucleo.purgar_papelera(ids=[pid])["borrados"], 1)

    def test_archivar_en_zip_mensual(self):
        import zipfile
        ruta = self.crear("antiguo.txt", b"contenido")
        hace = time.time() - 200 * 86400
        os.utime(ruta, (hace, hace))
        s = self.servicio([{"si": {"antiguedad_mayor_dias": 180}, "accion": "archivar", "destino": ""}])
        r = nucleo.ejecutar_y_anotar(s)
        zip_ruta = r["operaciones"][0]["destino"]
        self.assertTrue(os.path.basename(zip_ruta).startswith("Archivo "))
        with zipfile.ZipFile(zip_ruta) as z:
            self.assertEqual(z.read("antiguo.txt"), b"contenido")
        self.assertEqual(os.listdir(self.origen), ["Archivados"])
        nucleo.deshacer(s["id"])
        self.assertIn("antiguo.txt", os.listdir(self.origen))

    def test_borrar_carpetas_vacias(self):
        sub = os.path.join(self.origen, "a", "b")
        os.makedirs(sub)
        ruta = os.path.join(sub, "x.pdf")
        open(ruta, "w").close()
        os.utime(ruta, (self.hace_una_hora, self.hace_una_hora))
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}],
                          subcarpetas=True, borrar_carpetas_vacias=True)
        r = nucleo.ejecutar_servicio(s)
        self.assertEqual(len(r["carpetas_borradas"]), 2)
        self.assertEqual(os.listdir(self.origen), [])

    def test_renombrar_no_se_repite(self):
        self.crear("nota.txt")
        s = self.servicio([{"si": {}, "accion": "renombrar", "nuevo_nombre": "x_{nombre}"}])
        nucleo.ejecutar_y_anotar(s)
        nucleo.ejecutar_y_anotar(s)
        self.assertEqual(os.listdir(self.origen), ["x_nota.txt"])

    def test_contenido_docx_y_txt(self):
        import zipfile
        docx = os.path.join(self.origen, "f.docx")
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", "<w:p><w:t>FACTURA</w:t></w:p><w:p><w:t>RFC ABC010101XY9</w:t></w:p>")
        txt = self.crear("t.txt", "estado de cuenta".encode())
        st = os.stat(docx)
        self.assertTrue(nucleo.cumple({"contenido_valor": "factura, rfc"}, docx, st, time.time()))
        self.assertTrue(nucleo.cumple({"contenido_valor": r"[A-Z]{3}\d{6}", "contenido_modo": "regex"},
                                      docx, st, time.time()))
        self.assertFalse(nucleo.cumple({"contenido_valor": "factura"}, txt, os.stat(txt), time.time()))

    def test_fecha_captura_desactivada(self):
        ruta = self.crear("foto.jpg", jpeg_con_exif("2019:05:20 10:00:00"))
        regla = {"si": {}, "accion": "mover", "destino": os.path.join(self.destino, "{año}")}
        con = self.servicio([regla])
        sin = self.servicio([regla], fecha_captura_fotos=False)
        self.assertIn(os.sep + "2019" + os.sep, nucleo.planificar(con)[0][0]["destino"])
        self.assertNotIn(os.sep + "2019" + os.sep, nucleo.planificar(sin)[0][0]["destino"])

    def test_buscar_duplicados(self):
        for nombre in ("a.bin", "b.bin", "c.bin"):
            with open(os.path.join(self.origen, nombre), "wb") as f:
                f.write(b"x" * 4096 if nombre != "c.bin" else b"y" * 4096)
        grupos = nucleo.buscar_duplicados([self.origen], min_bytes=1)
        self.assertEqual(len(grupos), 1)
        self.assertEqual(sorted(os.path.basename(r) for r in grupos[0]["archivos"]), ["a.bin", "b.bin"])

    def test_asistente(self):
        self.crear("IMG-20231005-WA0012.jpg")
        self.crear("Screenshot_20231005-101233.png")
        self.crear("setup (1).exe")
        analisis = nucleo.analizar_carpeta(self.origen)
        claves = [s["clave"] for s in analisis["sugerencias"]]
        self.assertEqual(claves, ["whatsapp", "capturas", "instaladores"])
        self.assertEqual(analisis["copias"], 1)
        servicio = nucleo.crear_desde_asistente(self.origen, [s["regla"] for s in analisis["sugerencias"]], True)
        self.assertTrue(servicio["activo"] and servicio["modo_prueba"])
        self.assertEqual(len(nucleo.planificar(servicio)[0]), 3)

    def test_copia_incremental(self):
        self.crear("a.txt", b"1")
        n, _, _ = nucleo.copiar_incremental(self.origen, self.destino)
        self.assertEqual(n, 1)
        n, _, _ = nucleo.copiar_incremental(self.origen, self.destino)
        self.assertEqual(n, 0)

    def test_estadisticas(self):
        self.crear("a.pdf", b"12345")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}])
        nucleo.ejecutar_y_anotar(s)
        t = nucleo.cargar_estado()[s["id"]]["totales"]
        self.assertEqual((t["archivos"], t["bytes_ordenados"], t["por_categoria"]["Documentos"]), (1, 5, 1))


@unittest.skipUnless(__import__("importlib").util.find_spec("watchdog"), "watchdog no instalado")
class PruebaVaciarYPlantillas(PruebaServicio):
    def viejo(self, ruta, dias):
        t = time.time() - dias * 86400
        os.utime(ruta, (t, t))

    def test_hermanos_se_mueven_juntos(self):
        self.crear("factura A1.pdf")
        self.crear("factura A1.xml")
        self.crear("otra.xml")
        regla = {"id": "r", "si": {"categorias": ["Documentos"]}, "accion": "mover", "destino": self.destino}
        plan, _ = nucleo.planificar(self.servicio([regla]))
        self.assertEqual(sorted(os.path.basename(o["destino"]) for o in plan), ["factura A1.pdf", "factura A1.xml"])
        plan, _ = nucleo.planificar(self.servicio([regla], mover_hermanos=False))
        self.assertEqual([os.path.basename(o["destino"]) for o in plan], ["factura A1.pdf"])
        # El hermano toma el nombre nuevo del principal si hay conflicto.
        os.makedirs(self.destino)
        open(os.path.join(self.destino, "factura A1.pdf"), "w").close()
        plan, _ = nucleo.planificar(self.servicio([regla], identicos="conflicto"))
        self.assertEqual(sorted(os.path.basename(o["destino"]) for o in plan),
                         ["factura A1 (1).pdf", "factura A1 (1).xml"])

    def test_carpetas_viejas_y_mantener(self):
        for nombre, dias in (("proyecto", 20), ("nueva", 1), ("Mantener", 40)):
            os.makedirs(os.path.join(self.origen, nombre))
            ruta = os.path.join(self.origen, nombre, "a.txt")
            open(ruta, "w").close()
            self.viejo(ruta, dias)
            self.viejo(os.path.join(self.origen, nombre), dias)
        s = self.servicio([], carpetas={"activo": True, "dias": 14, "destino": os.path.join(self.destino, "{año}")})
        # En Windows la llegada es la fecha de creación, que una prueba no puede cambiar.
        original, nucleo.llegada = nucleo.llegada, lambda st: st.st_mtime
        self.addCleanup(setattr, nucleo, "llegada", original)
        plan, _ = nucleo.planificar(s, ahora=time.time())
        self.assertEqual([os.path.basename(o["origen"]) for o in plan], ["proyecto"])
        nucleo.ejecutar_servicio(s)
        self.assertTrue(os.path.isfile(os.path.join(plan[0]["destino"], "a.txt")))
        self.assertTrue(nucleo.deshacer(s["id"])["ok"])
        self.assertTrue(os.path.isfile(os.path.join(self.origen, "proyecto", "a.txt")))

    def test_sin_uso_y_zip_descomprimido(self):
        z = self.crear("fotos.zip")
        os.makedirs(os.path.join(self.origen, "fotos"))
        open(os.path.join(self.origen, "fotos", "1.jpg"), "w").close()
        self.crear("suelto.zip")
        self.assertTrue(nucleo.zip_descomprimido(z))
        self.assertFalse(nucleo.zip_descomprimido(os.path.join(self.origen, "suelto.zip")))
        viejo = self.crear("viejo.pdf")
        self.viejo(viejo, 20)
        st = os.stat(viejo)
        if not nucleo.ES_WINDOWS:
            self.assertTrue(nucleo.cumple({"sin_uso_dias": 14}, viejo, st, time.time()))
        self.assertFalse(nucleo.cumple({"sin_uso_dias": 14}, z, os.stat(z), time.time()))

    def test_modo_prueba_aprobar_y_buscar(self):
        self.crear("contrato renta.pdf")
        regla = {"id": "r", "si": {"categorias": ["Documentos"]}, "accion": "mover", "destino": self.destino}
        s = self.servicio([regla], modo_prueba=True)
        nucleo.guardar_servicios([s])
        r = nucleo.ejecutar_y_anotar(s, motivo="horario")
        self.assertTrue(r["prueba"])
        self.assertTrue(os.path.exists(os.path.join(self.origen, "contrato renta.pdf")))
        self.assertEqual(nucleo.cargar_estado()[s["id"]]["propuestas"]["n"], 1)
        r = nucleo.aprobar_prueba(s["id"])
        self.assertEqual(len(r["operaciones"]), 1)
        self.assertFalse(nucleo.cargar_servicios()[0]["modo_prueba"])
        encontrados = nucleo.buscar_movidos("CONTRATO")["resultados"]
        self.assertEqual(encontrados[0]["destino"], os.path.join(self.destino, "contrato renta.pdf"))
        self.assertTrue(encontrados[0]["existe"])
        self.assertEqual(nucleo.buscar_movidos("nada parecido")["total"], 0)

    def test_accesos_directos(self):
        juego = self.crear("Juego.url", b"[InternetShortcut]\r\nURL=steam://rungameid/123\r\n")
        web = self.crear("Banco.url", b"[InternetShortcut]\r\nURL=https://banco.example\r\n")
        self.assertEqual(nucleo.tipo_acceso(juego), "Juegos")
        self.assertEqual(nucleo.tipo_acceso(web), "Sitios web")
        regla = {"id": "r", "si": {"categorias": ["Accesos directos"]}, "accion": "mover",
                 "destino": os.path.join(self.origen, "Accesos directos", "{tipo_acceso}")}
        self.assertEqual(nucleo.planificar(self.servicio([regla]))[0], [])  # ignorados por defecto
        plan, _ = nucleo.planificar(self.servicio([regla], ordenar_accesos=True))
        self.assertEqual(sorted(os.path.basename(os.path.dirname(o["destino"])) for o in plan),
                         ["Juegos", "Sitios web"])

    def test_leer_no_cuenta_como_usar(self):
        ruta = self.crear("notas.txt", b"hola")
        self.viejo(ruta, 20)
        antes = os.stat(ruta).st_atime
        nucleo.texto_de(ruta)
        nucleo._huella(ruta)
        self.assertAlmostEqual(os.stat(ruta).st_atime, antes, delta=1)

    def test_no_molestar_horas(self):
        self.assertTrue(nucleo._en_horas("22:00", "07:00", dt.datetime(2024, 1, 1, 23, 30)))
        self.assertTrue(nucleo._en_horas("22:00", "07:00", dt.datetime(2024, 1, 1, 6, 59)))
        self.assertFalse(nucleo._en_horas("22:00", "07:00", dt.datetime(2024, 1, 1, 12, 0)))
        self.assertTrue(nucleo._en_horas("09:00", "17:00", dt.datetime(2024, 1, 1, 12, 0)))

    def test_plantilla_documentos_usa_carpetas_existentes(self):
        import plantillas
        docs = os.path.join(self.raiz, "Documentos")
        for d in ("01 - Facturas", "Contratos", "Mi Coche", "Viajes 2024", "My Games"):
            os.makedirs(os.path.join(docs, d))
        open(os.path.join(docs, "My Games", "partida.sav"), "w").close()
        tipos, otras = plantillas.mapa_documentos(docs)
        self.assertEqual(os.path.basename(tipos["facturas"]), "01 - Facturas")
        self.assertEqual(os.path.basename(tipos["contratos"]), "Contratos")
        self.assertEqual(sorted(os.path.basename(o) for o in otras), ["Mi Coche", "Viajes 2024"])
        reglas = plantillas.reglas_documentos(docs)
        destinos = {e["regla"]["destino"] for e in reglas if e["marcada"]}
        self.assertIn(os.path.join(docs, "01 - Facturas", "{proveedor}", "{año}"), destinos)
        self.assertFalse(any("Games" in d for d in destinos))
        # Solo crea dentro de Documentos, y desmarcado.
        nuevas = [e for e in plantillas.reglas_documentos(docs, crear_faltantes=True) if not e["marcada"]]
        self.assertTrue(nuevas and all(e["regla"]["destino"].startswith(docs) for e in nuevas))
        # Palabras enteras: «ine» no casa con «online».
        contrato = {"nombre_modo": "regex", "nombre_valor": plantillas.patron("ine|contrato")}
        st = os.stat(self.crear("online.pdf"))
        self.assertFalse(nucleo.cumple(contrato, os.path.join(self.origen, "online.pdf"), st, time.time()))
        st = os.stat(self.crear("Contratos_casa.pdf"))
        self.assertTrue(nucleo.cumple(contrato, os.path.join(self.origen, "Contratos_casa.pdf"), st, time.time()))

    def test_resumen_semanal(self):
        nucleo.borrar_json(nucleo.ARCHIVO_SISTEMA)
        ahora = time.time()
        self.assertFalse(nucleo.aviso_semanal(ahora - 8 * 86400))  # la primera vez solo empieza a contar
        nucleo.indexar({"nombre": "S"}, [{"accion": "mover", "origen": "/a/x.pdf", "destino": "/b/x.pdf"}])
        self.assertGreaterEqual(nucleo.resumen_semana(ahora + 1)["por_servicio"].get("S", 0), 1)
        self.assertTrue(nucleo.aviso_semanal(ahora + 1))
        self.assertFalse(nucleo.aviso_semanal(ahora + 2))  # una vez por semana


class PruebaCincoMas(PruebaServicio):
    def viejo(self, ruta, dias):
        t = time.time() - dias * 86400
        os.utime(ruta, (t, t))

    def test_factura_con_nombre_util(self):
        self.assertEqual(nucleo.proveedor_corto("COMISION FEDERAL DE ELECTRICIDAD"), "CFE")
        self.assertEqual(nucleo.proveedor_corto("Servicios Integrales del Norte, S.A. de C.V."), "Servicios Integrales")
        self.crear("abc123.pdf", b"%PDF-1.4")
        self.crear("abc123.xml", b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
                                 b'Fecha="2026-10-03T10:00:00" Total="1234.5" Serie="A" Folio="77">'
                                 b'<cfdi:Emisor Rfc="CFE370814QI0" Nombre="COMISION FEDERAL DE ELECTRICIDAD"/>'
                                 b'</cfdi:Comprobante>')
        regla = {"id": "r", "si": {"factura": True}, "accion": "mover", "destino": self.destino}
        plan, _ = nucleo.planificar(self.servicio([regla]))
        self.assertEqual(sorted(os.path.basename(o["destino"]) for o in plan),
                         ["2026-10 CFE $1,234.50 A77.pdf", "2026-10 CFE $1,234.50 A77.xml"])

    def test_vencimientos(self):
        import vencimientos
        f, _ = vencimientos.fecha_vencimiento("Póliza 123. Vigencia: desde 01/03/2025 hasta el 01/03/2027")
        self.assertEqual(f, dt.date(2027, 3, 1))
        self.assertEqual(vencimientos.fecha_vencimiento("VIGENCIA 2020 - 2030")[0], dt.date(2030, 12, 31))
        self.assertEqual(vencimientos.fecha_vencimiento("Fecha de vencimiento 15 de marzo de 2027")[0], dt.date(2027, 3, 15))
        carpeta = os.path.join(self.raiz, "Docs")
        os.makedirs(carpeta)
        with open(os.path.join(carpeta, "poliza auto.txt"), "w", encoding="utf-8") as fh:
            fh.write("Seguro de auto. Fin de vigencia: 2026-12-01")
        with open(os.path.join(carpeta, "notas.txt"), "w", encoding="utf-8") as fh:
            fh.write("La licencia del programa es libre.")
        ajustes = nucleo.cargar_ajustes()
        ajustes["carpetas_vencimientos"] = [carpeta]
        nucleo.guardar_ajustes(ajustes)
        self.assertTrue(vencimientos.escanear(segundos=30))
        filas = [v for v in vencimientos.lista(dt.date(2026, 11, 1))["vencimientos"] if v["ruta"].startswith(carpeta)]
        self.assertEqual([(v["nombre"], v["fecha"], v["dias"]) for v in filas], [("poliza auto.txt", "2026-12-01", 30)])
        vencimientos.agregar("Pasaporte", "2026-11-05", "Pasaporte")
        self.assertEqual(vencimientos.lista(dt.date(2026, 11, 1))["vencimientos"][0]["nombre"], "Pasaporte")

    def test_aprender_de_ti(self):
        import aprendizaje
        docs = os.path.join(self.raiz, "Documentos")
        casa = os.path.join(docs, "Casa")
        os.makedirs(os.path.join(casa, "2026"))
        original = nucleo.carpeta_conocida
        nucleo.carpeta_conocida = lambda n: docs if n == "Documentos" else os.path.join(self.raiz, n)
        self.addCleanup(setattr, nucleo, "carpeta_conocida", original)
        for nombre in ("Predial 2025.pdf", "recibo predial marzo.pdf"):
            ruta = os.path.join(casa, "2026", nombre)
            open(ruta, "w").close()
            self.assertTrue(aprendizaje.observar(ruta, os.path.join(self.origen, nombre)))
        self.assertFalse(aprendizaje.observar(os.path.join(docs, "suelto.pdf")))  # la raíz no enseña nada
        nuevas = aprendizaje.pensar()
        self.assertEqual([(p["palabra"], p["carpeta"]) for p in nuevas], [("predial", casa)])
        servicio = aprendizaje.aceptar(nuevas[0]["id"], origenes=[self.origen])
        self.assertTrue(servicio["modo_prueba"])
        self.crear("PREDIAL abril.pdf")
        plan, _ = nucleo.planificar(servicio)
        self.assertEqual(plan[0]["destino"], os.path.join(casa, "PREDIAL abril.pdf"))
        self.assertEqual(aprendizaje.pensar(), [])  # no vuelve a proponer lo mismo

    def test_respaldo_con_versiones(self):
        import respaldo
        origen = os.path.join(self.raiz, "Mis docs")
        destino = os.path.join(self.raiz, "Respaldo")
        os.makedirs(os.path.join(origen, "sub"))
        with open(os.path.join(origen, "sub", "a.txt"), "w") as f:
            f.write("uno")
        with open(os.path.join(origen, "b.txt"), "w") as f:
            f.write("b")
        self.assertEqual(respaldo.respaldar(origen, destino)["copiados"], 2)
        self.assertEqual(respaldo.respaldar(origen, destino)["copiados"], 0)
        with open(os.path.join(origen, "sub", "a.txt"), "w") as f:
            f.write("dos, más largo")
        os.remove(os.path.join(origen, "b.txt"))
        r = respaldo.respaldar(origen, destino)
        self.assertEqual((r["copiados"], r["versionados"], r["borrados"]), (1, 1, 1))
        with open(os.path.join(destino, "Actual", "sub", "a.txt")) as f:
            self.assertEqual(f.read(), "dos, más largo")
        versiones = respaldo.buscar_versiones(destino, "a.txt")
        self.assertEqual(len(versiones), 1)
        restaurado = respaldo.restaurar_version({"origen": origen, "destino": destino}, versiones[0]["ruta"])
        with open(restaurado) as f:
            self.assertEqual(f.read(), "uno")
        self.assertTrue(respaldo.validar(origen, os.path.join(origen, "x")))

    def test_sacar_todo_a_la_raiz(self):
        for rel, contenido in (("viaje/a.jpg", b"1"), ("viaje/dia 2/b.jpg", b"2"), ("otra/a.jpg", b"3"),
                               ("copia/b.jpg", b"2"), ("Mantener/c.txt", b"4"), ("raiz.txt", b"5")):
            ruta = os.path.join(self.origen, *rel.split("/"))
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "wb") as f:
                f.write(contenido)
        r = nucleo.aplanar(self.origen, simular=True)
        self.assertEqual(len(r["operaciones"]), 4, [(o["origen"], o.get("destino"), o.get("accion")) for o in r["operaciones"]]
                         + r.get("errores", []) + r.get("avisos", []))
        r = nucleo.aplanar(self.origen, simular=False)
        self.assertEqual(len(r["errores"]), 0)
        self.assertEqual(sorted(n for n in os.listdir(self.origen) if os.path.isfile(os.path.join(self.origen, n))),
                         ["a (1).jpg", "a.jpg", "b.jpg", "raiz.txt"])  # b.jpg repetido e idéntico: a la papelera
        self.assertEqual(sorted(d for d in os.listdir(self.origen) if os.path.isdir(os.path.join(self.origen, d))),
                         ["Mantener"])
        self.assertTrue(nucleo.deshacer(nucleo.ID_APLANAR)["ok"])
        self.assertTrue(os.path.isfile(os.path.join(self.origen, "viaje", "dia 2", "b.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(self.origen, "copia", "b.jpg")))
        r = nucleo.aplanar(self.origen, simular=True, nombre_con_carpeta=True)
        self.assertIn("viaje - a.jpg", [os.path.basename(o["destino"]) for o in r["operaciones"]])
        self.assertFalse(nucleo.aplanar(os.path.expanduser("~"))["ok"])

    def test_carpetas_que_se_repiten(self):
        a, b = os.path.join(self.raiz, "Fotos"), os.path.join(self.raiz, "Respaldo", "Fotos")
        for c in (a, b):
            os.makedirs(c)
            for i in range(4):
                with open(os.path.join(c, f"f{i}.jpg"), "wb") as f:
                    f.write(bytes([i]) * 2000)
        with open(os.path.join(a, "solo.jpg"), "wb") as f:
            f.write(b"z" * 2000)
        por_carpeta = {}
        grupos = nucleo.buscar_duplicados([self.raiz], min_bytes=1, por_carpeta=por_carpeta)
        pares = nucleo.carpetas_que_se_repiten(grupos, por_carpeta)
        self.assertEqual([(p["a"], p["b"], p["archivos"], p["pct_a"], p["pct_b"]) for p in pares], [(a, b, 4, 80, 100)])

    def test_relevo_fuera_del_exe_no_hace_nada(self):
        self.assertEqual(nucleo.otras_versiones(), [])
        self.assertEqual(nucleo.tomar_el_relevo()["cerrados"], 0)
        nucleo.pedir_cierre([os.getpid()])
        self.assertTrue(nucleo.debo_cerrarme())
        nucleo.pedir_cierre([])
        self.assertFalse(nucleo.debo_cerrarme())


class PruebaAlInstante(PruebaServicio):
    def test_ordena_al_aparecer_un_archivo(self):
        import residente
        residente.QUIETUD_SEGUNDOS, residente.ESPERA_ARCHIVO = 1, 0
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}],
                          horario={"tipo": "instante"})
        nucleo.guardar_servicios([s])
        v = residente.Vigilante()
        v.recargar()
        try:
            v.atender()  # primera pasada: carpeta vacía
            time.sleep(0.5)
            with open(os.path.join(self.origen, "nuevo.pdf"), "w") as f:
                f.write("x")
            limite = time.time() + 10
            while time.time() < limite and not os.path.exists(os.path.join(self.destino, "nuevo.pdf")):
                v.atender()
                time.sleep(0.3)
            self.assertTrue(os.path.exists(os.path.join(self.destino, "nuevo.pdf")))
        finally:
            v.detener()


class PruebaHorarios(unittest.TestCase):
    ahora = dt.datetime(2026, 10, 29, 10, 0)  # jueves

    def test_diario(self):
        s = {"activo": True, "horario": {"tipo": "diario", "horas": ["09:00", "22:00"]}}
        self.assertTrue(nucleo.toca_ejecutar(s, {"visto": "2026-10-29T08:00:00"}, self.ahora))
        self.assertFalse(nucleo.toca_ejecutar(s, {"ultima": "2026-10-29T09:30:00"}, self.ahora))
        self.assertEqual(nucleo.proxima_ejecucion(s, {"ultima": "2026-10-29T09:30:00"}, self.ahora),
                         "2026-10-29T22:00")

    def test_intervalo(self):
        s = {"activo": True, "horario": {"tipo": "intervalo", "cada": 8, "unidad": "horas"}}
        self.assertFalse(nucleo.toca_ejecutar(s, {"ultima": "2026-10-29T03:00:00"}, self.ahora))
        self.assertTrue(nucleo.toca_ejecutar(s, {"ultima": "2026-10-29T01:00:00"}, self.ahora))

    def test_semanal_y_mensual(self):
        e = {"ultima": "2026-10-29T09:30:00"}
        semanal = {"activo": True, "horario": {"tipo": "semanal", "dias": [5], "horas": ["08:00"]}}
        mensual = {"activo": True, "horario": {"tipo": "mensual", "dias_mes": [31], "horas": ["09:00"]}}
        self.assertEqual(nucleo.proxima_ejecucion(semanal, e, self.ahora), "2026-10-31T08:00")
        self.assertEqual(nucleo.proxima_ejecucion(mensual, e, self.ahora), "2026-10-31T09:00")
        # Noviembre tiene 30 días: el "31" cae en el último día.
        e2 = {"ultima": "2026-11-01T00:00:00"}
        self.assertEqual(nucleo.proxima_ejecucion(mensual, e2, dt.datetime(2026, 11, 1)), "2026-11-30T09:00")

    def test_equipo_apagado_recupera(self):
        s = {"activo": True, "horario": {"tipo": "diario", "horas": ["09:00"]}}
        self.assertTrue(nucleo.toca_ejecutar(s, {"ultima": "2026-10-27T09:00:00"}, self.ahora))


class PruebaSeguridad(unittest.TestCase):
    def test_carpetas_del_sistema(self):
        prohibida = nucleo.carpetas_prohibidas()[0]
        permitida, _ = nucleo.revisar_carpeta(os.path.join(prohibida, "algo"))
        self.assertFalse(permitida)

    def test_plantillas(self):
        nombres = [p["nombre"] for p in nucleo.plantillas_iniciales()]
        self.assertEqual(nombres, ["Ordenar Descargas", "Ordenar Documentos", "Ordenar Escritorio"])
        self.assertTrue(all(not p["activo"] for p in nucleo.plantillas_iniciales()))


class PruebaBaseDeDatos(unittest.TestCase):
    def test_estado_no_se_pisa(self):
        # Dos procesos leen el estado a la vez y cada uno guarda lo suyo: no se borran entre sí.
        a, b = nucleo.cargar_estado(), nucleo.cargar_estado()
        a["servicioA"] = {"ultima": "1"}
        nucleo.guardar_estado(a)
        b["servicioB"] = {"ultima": "2"}
        nucleo.guardar_estado(b)
        e = nucleo.cargar_estado()
        self.assertEqual(e["servicioA"]["ultima"], "1")
        self.assertEqual(e["servicioB"]["ultima"], "2")
        del e["servicioA"]
        nucleo.guardar_estado(e)
        self.assertNotIn("servicioA", nucleo.cargar_estado())

    def test_migra_json_antiguo(self):
        ruta = os.path.join(nucleo.DATOS, "prueba_migrar.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"x": 1}, f)
        self.assertEqual(nucleo.leer_json(ruta, {}), {"x": 1})
        self.assertFalse(os.path.exists(ruta))
        nucleo.escribir_json(ruta, {"x": 2})
        self.assertEqual(nucleo.leer_json(ruta, {}), {"x": 2})

    def test_movimientos_para_siempre(self):
        antes = nucleo.bd.total_movimientos()
        nucleo.indexar({"nombre": "S"}, [{"accion": "mover", "origen": "/a/Factura Agua.pdf", "destino": "/b/Factura Agua.pdf"}] * 3)
        self.assertEqual(nucleo.bd.total_movimientos(), antes + 3)
        r = nucleo.buscar_movidos("factura agua")
        self.assertGreaterEqual(r["total"], 3)

    def test_procesos(self):
        with nucleo.proceso("Prueba larga"):
            nucleo.avance(total=10, etapa="Contando")
            nucleo.avance(sumar=4)
            p = [x for x in nucleo.procesos() if x["nombre"] == "Prueba larga"][0]
            self.assertEqual(p["estado"], "en marcha")
        p = [x for x in nucleo.procesos() if x["nombre"] == "Prueba larga"][0]
        self.assertEqual(p["estado"], "terminado")
        self.assertEqual((p["hechos"], p["total"]), (4, 10))


class PruebaCombinarYMapa(unittest.TestCase):
    def escribir(self, ruta, contenido):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)

    def test_combinar_carpetas(self):
        raiz = tempfile.mkdtemp()
        a, b = os.path.join(raiz, "Fotos"), os.path.join(raiz, "Fotos copia")
        self.escribir(os.path.join(a, "1.jpg"), b"uno")
        self.escribir(os.path.join(b, "1.jpg"), b"uno")          # igual: a la papelera
        self.escribir(os.path.join(a, "2.jpg"), b"dos")
        self.escribir(os.path.join(b, "2.jpg"), b"DOS distinto")  # distinto: 2 (1).jpg
        self.escribir(os.path.join(b, "sub", "3.jpg"), b"tres")   # nuevo: se mueve con su carpeta
        sim = nucleo.combinar_carpetas(a, b, simular=True)
        self.assertEqual(sim["resumen"], {"mover": 2, "iguales": 1, "renombrados": 1, "bytes_liberados": 3})
        self.assertTrue(os.path.exists(os.path.join(b, "1.jpg")))
        res = nucleo.combinar_carpetas(a, b, simular=False)
        self.assertTrue(res["ok"])
        self.assertFalse(os.path.exists(b))
        self.assertTrue(os.path.exists(os.path.join(a, "2 (1).jpg")))
        self.assertTrue(os.path.exists(os.path.join(a, "sub", "3.jpg")))
        r = nucleo.deshacer(nucleo.ID_COMBINAR)
        self.assertTrue(r["ok"])
        self.assertTrue(os.path.exists(os.path.join(b, "sub", "3.jpg")))
        self.assertTrue(os.path.exists(os.path.join(b, "1.jpg")))

    def test_mapa(self):
        import mapa
        raiz = tempfile.mkdtemp()
        self.escribir(os.path.join(raiz, "docs", "Contrato renta.pdf"), b"x")
        ajustes = nucleo.cargar_ajustes()
        ajustes["mapa_archivos"] = {"activo": True, "carpetas": [raiz]}
        nucleo.guardar_ajustes(ajustes)
        self.assertTrue(mapa.escanear())
        self.assertEqual(len(mapa.buscar("contrato")), 1)
        # GESTOR lo mueve: el mapa lo sigue sin volver a recorrer.
        nuevo = os.path.join(raiz, "Contratos", "Contrato renta.pdf")
        nucleo.indexar({"nombre": "S"}, [{"accion": "mover", "origen": os.path.join(raiz, "docs", "Contrato renta.pdf"), "destino": nuevo}])
        self.assertEqual(mapa.buscar("contrato")[0]["ruta"], nuevo)
        os.remove(os.path.join(raiz, "docs", "Contrato renta.pdf"))
        self.assertTrue(mapa.escanear())
        self.assertEqual(mapa.buscar("contrato"), [])
        ajustes["mapa_archivos"] = {"activo": False, "carpetas": []}
        nucleo.guardar_ajustes(ajustes)


class PruebaVersion07(unittest.TestCase):
    def setUp(self):
        self.raiz = tempfile.mkdtemp()

    def escribir(self, ruta, contenido=b"x", hace_dias=0):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(contenido)
        if hace_dias:
            t = time.time() - hace_dias * 86400
            os.utime(ruta, (t, t))
        return ruta

    def test_etiquetas_siguen_al_archivo(self):
        import mapa
        a = self.escribir(os.path.join(self.raiz, "Garantia tele.pdf"))
        nucleo.bd.poner_etiqueta(a, "garantía")
        nucleo.bd.poner_nota(a, "Comprada en Liverpool")
        nuevo = os.path.join(self.raiz, "Casa", "Garantia tele.pdf")
        nucleo.indexar({"nombre": "S"}, [{"accion": "mover", "origen": a, "destino": nuevo}])
        self.assertEqual(nucleo.bd.etiquetas_de([nuevo])[nuevo], {"etiquetas": ["garantía"], "nota": "Comprada en Liverpool"})
        self.assertEqual(nucleo.bd.buscar_etiquetados("garantia"), [nuevo])  # sin acentos
        self.assertEqual(nucleo.bd.buscar_etiquetados("liverpool"), [nuevo])
        self.assertEqual([r["ruta"] for r in mapa.buscar("", etiqueta="garantía")], [nuevo])
        nucleo.bd.quitar_etiqueta(nuevo, "garantía")
        self.assertEqual(nucleo.bd.buscar_etiquetados("", exacta="garantía"), [])

    def test_recibo_con_fecha_limite(self):
        import pagos
        texto = "COMISION FEDERAL DE ELECTRICIDAD\nTOTAL A PAGAR: $1,234.50\nFECHA LIMITE DE PAGO: 15 NOV 26\n"
        self.assertEqual(pagos.fecha_limite(texto), dt.date(2026, 11, 15))
        self.assertEqual(pagos.monto(texto), 1234.5)
        self.assertEqual(pagos.fecha_limite("Pague antes del 03/12/2026"), dt.date(2026, 12, 3))
        self.assertEqual(pagos.proveedor_de("/x/recibo.pdf", "Telmex - estado de cuenta", {}), "Telmex")
        ruta = self.escribir(os.path.join(self.raiz, "recibo luz.txt"), texto.encode())
        pagos.EXT.add(".txt")
        try:
            r = pagos.analizar(ruta)
        finally:
            pagos.EXT.discard(".txt")
        self.assertEqual((r["tipo"], r["total"], r["limite"]), ("pago", 1234.5, "2026-11-15"))

    def test_lista_y_marcar_pagado(self):
        import pagos
        hoy = dt.date.today()
        ruta = self.escribir(os.path.join(self.raiz, "cfe.pdf"))
        d = pagos.cargar()
        d["archivos"] = {ruta: {"tipo": "pago", "proveedor": "CFE", "total": 100.0, "fecha": "",
                                "limite": (hoy + dt.timedelta(days=2)).isoformat(), "mtime": 1}}
        pagos.guardar(d)
        lista = pagos.lista(hoy)
        self.assertEqual(lista["pendiente"], 100.0)
        self.assertEqual(pagos.texto_aviso(lista["pagos"][0]), f"CFE vence el {(hoy + dt.timedelta(days=2)).day}, son $100.00.")
        pagos._etiquetar()
        self.assertIn("pendiente de pagar", nucleo.bd.etiquetas_de([ruta])[ruta]["etiquetas"])
        pagos.cambiar(lista["pagos"][0]["clave"], "pagado")
        self.assertEqual(pagos.lista(hoy)["pendiente"], 0)
        self.assertEqual(nucleo.bd.etiquetas_de([ruta])[ruta]["etiquetas"], ["pagado"])
        gastos = pagos.gastos(hoy - dt.timedelta(days=1), hoy + dt.timedelta(days=30))
        self.assertEqual(gastos, [{"proveedor": "CFE", "total": 100.0, "n": 1}])

    def test_papelera_inteligente(self):
        ruta = self.escribir(os.path.join(self.raiz, "abierto.zip"), b"z", hace_dias=40)
        op = {"accion": "papelera", "origen": ruta, "destino": ""}
        self.assertIsNone(nucleo.motivo_para_retener(op))
        t = time.time() - 40 * 86400
        os.utime(ruta, (time.time() - 3600, t))  # abierto hace una hora
        self.assertIn("Lo abriste", nucleo.motivo_para_retener(op))
        self.assertIsNone(nucleo.motivo_para_retener(dict(op, duplicado=True)))
        servicio = {"id": "s1", "nombre": "Limpieza", "origenes": [self.raiz], "activo": True,
                    "reglas": [{"si": {"extensiones": ".zip"}, "accion": "papelera"}]}
        r = nucleo.ejecutar_servicio(servicio)
        self.assertTrue(os.path.exists(ruta), r)
        ret = [x for x in nucleo.retenidos() if x["ruta"] == ruta]
        self.assertEqual(len(ret), 1)
        nucleo.decidir_retenido(ret[0]["id"], borrar=True)
        self.assertFalse(os.path.exists(ruta))

    def test_informe_pdf(self):
        import informe
        from unittest import mock
        destino = os.path.join(self.raiz, "informe.pdf")
        with mock.patch.dict(os.environ, {"GESTOR_IDIOMA": "es"}):
            r = informe.generar(ruta=destino)
        self.assertTrue(r["ok"])
        with open(destino, "rb") as f:
            contenido = f.read()
        self.assertTrue(contenido.startswith(b"%PDF-1.4") and contenido.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Informe de GESTOR", contenido)
        # en otro idioma, el informe sale traducido (también el mes)
        with mock.patch.dict(os.environ, {"GESTOR_IDIOMA": "fr"}):
            informe.generar(anio=2026, mes=10, ruta=destino)
        with open(destino, "rb") as f:
            contenido = f.read()
        self.assertIn(b"Rapport GESTOR", contenido)
        self.assertIn(b"octobre 2026", contenido.lower())

    def test_mapa_del_disco(self):
        import disco
        self.escribir(os.path.join(self.raiz, "grande.bin"), b"g" * 50000)
        for i in range(30):
            self.escribir(os.path.join(self.raiz, "sub", f"p{i}.txt"), b"p")
        r = disco.analizar(self.raiz)
        self.assertEqual((r["bytes"], r["archivos"]), (50030, 31))
        nombre, tam, _, hijos, _ = r["arbol"]
        self.assertEqual(tam, 50030)
        self.assertEqual(hijos[0][:3], ["grande.bin", 50000, ".bin"])
        sub = next(h for h in hijos if h[0] == "sub")
        self.assertEqual([h[2] for h in sub[3]], ["~"])  # los 30 archivos pequeños van en un solo bloque
        self.assertEqual(sub[3][0][4], 30)

    def test_extensiones_propias(self):
        self.assertEqual(nucleo.categoria_de(".dwg"), "3D y CAD")
        self.assertEqual(nucleo.categoria_de(".MKV"), "Vídeos")
        nucleo.guardar_extensiones_propias({"dwg": "Planos", "*.ABC": "Planos"})
        self.assertEqual(nucleo.categoria_de(".dwg"), "Planos")
        self.assertEqual(nucleo.categoria_de(".abc"), "Planos")
        self.assertNotIn(".dwg", nucleo.categorias()["3D y CAD"])
        nucleo.guardar_extensiones_propias({}, quitar=[".dwg", ".abc"])
        self.assertEqual(nucleo.categoria_de(".dwg"), "3D y CAD")
        with self.assertRaises(ValueError):
            nucleo.normalizar_extension("no vale/")

    def test_version_y_correo(self):
        import actualizar
        import correo
        self.assertGreater(actualizar.version_tupla("v0.10.0"), actualizar.version_tupla("0.9.3"))
        c = {**correo.POR_DEFECTO, "carpeta": self.raiz, "reglas": [{"remitente": "cfe.gob.mx", "carpeta": "/luz"}]}
        self.assertEqual(correo.destino_para({"correo": "avisos@cfe.gob.mx", "remitente": "CFE"}, c), "/luz")
        self.assertEqual(correo.destino_para({"correo": "juan@x.com", "remitente": "Juan Pérez"}, c),
                         os.path.join(self.raiz, "Juan Pérez"))


if __name__ == "__main__":
    unittest.main()


class PruebaUnSoloUso(PruebaServicio):
    def test_fecha_concreta(self):
        s = {"activo": True, "horario": {"tipo": "fecha", "fecha": "2026-11-02", "horas": ["08:30"]}}
        antes, despues = dt.datetime(2026, 11, 1, 12, 0), dt.datetime(2026, 11, 2, 9, 0)
        self.assertFalse(nucleo.toca_ejecutar(s, {}, antes))
        self.assertEqual(nucleo.proxima_ejecucion(s, {}, antes), "2026-11-02T08:30")
        self.assertTrue(nucleo.toca_ejecutar(s, {}, despues))
        self.assertFalse(nucleo.toca_ejecutar(s, {"ultima": "2026-11-02T08:31:00"}, despues))
        self.assertTrue(nucleo.solo_una_vez(s))

    def test_un_solo_uso_se_desactiva_y_queda_guardado(self):
        self.crear("a.pdf")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}], repetir=False)
        nucleo.guardar_servicios([s])
        r = nucleo.ejecutar_y_anotar(s)
        self.assertEqual(len(r["operaciones"]), 1)
        guardado = nucleo.cargar_servicios()[0]
        self.assertFalse(guardado["activo"])
        self.assertTrue(nucleo.cargar_estado()[s["id"]].get("usado"))

    def test_repetitivo_sigue_activo(self):
        self.crear("b.pdf")
        s = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}])
        nucleo.guardar_servicios([s])
        nucleo.ejecutar_y_anotar(s)
        self.assertTrue(nucleo.cargar_servicios()[0]["activo"])


class PruebaUsoDeDisco(unittest.TestCase):
    def test_un_cero_momentaneo_no_llega_al_panel(self):
        from collections import namedtuple
        from unittest import mock
        U = namedtuple("U", "total used free")
        respuestas = [U(0, 0, 0), U(500, 200, 300)]
        with mock.patch.object(nucleo.shutil, "disk_usage", side_effect=lambda r: respuestas.pop(0)), \
                mock.patch.object(nucleo.time, "sleep"):
            self.assertEqual(nucleo._uso_disco("C:\\").total, 500)
        with mock.patch.object(nucleo.shutil, "disk_usage", return_value=U(0, 0, 0)), \
                mock.patch.object(nucleo.time, "sleep"):
            self.assertIsNone(nucleo._uso_disco("C:\\"))
            if not nucleo.ES_WINDOWS:
                self.assertEqual(nucleo.unidades_fijas(), [])


class PruebaBorrarDesdeElMapa(unittest.TestCase):
    def test_solo_dentro_de_lo_medido_y_a_la_papelera(self):
        import disco
        raiz = tempfile.mkdtemp()
        os.makedirs(os.path.join(raiz, "sub"))
        with open(os.path.join(raiz, "sub", "x.bin"), "wb") as f:
            f.write(b"0" * 5000)
        fuera = tempfile.mkdtemp()
        disco.analizar(raiz)
        with self.assertRaises(ValueError):
            disco.borrar(fuera)
        with self.assertRaises(ValueError):
            disco.borrar(raiz)
        r = disco.borrar(os.path.join(raiz, "sub"))
        self.assertEqual(r["bytes"], 5000)
        self.assertFalse(os.path.exists(os.path.join(raiz, "sub")))
        entrada = next(e for e in nucleo.listar_papelera() if e["origen"] == os.path.join(raiz, "sub"))
        nucleo.restaurar(entrada["id"])
        self.assertTrue(os.path.exists(os.path.join(raiz, "sub", "x.bin")))


class PruebaVersionTienda(unittest.TestCase):
    """La versión de la Microsoft Store: sin tarea programada ni actualizador propio."""

    def setUp(self):
        from unittest import mock
        self.ajustes_antes = nucleo.cargar_ajustes()
        self.parches = [mock.patch.object(nucleo, "ES_TIENDA", True),
                        mock.patch.object(nucleo, "lanzar_residente", lambda: False)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        nucleo.guardar_ajustes(self.ajustes_antes)

    def test_fuera_de_la_tienda_no_se_detecta(self):
        if not os.environ.get("GESTOR_TIENDA"):
            self.assertEqual(nucleo._paquete_tienda(), "")

    def test_programacion_sin_programador_de_tareas(self):
        r = nucleo.programar_motor(7)
        self.assertTrue(r["ok"])
        self.assertEqual(nucleo.cargar_ajustes()["revisar_cada_minutos"], 7)
        self.assertEqual(nucleo.estado_programacion(), {"instalada": True, "tienda": True})
        self.assertTrue(nucleo.necesita_residente())  # el residente hace de tarea programada
        nucleo.quitar_programacion()
        self.assertFalse(nucleo.estado_programacion()["instalada"])
        self.assertFalse(nucleo.actualizar_programacion())

    def test_sin_actualizador_propio(self):
        import actualizar
        e = actualizar.estado()
        self.assertTrue(e["tienda"])
        self.assertFalse(e["nueva"] or e["puede_instalarse"] or e["activo"])
        self.assertFalse(actualizar.instalar()["ok"])
        self.assertIsNone(actualizar.mantenimiento())

    def test_el_residente_lanza_el_motor(self):
        from unittest import mock
        import residente
        nucleo.programar_motor(5)
        reloj = residente.RelojDelMotor()
        with mock.patch("subprocess.Popen") as popen:
            reloj.atender()
            popen.assert_not_called()  # todavía no toca
            reloj.ultimo -= 600
            reloj.atender()
            self.assertEqual(popen.call_count, 1)
            self.assertIn("--motor", popen.call_args[0][0])
            ajustes = nucleo.cargar_ajustes()
            ajustes["detenido"] = True
            nucleo.guardar_ajustes(ajustes)
            reloj.ultimo -= 600
            reloj.atender()
            self.assertEqual(popen.call_count, 1)  # «Cerrar GESTOR» lo detiene


class PruebaPanelCelularSeguro(unittest.TestCase):
    """El panel del celular: solo en redes privadas de Windows y cifrado."""

    def setUp(self):
        self.antes = os.environ.get("GESTOR_REDES")

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("GESTOR_REDES", None)
        else:
            os.environ["GESTOR_REDES"] = self.antes

    def test_solo_redes_privadas(self):
        import red
        os.environ["GESTOR_REDES"] = "192.168.1.20=Private,10.0.0.5=Public,172.16.0.9=DomainAuthenticated,8.8.8.8=Private"
        self.assertEqual(sorted(red.ips_privadas()), ["172.16.0.9", "192.168.1.20"])
        self.assertTrue(red.ip_permitida("192.168.1.20"))
        self.assertFalse(red.ip_permitida("10.0.0.5"))      # red pública (un café)
        self.assertFalse(red.ip_permitida("8.8.8.8"))       # no es una dirección de red local
        self.assertEqual(red.ip_para_celular("10.0.0.5"), "192.168.1.20")
        os.environ["GESTOR_REDES"] = "10.0.0.5=Public"
        self.assertFalse(red.hay_red_privada())
        self.assertIsNone(red.ip_para_celular("10.0.0.5"))

    def test_no_abre_sin_red_privada(self):
        import panel
        os.environ["GESTOR_REDES"] = "10.0.0.5=Public"
        with self.assertRaises(OSError):
            panel.servidor_en_red()

    def test_cifrado_de_extremo_a_extremo(self):
        import http.client
        import ssl
        import threading
        import panel
        import red
        if not red.cifrado_disponible():
            self.skipTest("sin cryptography")
        if not panel.hay_clave():
            panel.guardar_clave("clave-de-prueba-123")
        contexto_cliente = ssl.create_default_context()
        contexto_cliente.check_hostname = False
        contexto_cliente.verify_mode = ssl.CERT_NONE

        def arrancar(redes):
            os.environ["GESTOR_REDES"] = redes
            servidor = panel.ServidorCifrado(("127.0.0.1", 0), panel.ManejadorRed, red.contexto_tls())
            threading.Thread(target=servidor.serve_forever, daemon=True).start()
            return servidor

        def pedir(servidor):
            c = http.client.HTTPSConnection("127.0.0.1", servidor.server_address[1], timeout=10, context=contexto_cliente)
            c.request("GET", "/")
            certificado = c.sock.getpeercert(binary_form=True)
            r = c.getresponse()
            cuerpo = r.read()
            c.close()
            return r.status, cuerpo, certificado

        # En la prueba el «celular» llega por 127.0.0.1, que hace de red local; solo cambia su categoría.
        servidor = arrancar("127.0.0.1=Private")
        try:
            estado, cuerpo, certificado = pedir(servidor)
            self.assertEqual(estado, 200)                         # la página de entrada, por https
            self.assertIn(b"<html", cuerpo.lower())
            esperado = ":".join(f"{b:02X}" for b in __import__("hashlib").sha256(certificado).digest())
            self.assertEqual(red.huella(), esperado)               # la huella que enseña el panel es la real
            with self.assertRaises((ssl.SSLError, ConnectionError, http.client.HTTPException, OSError)):
                c = http.client.HTTPConnection("127.0.0.1", servidor.server_address[1], timeout=5)
                c.request("GET", "/")
                c.getresponse().read()                             # sin cifrar no responde
            os.environ["GESTOR_REDES"] = "127.0.0.1=Public"
            red._cache.update(t=0.0, redes=None)
            self.assertEqual(pedir(servidor)[0], 403)              # red pública: rechazado
        finally:
            servidor.shutdown()
            servidor.server_close()


class PruebaContrasenaOpcional(unittest.TestCase):
    """En esta PC la contraseña es opcional; el panel del celular la pide siempre."""

    def setUp(self):
        import panel
        self.panel = panel
        self.ajustes = nucleo.cargar_ajustes()
        self.habia = panel.hay_clave()
        if self.habia:
            with open(panel.ARCHIVO_CLAVE, "rb") as f:
                self.copia = f.read()
            os.remove(panel.ARCHIVO_CLAVE)

    def tearDown(self):
        nucleo.guardar_ajustes(self.ajustes)
        if os.path.exists(self.panel.ARCHIVO_CLAVE):
            os.remove(self.panel.ARCHIVO_CLAVE)
        if self.habia:
            with open(self.panel.ARCHIVO_CLAVE, "wb") as f:
                f.write(self.copia)

    def _con(self, **cambios):
        a = nucleo.cargar_ajustes()
        a.pop("pedir_clave", None)
        a.update(cambios)
        nucleo.guardar_ajustes(a)

    def test_reglas(self):
        p = self.panel
        self._con()
        self.assertFalse(p.pedir_clave())                 # instalación nueva: entra directo
        p.guardar_clave("clave-de-prueba-123")
        self.assertTrue(p.pedir_clave())                  # quien ya tenía contraseña la sigue usando
        self._con(pedir_clave=False)
        self.assertFalse(p.pedir_clave())                 # la quitó en Ajustes
        self._con(pedir_clave=True)
        self.assertTrue(p.pedir_clave())
        os.remove(p.ARCHIVO_CLAVE)
        self.assertFalse(p.pedir_clave())                 # sin contraseña no se puede pedir


class PruebaIdiomas(unittest.TestCase):
    """Traducción de la interfaz: diccionarios completos y plantillas con valores."""

    def setUp(self):
        import idioma
        self.idioma = idioma
        idioma._diccionarios.clear()
        idioma._plantillas.clear()

    def test_diccionarios_validos(self):
        import re
        for codigo, _ in self.idioma.IDIOMAS[1:]:
            d = self.idioma.diccionario(codigo)
            self.assertGreater(len(d), 1500, codigo)
            for es, otro in d.items():
                self.assertEqual(len(re.findall(r"\{\d*\}", es)), len(re.findall(r"\{\d*\}", otro)), (codigo, es))

    def test_exacto_y_plantilla(self):
        t = self.idioma.t
        self.assertEqual(t("Pausar todo", "en"), "Pause all")
        self.assertEqual(t("Pausar todo", "es"), "Pausar todo")
        self.assertEqual(t("12 archivos", "fr"), "12 fichiers")
        self.assertEqual(t("Texto que no existe", "en"), "Texto que no existe")

    def test_plantilla_reordena_valores(self):
        self.assertEqual(self.idioma.t("Mueves a «Facturas» los archivos con «cfe». ¿Lo hago yo la próxima vez? "
                                       "Míralo en el panel.", "en"),
                         "You move files with «cfe» to «Facturas». Should I do it next time? Check it in the panel.")

    def test_plantillas_cortas_no_se_usan(self):
        # «de {}» encajaría con media frase en español: se ignora.
        self.assertEqual(self.idioma.t("de cualquier cosa", "en"), "de cualquier cosa")

    def test_inyectar_en_la_pagina(self):
        os.environ["GESTOR_IDIOMA"] = "pt"
        try:
            html = self.idioma.inyectar(b"<html><head><title>x</title></head><body></body></html>")
        finally:
            del os.environ["GESTOR_IDIOMA"]
        self.assertIn(b"window.GESTOR_I18N=", html)
        self.assertIn(b'"idioma": "pt"', html)
        self.assertLess(html.index(b"GESTOR_I18N"), html.index(b"</head>"))

    def test_eleccion_guardada(self):
        self.assertEqual(self.idioma.guardar_eleccion("fr"), "fr")
        self.assertEqual(self.idioma.eleccion(), "fr")
        self.assertEqual(self.idioma.guardar_eleccion("klingon"), "auto")


class PruebaReorganizar(unittest.TestCase):
    """Volver a ordenar una carpeta que ya tenía subcarpetas, con otro orden, y poder deshacerlo."""

    def setUp(self):
        self.raiz = tempfile.mkdtemp()
        viejo = time.time() - 3 * 86400
        for rel in ["Viejo/a.jpg", "Viejo/Sub/b.pdf", "c.txt", "Mantener/d.jpg", "Proyecto/e.jpg"]:
            ruta = os.path.join(self.raiz, *rel.split("/"))
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w") as f:
                f.write(rel)
            os.utime(ruta, (viejo, viejo))
        self.año = str(dt.datetime.fromtimestamp(viejo).year)

    def _existe(self, *partes):
        return os.path.exists(os.path.join(self.raiz, *partes))

    def test_simular_no_mueve_nada(self):
        r = nucleo.reorganizar(self.raiz, simular=True, esquema="año")
        self.assertTrue(r["ok"])
        self.assertTrue(self._existe("Viejo", "a.jpg"))
        self.assertTrue(r["resumen"])
        self.assertEqual(r["resumen"][0]["carpeta"], self.año)

    def test_por_año_mueve_subcarpetas_y_respeta_mantener(self):
        r = nucleo.reorganizar(self.raiz, simular=False, esquema="año")
        self.assertTrue(r["ok"])
        for n in ["a.jpg", "b.pdf", "c.txt", "e.jpg"]:
            self.assertTrue(self._existe(self.año, n), n)
        self.assertTrue(self._existe("Mantener", "d.jpg"))
        self.assertFalse(self._existe("Viejo"))            # quedó vacía y se quitó

        d = nucleo.deshacer(nucleo.ID_REORGANIZAR)
        self.assertTrue(d["ok"])
        nucleo.quitar_carpetas_vacias(d["carpetas_destino"], self.raiz)
        self.assertTrue(self._existe("Viejo", "Sub", "b.pdf"))
        self.assertTrue(self._existe("c.txt"))
        self.assertFalse(self._existe(self.año))            # la carpeta que creó GESTOR ya no está

    def test_por_subcarpeta_conserva_proyectos(self):
        r = nucleo.reorganizar(self.raiz, simular=False, esquema="extension", por_subcarpeta=True)
        self.assertTrue(r["ok"])
        self.assertTrue(self._existe("c.txt"))              # lo suelto de la raíz no se toca
        self.assertTrue(any(self._existe("Proyecto", d, "e.jpg") for d in os.listdir(os.path.join(self.raiz, "Proyecto"))))
        self.assertTrue(any(self._existe("Viejo", d, "b.pdf") for d in os.listdir(os.path.join(self.raiz, "Viejo"))))

    def test_no_deja_reorganizar_una_carpeta_del_sistema(self):
        r = nucleo.reorganizar(os.path.splitdrive(self.raiz)[0] + os.sep, simular=True)
        self.assertFalse(r["ok"])


class PruebaDevolverMovimiento(unittest.TestCase):
    def test_devuelve_un_archivo_del_diario(self):
        raiz = tempfile.mkdtemp()
        origen, destino = os.path.join(raiz, "x.txt"), os.path.join(raiz, "Docs", "x.txt")
        os.makedirs(os.path.dirname(destino))
        with open(destino, "w") as f:
            f.write("x")
        nucleo.indexar({"id": "prueba_dev", "nombre": "Prueba"},
                       [{"accion": "mover", "origen": origen, "destino": destino, "bytes": 1, "categoria": "Documentos"}])
        self.assertTrue(nucleo.devolver_movimiento(origen, destino)["ok"])
        self.assertTrue(os.path.exists(origen))
        self.assertFalse(nucleo.devolver_movimiento(origen, destino)["ok"])   # ya no está donde lo dejó
        self.assertFalse(nucleo.devolver_movimiento(origen, os.path.join(raiz, "otro.txt"))["ok"])

    def test_quitar_carpetas_vacias_no_sube_de_mas(self):
        raiz = tempfile.mkdtemp()
        hondo = os.path.join(raiz, "A", "B", "C")
        os.makedirs(hondo)
        with open(os.path.join(raiz, "A", "lleno.txt"), "w") as f:
            f.write("x")
        self.assertEqual(nucleo.quitar_carpetas_vacias([hondo], raiz), 2)
        self.assertTrue(os.path.isdir(os.path.join(raiz, "A")))


class PruebaJerarquia(PruebaServicio):
    """Si otro servicio activo se encarga de una subcarpeta, el de la carpeta de arriba no la toca."""

    def test_la_subcarpeta_de_otro_servicio_no_se_toca(self):
        sub = os.path.join(self.origen, "Facturas")
        os.makedirs(sub)
        for ruta in (os.path.join(self.origen, "a.pdf"), os.path.join(sub, "b.pdf")):
            with open(ruta, "w") as f:
                f.write("x")
        arriba = self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}], subcarpetas=True)
        abajo = dict(self.servicio([{"si": {}, "accion": "mover", "destino": self.destino}]),
                     id="abajo", origenes=[sub])
        nucleo.guardar_servicios([arriba, abajo])
        plan, _ = nucleo.planificar(arriba, esperar_segundos=0)
        self.assertEqual([os.path.basename(o["origen"]) for o in plan], ["a.pdf"])
        nucleo.guardar_servicios([arriba, dict(abajo, activo=False)])
        plan, _ = nucleo.planificar(arriba, esperar_segundos=0)
        self.assertEqual(sorted(os.path.basename(o["origen"]) for o in plan), ["a.pdf", "b.pdf"])


class PruebaBloqueoHuerfano(unittest.TestCase):
    def test_se_quita_si_su_proceso_ya_no_existe(self):
        with open(nucleo.ARCHIVO_BLOQUEO, "w") as f:
            f.write("999999")                      # un proceso que no existe
        inicio = time.time()
        with nucleo.Bloqueo():
            pass
        self.assertLess(time.time() - inicio, 3)
        self.assertFalse(os.path.exists(nucleo.ARCHIVO_BLOQUEO))
