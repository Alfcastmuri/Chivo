## Novedades de GESTOR 0.9.10

- **Duplicados mucho más rápido la segunda vez**: GESTOR guarda la huella de cada archivo que compara. En la siguiente búsqueda solo lee los archivos nuevos o que cambiaron; los demás los reconoce al instante por su tamaño y fecha.
- **Adiós por fin al error «Tcl data directory not found»**: venía de una instalación normal antigua que seguía abriéndose sola (cada pocos minutos y al iniciar Windows) aunque ya usaras la versión de la Store. GESTOR de la Store ahora apaga ese arranque viejo y te avisa para que desinstales la copia antigua.
- **Espacio sin recorrer todo otra vez**: si el mapa de archivos está al día, Espacio ya sabe qué hay en tus carpetas y solo revisa los archivos grandes y Descargas.

## Novedades de GESTOR 0.9.9

- **Arreglado de verdad el error «Tcl data directory not found»**: al actualizar, el instalador ahora cierra cualquier GESTOR que siga abierto antes de copiar los archivos, para que ninguna copia vieja del programa se quede funcionando. Además deja preparadas las carpetas que buscaban las versiones anteriores, así que el aviso ya no puede salir aunque quede alguna copia antigua.

## Novedades de GESTOR 0.9.8

- **Contraseña opcional**: en Ajustes › General eliges si GESTOR la pide al abrirlo en esta PC. Si es nuevo, entra directo; si ya tenías una, la sigue pidiendo hasta que la quites (para eso se pide la actual). Desde el celular siempre se pide.
- **Bienvenida en 3 pasos**: eliges una carpeta, ves cómo quedaría antes de mover nada y, si te convence, se ordena al momento. Todo se puede deshacer.
- **Un Inicio que dice la verdad**: si todavía no ordena nada solo, lo dice y te ofrece empezar; en vez de ceros, te invita a ordenar tu primera carpeta.
- **«Lo que hice»**: un diario en palabras sencillas, agrupado por día, con un botón para deshacer cada movimiento.
- **Más formas de ordenar**: en el Asistente eliges cómo quedan las carpetas: por tipo, por año, por año y mes, por tipo y año, por extensión, por procedencia o todo junto. Los destinos se ven como «Imágenes › año › mes» en lugar de variables.
- **Reorganizar carpetas ya ordenadas**: vuelve a ordenar una carpeta con todas sus subcarpetas usando otro orden. Puedes conservar las subcarpetas principales (un proyecto, un viaje) y ordenar dentro de cada una. Ves cómo quedaría antes, «Mantener» no se toca y se puede deshacer.
- **Ves cómo se mueven las cosas**: mientras GESTOR ordena, la tarjeta de Estado en Inicio enseña en grande el servicio, el porcentaje, el archivo que va de una carpeta a otra y los últimos que movió. En las demás secciones aparece una tarjeta con su barra de progreso, y ahora sale siempre al analizar, ordenar, deshacer o recuperar, aunque sea rápido.
- **Servicios por jerarquía**: si un servicio ordena una carpeta y otro se encarga de una subcarpeta, cada uno respeta lo suyo y no chocan.
- **Archivos abiertos**: si un archivo está abierto en otro programa o ya no está, se deja para la próxima vez sin contarlo como error.
- **Arreglado**: el error «Tcl data directory not found» al abrir GESTOR, el aviso «database is locked», y que a veces dejaba de mover archivos tras cerrarse a la fuerza (quedaba un bloqueo que ahora se quita solo). También abre más rápido.
- **Todo cabe en la pantalla**, también en modo cuaderno y en pantallas chicas (Actividad y Línea de tiempo).
- **Menos ruido**: el idioma pasó a Ajustes, se quitaron botones repetidos de la barra superior y los textos usan singular cuando es uno solo.

## Novedades de GESTOR 0.9.7

- **Traducción completa en inglés, portugués y francés**: se tradujeron los textos que se habían quedado en español, como las barras de progreso («Buscando duplicados», «Comparando contenido»…), las propuestas del Asistente, el recuento por tipo de archivo, los nombres de las armonías de color, los mensajes de «Guardado», los avisos de Windows (resumen de la semana, pagos, vencimientos, copias) y el informe mensual en PDF, que ahora sale en tu idioma.
- **Servicios con nombre en tu idioma**: los servicios que creas desde Plantillas se llaman en el idioma elegido («Empty Downloads», «Vider Téléchargements»…) y los que ya tenías se muestran traducidos.
- **Pestañas más claras**: las secciones (arriba, a todo lo ancho) y las pestañas de dentro de cada sección ya no se ven iguales. Las de dentro son un selector compacto, más chico y separado, así se nota cuál está dentro de cuál.
- **Más aire entre secciones**: hay una distancia mínima entre paneles, entre las pestañas y su contenido, y entre tarjetas, para que nada se vea amontonado.
- **El resplandor de los marcos ya no invade a los vecinos**: la sombra y el brillo de cada panel quedan siempre detrás de todos los paneles, así los bordes y el contenido de las secciones de al lado se ven limpios.

## Novedades de GESTOR 0.9.6

- **GESTOR en tu idioma**: español, English, Português y Français. Elige el idioma arriba, junto a «Cuaderno»; «Automático» usa el idioma de Windows. Las fechas y los números también siguen el idioma elegido. Las carpetas que GESTOR crea en tu disco conservan su nombre.

## Novedades de GESTOR 0.9.5

- **Todas las pestañas con el mismo formato que Inicio y Organizar**: cada sección ocupa la ventana completa, alineada arriba y con un margen ajustado abajo y a la derecha. Ya no hay barras de desplazamiento en la página; solo se desplazan las listas largas.
  - *Encontrar, Espacio, Proteger, Al día y Personalizar*: los paneles y sus pestañas internas se adaptan a la altura de tu pantalla.
  - *Mapa del disco*: el mapa llena el espacio de la izquierda y el detalle queda a la derecha.
  - *Colores*: la vista previa y el modo a la izquierda, las opciones a la derecha.
  - *Ajustes*: las opciones se reparten en dos columnas y los botones siempre quedan a la vista.
- **Lista para la Microsoft Store**: GESTOR reconoce cuándo se instaló desde la Store. En esa versión arranca con Windows desde el propio paquete (se apaga en Configuración › Aplicaciones › Inicio), revisa tus servicios sin la tarea programada y deja que la Store lo actualice.
- **Panel del celular más seguro**: ahora va cifrado (https) y solo se abre en redes que Windows marca como privadas. En un café o cualquier red pública se queda cerrado. La primera vez el celular avisa del certificado: es normal, lo crea tu propia PC.
- **Nada cambia en la versión de siempre**: el instalador, la tarea programada y «Actualizar ahora» siguen igual.
- **Política de privacidad** publicada: GESTOR no envía tus archivos a ningún lado.

## Lo que trajo la 0.9.4

- **Inicio sin barras de desplazamiento**: todo el resumen cabe en la ventana y se adapta a la resolución de tu pantalla, con un margen ajustado abajo y a la derecha. En pantallas bajas se compacta solo.
- **Organizar, reordenado como una app profesional**: todo alineado arriba y a lo ancho de la ventana, sin espacios vacíos.
  - *Asistente*: a la izquierda eliges la carpeta y ves lo que encontró; a la derecha marcas las propuestas.
  - *Plantillas*: tarjetas en cuadrícula y, al lado, el detalle de la que elijas con sus reglas y el botón para crearla. Ya no hay que bajar por una lista larga.
  - *Sacar a la raíz*: carpeta y opciones a la izquierda, vista previa a la derecha.
  - *Adjuntos de correo*: configuración y última revisión a la izquierda, reglas por remitente a la derecha.
  - *Servicios*: la lista y el editor ocupan toda la altura y los botones Guardar, Simular y Ejecutar quedan siempre a la vista.
- Solo las listas largas (por ejemplo, muchas reglas en una pantalla chica) se desplazan por dentro.

## Lo que trajo la 0.9.3

- **El indicador de espacio ya no marca 0 de golpe**: cuando un disco (sobre todo un USB o un lector de tarjetas) contesta «0 bytes» por un momento, GESTOR vuelve a preguntar y, si sigue igual, no lo muestra en vez de pintar un 0.
- **Discos casi vacíos**: el anillo dice «<1%» en lugar de «0%».

## Lo que trajo la 0.9.2

- **Borrar desde el mapa del disco**: elige un archivo o una carpeta en el mapa y pulsa «Borrar». Una ventana te pregunta si estás seguro y te dice qué es, cuánto ocupa y dónde está. Va a la papelera, así que se puede recuperar.
- **Los avisos ya no estorban**: los mensajes y las tarjetas de progreso se ocultan con un clic, y las terminadas desaparecen solas en 3 segundos.
- **Todo simétrico y centrado**: cajas de igual ancho y alto en cada fila, el panel ocupa toda la pantalla y el contenido queda centrado en horizontal y en vertical.
- **Pestañas del mismo tamaño**: todas las pestañas de una sección miden lo mismo, y su contenido también, para que nada salte al cambiar.

## Lo que trajo la 0.9.1

- **200 combinaciones de colores**: 100 nuevas en Profesionales, Salud, Naturales, Mexicanas, Retro, Elegantes, Dinámicas, Pastel e Inspiradas en marcas (estilo Coca-Cola, Amazon, Spotify, Mercado Libre, Oxxo y más).
- **Vista previa en claro y en oscuro**: pasa el ratón por una combinación y ves cómo queda en los dos modos antes de pulsar «Aplicar».
- **Filtros por tipo y por color**, y tus combinaciones guardadas al principio.
- **Mi combinación**: edita los 5 colores con su código, genera una al azar (análoga, complementaria, triádica o monocromática) y guarda hasta 60.
- **Desde una imagen o logo**: elige una imagen y GESTOR saca sus colores (sin subirla a ningún lado). Puedes pedir otra variante, ajustarla, guardarla o aplicarla.

## Lo que trajo la 0.9.0

- **Panel rediseñado**: tarjetas redondeadas con sombras suaves, botones tipo píldora e interruptores en lugar de casillas. Sigue usando tus colores.
- **Todo ordenado por grupos**: el menú de la izquierda tiene 7 secciones con icono (Inicio, Organizar, Encontrar, Espacio, Proteger, Al día, Personalizar) y cada una muestra sus partes en pestañas. Sin páginas largas.
- **Ajustes en una ventana con pestañas**: General, Programación, Inteligencia, Celular y Datos y seguridad.
- **Servicios en pestañas**: Carpetas, Cuándo, Reglas, Opciones e Historial.
- **Tareas de un solo uso o repetitivas**: en «Cuándo» eliges «Repetir siempre» o «Solo una vez». Las de un solo uso se desactivan solas al terminar y quedan guardadas para reusarlas. También puedes programarlas para un día y hora concretos.
- **Más gráficas en Inicio**: actividad de 30 días, archivos por tipo, por servicio, tendencia semanal y anillos de espacio en disco.
- **Texto blanco sobre fondos oscuros**: botones, pestañas activas y tarjetas de color siempre se leen bien.
- **El código QR para el celular ya se ve completo.**
- **Icono propio de GESTOR** en el escritorio, el menú Inicio y junto al reloj.

## Lo que trajo la 0.8.0

- **GESTOR se abre en su propia ventana**, como cualquier programa, sin barra de direcciones ni pestañas del navegador. Usa el motor de Edge que ya trae Windows. Si prefieres el navegador, se cambia en Ajustes → Funcionamiento.
- **El Asistente vuelve al menú de la izquierda** (Organizar → 🧭 Asistente). Sigue también en Plantillas.

## Lo que trajo la 0.7.0

- **Mapa del disco al estilo WinDirStat** (Espacio): cada archivo es un rectángulo de su tamaño, en colores planos y mates que salen de tu tema. Doble clic para entrar en una carpeta.
- **Más de 670 extensiones en 23 tipos** (diseño, 3D y CAD, fuentes, libros, correo, bases de datos, subtítulos, certificados…) y en Personalizar → Tipos de archivo puedes añadir las tuyas, crear tipos nuevos o subir una lista.
- **Línea de tiempo**: tus archivos día a día, como un diario, con lo que movió GESTOR y lo que moviste tú.
- **Etiquetas y notas** en tus archivos («garantía», «impuestos»…). Se buscan en Buscar y siguen al archivo aunque se mueva.
- **Lee fotos y PDF escaneados** con el OCR que ya trae Windows: los recibos fotografiados se ordenan igual que los PDF.
- **Recordatorios de pago**: «CFE vence el 15, son $1,234». Avisa 3 días antes y el mismo día. Marca «Ya lo pagué».
- **Informe mensual en PDF** en Documentos\GESTOR\Informes: lo ordenado, el espacio liberado y los gastos por proveedor.
- **Papelera inteligente**: si un servicio quiere borrar algo que abriste hace poco o que es la única copia, te pregunta antes.
- **Adjuntos de Outlook** guardados en una carpeta por contacto o según el remitente.
- **Actualización automática**: GESTOR avisa cuando hay versión nueva y se actualiza con un clic.

**Cómo instalar:** descarga `GESTOR-Instalador-0.7.0.exe` y ábrelo; si ya tienes GESTOR, elige «Actualizar». Si Windows avisa de que protegió el equipo, pulsa «Más información» y «Ejecutar de todas formas» (el instalador no está firmado).
