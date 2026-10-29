import datetime as dt
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
        self.assertFalse(servicio["activo"])
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


if __name__ == "__main__":
    unittest.main()
