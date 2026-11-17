"""Abre el panel en un idioma, recorre todas las pestañas y lista los textos que siguen en español.

    python tienda/revisar_traduccion.py en          → imprime los textos sin traducir
    python tienda/revisar_traduccion.py en --falso  → con un diccionario de prueba que marca todo lo que
                                                      conoce, para ver qué textos no saca textos.py

Necesita Playwright (pip install playwright). Usa una carpeta de datos temporal.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "app")
ESPANOL = re.compile(r"[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|en|no|un|una|por|para|con|se|al|tu|tus|y|es|está|hay|"
                     r"archivos?|carpetas?|servicios?|ajustes|buscar|abrir|cerrar|guardar|borrar|nuevo|nueva)\b", re.I)

RECOGER = r"""() => {
  const salida = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const p = n.parentElement;
    if (!p || p.closest('script,style,code,pre,textarea,[translate=no],.notranslate')) continue;
    const st = getComputedStyle(p);
    if (st.display === 'none' || st.visibility === 'hidden' || !p.getClientRects().length) continue;
    const t = n.nodeValue.replace(/\s+/g, ' ').trim();
    if (t) salida.add(t);
  }
  document.querySelectorAll('[title],[placeholder]').forEach(e => {
    if (!e.closest('[translate=no]')) { if (e.title) salida.add(e.title); if (e.placeholder) salida.add(e.placeholder); }
  });
  return [...salida];
}"""


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    codigo = sys.argv[1] if len(sys.argv) > 1 else "en"
    falso = "--falso" in sys.argv
    datos = tempfile.mkdtemp(prefix="gestor-i18n-")
    copia_app = None
    if falso:
        copia_app = tempfile.mkdtemp(prefix="gestor-app-")
        shutil.copytree(APP, copia_app, dirs_exist_ok=True)
        with open(os.path.join(APP, "idiomas", "_textos.json"), encoding="utf-8") as f:
            textos = json.load(f)
        with open(os.path.join(copia_app, "idiomas", f"{codigo}.json"), "w", encoding="utf-8") as f:
            json.dump({t: "⟦" + t.replace("{}", "{}") + "⟧" for t in textos}, f, ensure_ascii=False)
    carpeta_app = copia_app or APP
    puerto = puerto_libre()
    entorno = dict(os.environ, GESTOR_DATOS=datos, GESTOR_IDIOMA=codigo, GESTOR_PUERTO=str(puerto),
                   GESTOR_SIN_RESIDENTE="1", PYTHONIOENCODING="utf-8")
    proceso = subprocess.Popen([sys.executable, os.path.join(carpeta_app, "panel.py"), "--sin-navegador"],
                               cwd=carpeta_app, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{puerto}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        from playwright.sync_api import sync_playwright
        vistos = set()
        with sync_playwright() as p:
            ruta = "/opt/pw-browsers/chromium"
            navegador = p.chromium.launch(executable_path=ruta) if os.path.exists(ruta) else p.chromium.launch()
            pagina = navegador.new_page(viewport={"width": 1366, "height": 860})
            pagina.on("dialog", lambda d: (vistos.add(d.message), d.dismiss()))
            pagina.goto(base + "/")
            vistos.update(pagina.evaluate(RECOGER))
            pagina.fill("#clave", "prueba123")
            pagina.fill("#repetir", "prueba123")
            pagina.click("#btn")
            pagina.wait_for_load_state("networkidle")
            time.sleep(1.5)
            vistos.update(pagina.evaluate(RECOGER))
            grupos = pagina.eval_on_selector_all("#pestanas [data-grupo]", "es => es.map(e => e.dataset.grupo)")
            for g in grupos + [None]:
                if g is None:
                    pagina.click("#btnAjustes")
                else:
                    pagina.click(f'#pestanas [data-grupo="{g}"]')
                time.sleep(0.8)
                vistos.update(pagina.evaluate(RECOGER))
                for i in range(pagina.locator("#subnav button").count()):
                    try:
                        pagina.locator("#subnav button").nth(i).click(timeout=2000)
                        time.sleep(0.8)
                        vistos.update(pagina.evaluate(RECOGER))
                        # pestañas internas de cada vista
                        internas = pagina.locator("main.vista.on .pestanas button, main.vista.on [role=tab]")
                        for k in range(min(internas.count(), 12)):
                            try:
                                internas.nth(k).click(timeout=1500)
                                time.sleep(0.4)
                                vistos.update(pagina.evaluate(RECOGER))
                            except Exception:
                                pass
                    except Exception:
                        pass
            navegador.close()
        if codigo == "en":
            sospechoso = ESPANOL.search
        else:   # en portugués y francés los acentos no dicen nada: se buscan palabras que solo son del español
            sospechoso = re.compile(r"ñ|\b(archivos?|carpetas?|está|el|los|del|y|pulsa|elige|guardar|borrar|ahora)\b", re.I).search
        pendientes = sorted(t for t in vistos
                            if "⟦" not in t and sospechoso(t) and not re.fullmatch(r"[\d\s.,:%/-]+", t))
        print(json.dumps(pendientes, ensure_ascii=False, indent=1))
        print(f"{len(pendientes)} textos en español de {len(vistos)} vistos", file=sys.stderr)
    finally:
        proceso.terminate()
        shutil.rmtree(datos, ignore_errors=True)
        if copia_app:
            shutil.rmtree(copia_app, ignore_errors=True)


if __name__ == "__main__":
    main()
