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


def jpeg_con_exif(fecha):
    cabecera = b"MM\x00\x2a\x00\x00\x00\x08"
    ifd0 = struct.pack(">H", 1) + struct.pack(">HHII", 0x8769, 4, 1, 26) + b"\x00" * 4
    exif = struct.pack(">H", 1) + struct.pack(">HHII", 0x9003, 2, 20, 44) + b"\x00" * 4
    app1 = b"Exif\x00\x00" + cabecera + ifd0 + exif + fecha.encode() + b"\x00"
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
