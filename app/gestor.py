"""GESTOR: punto de entrada único.

  gestor.py                abre el panel
  gestor.py --motor [...]  ejecuta el motor (lo usa el Programador de tareas)
"""

import sys


def main():
    args = sys.argv[1:]
    if args and args[0] == "--motor":
        import motor
        motor.main_seguro(args[1:])
    elif args and args[0] == "--elegir-carpeta":
        import panel
        panel.dialogo_carpeta(args[1], args[2] if len(args) > 2 else "")
    else:
        import panel
        panel.main()


if __name__ == "__main__":
    main()
