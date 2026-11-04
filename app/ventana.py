"""GESTOR: el panel en su propia ventana, como cualquier otro programa (sin barra de direcciones ni pestañas).

Usa WebView2, el motor de Edge que ya viene con Windows 10/11, a través de pywebview.
Si no está disponible, abre Edge en «modo aplicación» (también sin barra) y, como último recurso,
el navegador normal. Con el ajuste «ventana_propia» apagado se usa siempre el navegador.
"""

import os
import subprocess
import webbrowser

import nucleo

ANCHO, ALTO = 1280, 820


def _edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        ruta = os.path.join(base or "", "Microsoft", "Edge", "Application", "msedge.exe")
        if base and os.path.isfile(ruta):
            return ruta
    return None


def _webview(url):
    """Abre la ventana y espera a que la cierres. Devuelve False si no se pudo."""
    try:
        import webview
    except Exception:
        return False
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.create_window("GESTOR", url, width=ANCHO, height=ALTO, min_size=(900, 600), text_select=True)
        # private_mode=False conserva la sesión y el tema entre aperturas.
        webview.start(private_mode=False, storage_path=os.path.join(nucleo.DATOS, "ventana"))
        return True
    except Exception:
        return False  # sin WebView2 o sin .NET: se prueba con Edge


def abrir(url):
    """Muestra el panel. Devuelve True si ya se mostró y se cerró (ventana propia), False si sigue abierto aparte."""
    if nucleo.ES_WINDOWS and nucleo.cargar_ajustes().get("ventana_propia", True):
        if _webview(url):
            return True
        edge = _edge()
        if edge:
            try:
                subprocess.Popen([edge, f"--app={url}", f"--window-size={ANCHO},{ALTO}"], creationflags=0x08000000)
                return False
            except OSError:
                pass
    webbrowser.open(url)
    return False
