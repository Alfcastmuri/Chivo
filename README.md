# GESTOR

Organizador automático de archivos para Windows. Desde un panel en el navegador creas
**servicios**: cada uno vigila las carpetas que elijas (en cualquier parte del disco) y,
según su horario, ordena los archivos con tus reglas.

## Cómo se usa

1. Descarga `GESTOR-windows.zip` desde *Releases* (o desde la pestaña *Actions*, en la última
   ejecución correcta), descomprímelo donde quieras y abre `GESTOR.exe`.
   La primera vez Windows puede mostrar "Windows protegió su PC": pulsa **Más información →
   Ejecutar de todas formas** (el programa no está firmado).
   Si el antivirus lo borra (falso positivo frecuente con PyInstaller), restáuralo desde la
   cuarentena y añade la carpeta a las exclusiones, o usa la versión sin `.exe` (abajo).
2. Se abre el panel en el navegador. Ya hay tres servicios de ejemplo, desactivados:
   **Ordenar Descargas**, **Ordenar Documentos** y **Ordenar Escritorio**.
3. Revisa un servicio, pulsa **Simular** para ver qué haría sin tocar nada, y cuando te
   convenza márcalo como **Activo** y **Guarda**.
4. Pulsa **Programación → Activar** para que Windows lance el motor automáticamente.

### Versión sin .exe

Instala Python desde python.org (marca "Add python.exe to PATH"), descarga `GESTOR-python.zip`,
descomprímelo y haz doble clic en `GESTOR.pyw`. Funciona igual, y como lo ejecuta
`pythonw.exe` (firmado por la Python Software Foundation) los antivirus no lo bloquean.

## Qué puede hacer un servicio

- **Carpetas:** una o varias, con o sin subcarpetas. Nunca actúa en `C:\Windows`,
  `Program Files` ni `ProgramData`.
- **Reglas** (se aplica la primera que encaja): por tipo de archivo, extensión, nombre,
  tamaño o antigüedad. Acciones: mover, copiar, renombrar o enviar a la papelera.
  Los destinos admiten variables: `{categoria}`, `{extension}`, `{año}`, `{mes}`,
  `{mes_num}`, `{dia}`, `{nombre}`, `{carpeta_origen}`, `{origen}`.
  La fecha puede ser la de modificación, la de creación o la de **captura de la foto**.
- **Horario:** cada N minutos, horas o días; ciertas horas todos los días; ciertos días de
  la semana o del mes; al iniciar sesión; o solo manual. Si el equipo estaba apagado,
  se ejecuta al encenderlo.
- **Seguridad:** espera a que un archivo lleve unos minutos sin cambios, ignora descargas a
  medias y accesos directos, nunca borra definitivamente, guarda un historial de cada
  ejecución y permite **deshacerla**.

## Cómo funciona

- `GESTOR.exe` abre el panel (http://127.0.0.1:8765, solo accesible desde tu equipo).
  Se cierra con el botón **Cerrar panel** o a los 5 minutos de cerrar la pestaña.
- `GESTOR.exe --motor` es lo que lanza el Programador de tareas (tarea `GESTOR\Motor`).
  Revisa qué servicios toca ejecutar, los ejecuta y se cierra: entre revisiones no
  consume nada.
- Tu configuración y el historial se guardan en `%APPDATA%\GESTOR`. Los errores del motor
  quedan en `%APPDATA%\GESTOR\errores.log`.

## Desarrollo

```
python app\gestor.py                 # abre el panel
python app\gestor.py --motor         # ejecuta el motor una vez
python -m unittest discover -s tests # pruebas
construir.bat                        # genera dist\GESTOR\GESTOR.exe
```

Solo usa la biblioteca estándar de Python. Si `Pillow` está instalado, la fecha de captura
funciona con más formatos además de JPEG.

Cada vez que se sube un cambio a `main`, GitHub Actions construye el `.exe`. Al crear una
etiqueta `v1.0.0` se publica como *Release*.
