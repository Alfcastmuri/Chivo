# GESTOR en la Microsoft Store

Esta carpeta tiene lo necesario para publicar GESTOR en la Microsoft Store como paquete **MSIX**.
Microsoft firma el paquete gratis, la Store lo actualiza sola y cobra por ti.

| Archivo | Para qué sirve |
| --- | --- |
| `identidad.json` | Los datos de Partner Center que identifican el paquete. Mientras digan `PENDIENTE`, solo sirve para probar. |
| `hacer_paquete.py` | Prepara la carpeta del paquete (manifiesto y logotipos) a partir de `dist/GESTOR`. Lo usa GitHub Actions. |
| `probar-en-mi-pc.ps1` y `Probar GESTOR de la Store.bat` | Instalan el paquete en tu PC, sin firmar, para probarlo antes de enviarlo. |
| `../docs/privacidad.html` | La política de privacidad que pide la Store. |

GitHub Actions crea en cada compilación el artefacto **GESTOR-Store**, que trae dos archivos:
- `GESTOR-Store-X.Y.Z.msix`: el paquete que se sube a Partner Center.
- `GESTOR-Store-prueba-X.Y.Z.zip`: el paquete para probar en tu PC.

## Qué cambia en la versión de la Store

GESTOR detecta solo si se instaló desde la Store. En ese caso:

- **Arranque con Windows:** lo declara el paquete, no el archivo de la carpeta Inicio. Se apaga en Configuración › Aplicaciones › Inicio.
- **Revisiones cada N minutos:** las lanza el proceso del icono, porque la tarea programada se quedaría apuntando a la versión vieja tras cada actualización.
- **Actualizaciones:** sin «Actualizar ahora» ni consultas a GitHub; las da la Store.
- **Datos:** lo nuevo en `%APPDATA%\GESTOR` lo guarda Windows en una carpeta privada del paquete y se borra al desinstalar. Los respaldos siguen yendo a Documentos\GESTOR.

## Pasos para publicar

1. **Cuenta.** Regístrate gratis en [Partner Center](https://partner.microsoft.com/dashboard/registration) como «Individual». Pide tu INE o pasaporte y una selfie.
2. **Nombre.** En «Apps y juegos › Nueva app», reserva el nombre.
3. **Identidad.** En «Administración del producto › Identidad del producto» copia los tres datos en `identidad.json`:
   - `Package/Identity/Name` → `nombre_paquete`
   - `Package/Identity/Publisher` → `editor` (empieza con `CN=`)
   - `Package/Properties/PublisherDisplayName` → `editor_visible`
4. **Política de privacidad.** En GitHub ve a Settings › Pages, elige la rama y la carpeta `/docs`. La dirección queda así: `https://alfcastmuri.github.io/Chivo/privacidad.html`.
5. **Compilar.** Empuja el cambio y descarga el artefacto **GESTOR-Store** de GitHub Actions.
6. **Probar en tu PC.** Activa el Modo de desarrollador (Configuración › Sistema › Para programadores). Descomprime el `.zip` de prueba y abre `Probar GESTOR de la Store.bat`.
7. **Envío en Partner Center.**
   - **Precios y disponibilidad:** el precio, los mercados y, si quieres, una prueba gratis.
   - **Propiedades:** categoría *Productividad* y la URL de la política de privacidad.
   - **Clasificación por edades:** el cuestionario IARC (sin violencia ni compras de contenido: queda «Para todos»).
   - **Paquetes:** sube el `.msix`.
   - **Descripción de la Store:** usa los textos de abajo y entre 4 y 10 capturas de 1366 × 768 o más.
   - **Opciones de envío › Notas para la certificación:** usa el texto de abajo.
   - **Capacidades restringidas:** la justificación de `runFullTrust`.
8. **Certificación.** Tarda de unas horas a 3 días hábiles. Si la rechazan, el informe dice qué regla falló.
9. **Versiones nuevas.** Para cada versión nueva, sube el `.msix` nuevo en un envío nuevo.

## Textos para la ficha de la Store

**Nombre:** GESTOR (si está tomado: «GESTOR – Organizador de archivos»)

**Descripción breve:**
Ordena solo tus Descargas, tu Escritorio y tus Documentos con reglas que tú creas. Todo se queda en tu PC.

**Descripción:**
GESTOR ordena tu computadora por ti. Creas «servicios» con reglas sencillas y GESTOR los ejecuta solo, cada pocos minutos o en cuanto llega un archivo.

- Ordena Descargas y Escritorio en las carpetas que ya tienes en Documentos.
- Reconoce facturas CFDI y recibos, saca el proveedor, el RFC, el monto y la fecha límite, y te avisa antes de que venzan.
- Guarda los adjuntos de Outlook en una carpeta por remitente.
- Lee el texto de fotos de recibos con el reconocimiento de texto de Windows.
- Renombra fotos por fecha, encuentra duplicados y archiva lo viejo en ZIP.
- Mapa del disco para ver qué ocupa espacio y liberar con un clic.
- Papelera propia y «deshacer»: todo lo que mueve se puede revertir.
- Modo prueba: antes de mover nada, te enseña lo que haría.
- Panel desde el celular en tu red de casa, con contraseña.
- 200 combinaciones de colores, modo oscuro y modo cuaderno.

Privado: no sube tus archivos a ningún lado, no tiene anuncios ni recoge estadísticas.

**Características (una por línea en Partner Center):**
Servicios automáticos con reglas · Facturas CFDI y recordatorios de pago · Adjuntos de Outlook por remitente · OCR de Windows · Buscador de duplicados · Mapa del disco · Deshacer y papelera propia · Modo prueba · Panel desde el celular · Todo en tu PC

**Palabras clave:** organizar archivos, ordenar descargas, facturas CFDI, duplicados, limpiar escritorio, automatizar, Outlook adjuntos

**Notas para la certificación:**
GESTOR es un organizador de archivos. Al abrirlo pide crear una contraseña local para el panel. Para probarlo: pulsa «Nuevo servicio», elige una carpeta de origen y una regla «mover a» otra carpeta, y pulsa «Ejecutar ahora». Los servicios nuevos arrancan en modo prueba, así que no mueven nada hasta que el usuario lo aprueba. El panel es una página local (127.0.0.1) dentro de la ventana de la app. La función opcional «Adjuntos de Outlook» usa PowerShell para leer Outlook clásico por COM. La función opcional «Panel desde el celular» abre un puerto en la red privada, solo si el usuario la activa y con contraseña.

**Justificación de runFullTrust:**
GESTOR es una aplicación de escritorio Win32 (Python y WebView2) que mueve, renombra y archiva archivos en las carpetas que el usuario elige en cualquier unidad, vigila esas carpetas para ordenar al instante, muestra un icono en la bandeja y usa el OCR de Windows y Outlook clásico. Necesita acceso completo al sistema de archivos del usuario, y eso no es posible en el contenedor de aplicaciones.
