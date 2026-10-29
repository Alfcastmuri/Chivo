"""GESTOR: motor. Lo lanza el Programador de tareas; ejecuta los servicios que toca y se cierra.

Uso (también como "gestor.py --motor ..." o "GESTOR.exe --motor ..."):
  motor.py                    ejecuta los servicios activos cuyo horario ha llegado
  motor.py --inicio           además, los servicios programados "al iniciar sesión"
  motor.py --servicio ID      ejecuta ese servicio ahora
  motor.py --simular ID       muestra qué haría ese servicio, sin tocar nada
  motor.py --deshacer ID      deshace la última ejecución de ese servicio
"""

import datetime as dt
import json
import sys

import nucleo


def buscar(servicio_id):
    for s in nucleo.cargar_servicios():
        if s["id"] == servicio_id:
            return s
    sys.exit(f"No existe el servicio {servicio_id}")


def revisar(al_iniciar=False):
    ahora = dt.datetime.now()
    tareas_de_mantenimiento()
    if nucleo.cargar_ajustes().get("pausado"):
        return
    estado = nucleo.cargar_estado()
    cambiado = False
    pendientes = []
    for s in nucleo.cargar_servicios():
        if not s.get("activo"):
            continue
        e = estado.setdefault(s["id"], {})
        if "visto" not in e:
            e["visto"] = ahora.isoformat(timespec="seconds")
            cambiado = True
        tipo = (s.get("horario") or {}).get("tipo")
        if (al_iniciar and tipo == "inicio") or nucleo.toca_ejecutar(s, e, ahora):
            pendientes.append(s)
    if cambiado:
        nucleo.guardar_estado(estado)
    for s in pendientes:
        nucleo.ejecutar_y_anotar(s, motivo="inicio" if al_iniciar else "horario")


def tareas_de_mantenimiento():
    """Cosas baratas que conviene hacer en cada revisión, haya o no servicios que ejecutar."""
    for tarea in (nucleo.lanzar_residente, nucleo.purgar_papelera, copias_si_toca):
        try:
            tarea()
        except Exception:
            registrar_error("mantenimiento")


def copias_si_toca():
    if nucleo.cargar_ajustes().get("pausado"):
        return
    pendientes, _ = nucleo.copias_pendientes()
    for copia in pendientes:
        nucleo.ejecutar_copia(copia)


def registrar_error(contexto):
    import traceback
    with open(nucleo.ARCHIVO_ERRORES, "a", encoding="utf-8") as f:
        f.write(f"--- {dt.datetime.now().isoformat(timespec='seconds')} {contexto}\n")
        f.write(traceback.format_exc())


def main(args):
    if not args or args == ["--inicio"]:
        revisar(al_iniciar=bool(args))
    elif args[0] == "--servicio" and len(args) == 2:
        r = nucleo.ejecutar_y_anotar(buscar(args[1]))
        print(f'{len(r["operaciones"])} archivos ordenados, {len(r["errores"])} errores.')
    elif args[0] == "--simular" and len(args) == 2:
        r = nucleo.ejecutar_servicio(buscar(args[1]), simular=True)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args[0] == "--deshacer" and len(args) == 2:
        print(json.dumps(nucleo.deshacer(args[1]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)


def main_seguro(args):
    """Bajo el Programador de tareas no hay consola: los errores se guardan en errores.log."""
    try:
        main(args)
    except SystemExit:
        raise
    except Exception:
        registrar_error(args)


if __name__ == "__main__":
    main_seguro(sys.argv[1:])
