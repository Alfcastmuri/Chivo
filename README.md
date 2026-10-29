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
- **Condiciones** (se aplica la primera regla que encaja): tipo de archivo, **procedencia**
  (cámara, WhatsApp, Telegram, captura de pantalla, escáner, descarga de internet), extensión,
  nombre, **contenido** (texto de PDF, DOCX o TXT, por palabras o expresión regular), tamaño,
  antigüedad, **sin usar en N días** (desde que llegó, se modificó o se abrió), **es una factura**
  (CFDI: PDF o XML del SAT) y **ZIP ya descomprimido**.
- **Acciones:** mover, copiar, renombrar, **archivar en un ZIP mensual** o quitar (a la papelera).
  Variables para destinos y nombres: `{categoria}`, `{procedencia}`, `{camara}`, `{sitio}`,
  `{proveedor}` y `{rfc}` (de la factura), `{dato}` (lo que captura la expresión regular del
  contenido), `{tipo_acceso}` (Programas, Juegos, Sitios web…), `{extension}`, `{año}`, `{mes}`, `{mes_num}`, `{dia}`, `{nombre}`, `{carpeta_origen}`, `{origen}`.
- **Fotos por fecha de captura** (EXIF; si no hay, la fecha del nombre, como en WhatsApp).
- **Limpiar nombres:** quita "(1)", "copia", espacios dobles y caracteres raros; opcionalmente
  pone la fecha al inicio (AAAA-MM-DD).
- **Duplicados:** si en el destino ya hay un archivo con el mismo contenido, el nuevo va a la
  papelera o a una carpeta "Duplicados", y recibes una notificación.
- **Archivos hermanos juntos:** `factura.pdf` + `factura.xml`, `foto.heic` + `foto.aae` o
  `video.mp4` + `video.srt` se mueven juntos y siguen al principal.
- **Carpetas enteras:** las que llevan N días sin usarse se mueven completas, sin desarmarlas.
  La carpeta `Mantener` de cada origen nunca se toca.
- **Accesos directos** (opcional): se ordenan por tipo dentro de la misma carpeta.
- **Modo prueba:** el servicio funciona con su horario pero solo propone; apruebas con un clic.
- **Borrar las carpetas que queden vacías.**
- **Horario:** cada N minutos, horas o días; ciertas horas; ciertos días de la semana o del
  mes; al iniciar sesión; **al instante** (cuando aparece un archivo); o solo manual.

## Más herramientas del panel

- **Plantillas** para Descargas, Documentos, Escritorio, Imágenes, capturas, Vídeos, Música,
  facturas y escaneados. Los documentos van a las subcarpetas que **ya existen** en Documentos
  (Facturas, Contratos, Bancos…); si hay que crear alguna, siempre es dentro de Documentos.
  "Vaciar Descargas" y "Vaciar Escritorio" llevan a Documentos lo que lleva 14 días sin usarse,
  y mandan a la papelera los instaladores de más de 30 días y los ZIP ya descomprimidos.
- **Buscar:** ¿a dónde fue mi archivo? Busca por nombre en todo lo que GESTOR ha movido.
- **Espacio:** uso de cada disco, aviso si queda menos del 10 % libre y qué se puede liberar.
- **No molestar:** con batería, con un juego o presentación a pantalla completa o en ciertas
  horas, los servicios esperan.
- **Aviso semanal** con lo que se ordenó.
- **Aprender de ti:** si mueves a mano archivos a una carpeta de Documentos, GESTOR ve qué tienen
  en común y te propone una regla ("los archivos con «predial» van a Casa").
- **Vencimientos:** lee la vigencia de pólizas, contratos, INE, pasaportes, licencias y garantías
  y avisa un mes antes, una semana antes y el día.
- **Facturas con nombre útil:** `2026-10 CFE $1,234.50 A77.pdf`, con los datos del XML.
- **Respaldo con versiones** a OneDrive, Google Drive o un disco: `Actual` y `Versiones`.
- **Desde el celular:** el panel en la red de casa (`http://IP-del-PC:8770`), con contraseña.
- **Pausar todo / Detener GESTOR** desde el panel o el icono. Al abrir una versión nueva, la
  anterior se cierra sola y la tarea programada pasa a usar el .exe nuevo.
- **Asistente:** analiza una carpeta y propone reglas ("tienes 340 fotos de WhatsApp").
- **Duplicados:** busca archivos idénticos en las carpetas o discos que elijas.
- **Papelera de GESTOR:** guarda 30 días (configurable) lo que se quita, con restauración.
- **Copias a USB:** al conectar una unidad concreta, copia ahí lo nuevo de las carpetas elegidas.
- **Estadísticas:** archivos ordenados, espacio liberado y reparto por tipo.
- **Icono junto al reloj:** notificaciones, "Ejecutar ahora", "Pausar todo" y "Abrir panel".
- **Exportar e importar** la configuración, y **contraseña** para abrir el panel.

## Cómo funciona

- `GESTOR.exe` abre el panel (http://127.0.0.1:8765, solo accesible desde tu equipo).
  Se cierra con el botón **Cerrar panel** o a los 5 minutos de cerrar la pestaña.
- `GESTOR.exe --motor` es lo que lanza el Programador de tareas (tarea `GESTOR\Motor`).
  Revisa qué servicios toca ejecutar, los ejecuta y se cierra: entre revisiones no
  consume nada.
- `GESTOR.exe --residente` es el proceso del icono y del modo al instante. Arranca al iniciar
  sesión y se cierra solo si no hace falta.
- Tu configuración, el historial y la papelera se guardan en `%APPDATA%\GESTOR` (los archivos
  quitados de otros discos se guardan en `X:\GESTOR-papelera`, oculta, para no copiar entre discos).
- Los errores del motor y del residente quedan en `%APPDATA%\GESTOR\errores.log`.
- ¿Olvidaste la contraseña? Borra `%APPDATA%\GESTOR\credenciales.json` y crea otra; no se pierde nada.

## Desarrollo

```
python app\gestor.py                 # abre el panel
python app\gestor.py --motor         # ejecuta el motor una vez
python -m unittest discover -s tests # pruebas
construir.bat                        # genera dist\GESTOR\GESTOR.exe
```

Funciona solo con la biblioteca estándar de Python. Las librerías de `requirements.txt`
(Pillow, pillow-heif, pypdf, watchdog, pystray) son opcionales y el `.exe` ya las incluye.

Cada vez que se sube un cambio a `main`, GitHub Actions construye el `.exe`. Al crear una
etiqueta `v1.0.0` se publica como *Release*.
