"""GESTOR: punto de entrada único.

  gestor.py                abre el panel
  gestor.py --motor [...]  ejecuta el motor (lo usa el Programador de tareas)
  gestor.py --residente    icono junto al reloj, notificaciones y modo al instante
  gestor.py --detener | --reiniciar | --respaldar-base | --cerrar-procesos | --desinstalar
                           mantenimiento (lo usa el instalador)
  gestor.py --diagnostico RUTA   escribe en RUTA (JSON) la versión y si corre como paquete de la Store

En la versión de la Microsoft Store, Windows abre «GESTOR-inicio.exe» (una copia de GESTOR.exe) al iniciar
sesión: equivale a «--motor --inicio».
"""

import os
import sys


def main():
    args = sys.argv[1:]
    if not args and os.path.basename(sys.executable).lower() == "gestor-inicio.exe":
        args = ["--motor", "--inicio"]
    if args and args[0] == "--diagnostico":
        import json
        import nucleo
        with open(args[1], "w", encoding="utf-8") as f:
            json.dump({"version": nucleo.VERSION, "tienda": nucleo.ES_TIENDA, "paquete": nucleo.PAQUETE_TIENDA,
                       "ejecutable": nucleo.EJECUTABLE, "datos": nucleo.DATOS}, f, ensure_ascii=False)
        return
    if args and args[0] == "--motor":
        import motor
        motor.main_seguro(args[1:])
    elif args and args[0] == "--residente":
        import residente
        residente.main_seguro(args[1:])
    elif args and args[0] in ("--detener", "--reiniciar", "--respaldar-base", "--cerrar-procesos", "--desinstalar"):
        import mantenimiento
        mantenimiento.main(args[0], args[1:])
    elif args and args[0] == "--elegir-carpeta":
        import panel
        panel.dialogo_carpeta(args[1], args[2] if len(args) > 2 else "")
    else:
        import panel
        panel.main()


if __name__ == "__main__":
    main()
