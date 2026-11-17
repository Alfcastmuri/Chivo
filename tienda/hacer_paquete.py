"""Prepara la carpeta del paquete MSIX de GESTOR para la Microsoft Store.

  python tienda/hacer_paquete.py dist/GESTOR salida/paquete-tienda

Toma el GESTOR ya construido con PyInstaller (carpeta dist/GESTOR), le añade el manifiesto
(AppxManifest.xml) con la identidad de tienda/identidad.json y los logotipos que pide Windows, y deja todo
en la carpeta de salida. Después:
  - makeappx pack /d salida/paquete-tienda /p GESTOR.msix   crea el paquete que se sube a Partner Center;
  - tienda/probar-en-mi-pc.ps1                               lo instala en tu PC para probarlo sin firmar.

Solo usa la biblioteca estándar y Pillow (para los logotipos).
"""

import json
import os
import re
import shutil
import sys
from xml.sax.saxutils import escape

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (archivo, ancho, alto): los que pide el manifiesto. El icono se centra con margen en los rectangulares.
LOGOTIPOS = [("StoreLogo.png", 50, 50), ("Square44x44Logo.png", 44, 44), ("Square71x71Logo.png", 71, 71),
             ("Square150x150Logo.png", 150, 150), ("Wide310x150Logo.png", 310, 150),
             ("Square310x310Logo.png", 310, 310)]

MANIFIESTO = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:uap5="http://schemas.microsoft.com/appx/manifest/uap/windows10/5"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap uap5 rescap">
  <Identity Name="{nombre_paquete}" Publisher="{editor}" Version="{version}" ProcessorArchitecture="x64"/>
  <Properties>
    <DisplayName>{nombre_visible}</DisplayName>
    <PublisherDisplayName>{editor_visible}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
    <Description>{descripcion}</Description>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0"/>
  </Dependencies>
  <Resources>
    <Resource Language="es-MX"/>
  </Resources>
  <Applications>
    <Application Id="GESTOR" Executable="GESTOR\\GESTOR.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{nombre_visible}" Description="{descripcion}" BackgroundColor="transparent"
                          Square150x150Logo="Assets\\Square150x150Logo.png" Square44x44Logo="Assets\\Square44x44Logo.png">
        <uap:DefaultTile Wide310x150Logo="Assets\\Wide310x150Logo.png" Square71x71Logo="Assets\\Square71x71Logo.png"
                         Square310x310Logo="Assets\\Square310x310Logo.png" ShortName="{nombre_visible}"/>
      </uap:VisualElements>
      <Extensions>
        <!-- «gestor» en la terminal o en Ejecutar abre GESTOR (y admite las órdenes de siempre). -->
        <uap5:Extension Category="windows.appExecutionAlias" Executable="GESTOR\\GESTOR.exe" EntryPoint="Windows.FullTrustApplication">
          <uap5:AppExecutionAlias>
            <uap5:ExecutionAlias Alias="gestor.exe"/>
          </uap5:AppExecutionAlias>
        </uap5:Extension>
        <!-- Al iniciar sesión: GESTOR-inicio.exe (copia de GESTOR.exe) revisa los servicios de inicio y abre el icono.
             Se apaga en Configuración › Aplicaciones › Inicio. -->
        <uap5:Extension Category="windows.startupTask" Executable="GESTOR\\GESTOR-inicio.exe" EntryPoint="Windows.FullTrustApplication">
          <uap5:StartupTask TaskId="GESTORInicio" Enabled="true" DisplayName="{nombre_visible}"/>
        </uap5:Extension>
      </Extensions>
    </Application>
  </Applications>
  <Capabilities>
    <Capability Name="internetClient"/>
    <Capability Name="privateNetworkClientServer"/>
    <rescap:Capability Name="runFullTrust"/>
  </Capabilities>
</Package>
"""


def version_gestor():
    with open(os.path.join(RAIZ, "app", "nucleo.py"), encoding="utf-8") as f:
        numeros = re.search(r'VERSION = "(\d+)\.(\d+)\.(\d+)"', f.read()).groups()
    return ".".join(numeros) + ".0"  # la Store exige 4 números y el último en 0


def leer_identidad():
    with open(os.path.join(RAIZ, "tienda", "identidad.json"), encoding="utf-8") as f:
        identidad = json.load(f)
    for clave in ("nombre_paquete", "editor", "editor_visible", "nombre_visible", "descripcion"):
        if not str(identidad.get(clave, "")).strip():
            sys.exit(f"Falta «{clave}» en tienda/identidad.json")
    if not re.fullmatch(r"[A-Za-z0-9.\-]{3,50}", identidad["nombre_paquete"]):
        sys.exit("«nombre_paquete» solo admite letras, números, puntos y guiones (3 a 50).")
    if not identidad["editor"].startswith("CN="):
        sys.exit("«editor» tiene que empezar con CN= (cópialo tal cual de Partner Center).")
    return identidad


def manifiesto(identidad, version):
    valores = {k: escape(str(v), {'"': "&quot;"}) for k, v in identidad.items() if not k.startswith("_")}
    return MANIFIESTO.format(version=version, **valores)


def logotipos(destino):
    from PIL import Image
    icono = Image.open(os.path.join(RAIZ, "recursos", "gestor.png")).convert("RGBA")
    os.makedirs(destino, exist_ok=True)
    for nombre, ancho, alto in LOGOTIPOS:
        lado = min(ancho, alto)
        if ancho != alto:
            lado = int(alto * 0.8)  # en el rectangular el icono va centrado con aire alrededor
        lienzo = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
        dibujo = icono.resize((lado, lado), Image.LANCZOS)
        lienzo.paste(dibujo, ((ancho - lado) // 2, (alto - lado) // 2), dibujo)
        lienzo.save(os.path.join(destino, nombre))


def preparar(dist, salida):
    if not os.path.isfile(os.path.join(dist, "GESTOR.exe")):
        sys.exit(f"No encuentro {os.path.join(dist, 'GESTOR.exe')}: construye antes GESTOR con PyInstaller.")
    identidad = leer_identidad()
    version = version_gestor()
    if os.path.exists(salida):
        shutil.rmtree(salida)
    shutil.copytree(dist, os.path.join(salida, "GESTOR"))
    shutil.copy2(os.path.join(salida, "GESTOR", "GESTOR.exe"), os.path.join(salida, "GESTOR", "GESTOR-inicio.exe"))
    logotipos(os.path.join(salida, "Assets"))
    with open(os.path.join(salida, "AppxManifest.xml"), "w", encoding="utf-8") as f:
        f.write(manifiesto(identidad, version))
    pendiente = "PENDIENTE" in identidad["nombre_paquete"] + identidad["editor"]
    print(f"Paquete de GESTOR {version} preparado en {salida}")
    if pendiente:
        print("Aviso: la identidad es provisional (PENDIENTE). Sirve para probar en tu PC; para la Store, "
              "copia los datos de Partner Center en tienda/identidad.json.")
    return {"version": version, "pendiente": pendiente}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    preparar(sys.argv[1], sys.argv[2])
