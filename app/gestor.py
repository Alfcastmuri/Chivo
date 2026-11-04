"""GESTOR: punto de entrada único.

  gestor.py                abre el panel
  gestor.py --motor [...]  ejecuta el motor (lo usa el Programador de tareas)
  gestor.py --residente    icono junto al reloj, notificaciones y modo al instante
  gestor.py --detener | --reiniciar | --respaldar-base | --cerrar-procesos | --desinstalar
                           mantenimiento (lo usa el instalador)
"""

import sys


def main():
    args = sys.argv[1:]
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
