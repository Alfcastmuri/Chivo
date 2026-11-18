"""Recorre el panel en un idioma con datos de ejemplo, pulsa (casi) todos los botones y lista los textos que
idioma.js no supo traducir: también los que arma el panel al vuelo y los avisos que manda Python.

    python tienda/rastrear_traduccion.py en

Más lento que revisar_traduccion.py (unos minutos), pero ve lo que solo aparece al pulsar algo. Usa una carpeta
de datos y una carpeta personal temporales: no toca tus archivos. Lo que imprime en inglés o con rutas es ruido
(textos ya traducidos que se vuelven a mirar, nombres de archivos); lo que sigue en español es lo que falta.
Necesita Playwright (pip install playwright)."""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.request
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
codigo = sys.argv[1]
APP = os.path.join(REPO, "app")
copia = tempfile.mkdtemp(prefix="gapp-")
shutil.copytree(APP, copia, dirs_exist_ok=True)
js = open(os.path.join(copia, "idioma.js"), encoding="utf-8").read()
anota = "if (__n === __a && /\\p{L}/u.test(__a)) (window.__faltan = window.__faltan || new Set()).add(normal(__a));"
js = js.replace("    const nuevo = traducir(actual);", "    const nuevo = traducir(actual); { const __a = actual, __n = nuevo; " + anota + " }", 1)
js = js.replace("      const nuevo = traducir(v);", "      const nuevo = traducir(v); { const __a = v, __n = nuevo; " + anota + " }", 1)
js = js.replace("window.alert = m => alertaOriginal(traducir(String(m ?? \"\")));", "window.alert = m => { const __a = String(m ?? \"\"), __n = traducir(__a); " + anota + " return alertaOriginal(__n); };")
js = js.replace("window.confirm = m => confirmarOriginal(traducir(String(m ?? \"\")));", "window.confirm = m => { const __a = String(m ?? \"\"), __n = traducir(__a); " + anota + " return confirmarOriginal(__n); };")
assert js.count("__faltan") == 8, js.count("__faltan")
open(os.path.join(copia, "idioma.js"), "w", encoding="utf-8").write(js)
casa = tempfile.mkdtemp(prefix="gcasa-")
for d in ["Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music", "Documents/Facturas", "Documents/Bancos"]:
    os.makedirs(os.path.join(casa, d), exist_ok=True)
viejo = time.time() - 40 * 86400
for n in ["factura CFE.pdf", "foto vacaciones.jpg", "setup.exe", "notas.txt", "presupuesto.xlsx", "video.mp4",
          "cancion.mp3", "comprimido.zip", "Screenshot 2026-10-01.png", "recibo luz (1).pdf", "copia de notas.txt"]:
    for d in ["Downloads", "Desktop"]:
        p = os.path.join(casa, d, n); open(p, "w").write("x" * 2000); os.utime(p, (viejo, viejo))
datos = tempfile.mkdtemp(prefix="gdatos-")
def puerto():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
pu = puerto()
ent = dict(os.environ, GESTOR_DATOS=datos, GESTOR_IDIOMA=codigo, GESTOR_PUERTO=str(pu), GESTOR_SIN_RESIDENTE="1",
           PYTHONIOENCODING="utf-8", HOME=casa)
proc = subprocess.Popen([sys.executable, os.path.join(copia, "panel.py"), "--sin-navegador"], cwd=copia, env=ent,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = f"http://127.0.0.1:{pu}"
for _ in range(60):
    try: urllib.request.urlopen(base + "/", timeout=1); break
    except Exception: time.sleep(0.25)
from playwright.sync_api import sync_playwright
NO = re.compile(r"btnSalir|btnCerrar|btnCuaderno|idioma|salir|cerrar sesi|cerrar panel|Log out|Close panel|Sign out|Déconnexion|Sair|Encerrar|Fermer le panneau|Fechar painel", re.I)
dialogos = set()
with sync_playwright() as p:
    ruta = "/opt/pw-browsers/chromium"
    nav = p.chromium.launch(executable_path=ruta) if os.path.exists(ruta) else p.chromium.launch()
    pg = nav.new_page(viewport={"width": 1366, "height": 860})
    pg.on("dialog", lambda d: (dialogos.add(d.message), d.accept() if d.type != "prompt" else d.accept("prueba")))
    pg.goto(base + "/")
    pg.fill("#clave", "prueba123"); pg.fill("#repetir", "prueba123"); pg.click("#btn")
    pg.wait_for_load_state("networkidle"); time.sleep(1.5)
    def cerrar_modales():
        for _ in range(3):
            pg.keyboard.press("Escape"); time.sleep(0.1)
        pg.evaluate("""() => document.querySelectorAll('.modal.on, .modal[open], dialog[open]').forEach(m => { m.classList.remove('on'); if (m.close) try { m.close() } catch(e){} })""")
    def pulsar_todo(alcance, maximo=60):
        n = 0
        botones = pg.locator(alcance + " button:visible")
        total = min(botones.count(), maximo)
        textos = []
        for i in range(total):
            try:
                b = botones.nth(i)
                h = b.evaluate("e => e.id + ' ' + e.textContent + ' ' + (e.title||'')")
                textos.append(h)
            except Exception:
                textos.append("")
        for i, h in enumerate(textos):
            if NO.search(h): continue
            try:
                botones = pg.locator(alcance + " button:visible")
                if i >= botones.count(): break
                botones.nth(i).click(timeout=1500); time.sleep(0.5)
                # dentro de un modal: pulsar sus botones de pestañas
                for k in range(min(pg.locator(".modal.on button:visible").count(), 25)):
                    try:
                        bb = pg.locator(".modal.on button:visible").nth(k)
                        t = bb.text_content() or ""
                        if NO.search(t) or re.search(r"Borrar|Delete|Supprimer|Excluir|Apagar|Vaciar|Empty|Vider|Esvaziar|Restaurar|Restore", t): continue
                        bb.click(timeout=800); time.sleep(0.25)
                    except Exception: pass
                cerrar_modales()
            except Exception:
                cerrar_modales()
    for ronda in range(2):
        grupos = pg.eval_on_selector_all("#pestanas [data-grupo]", "es => es.map(e => e.dataset.grupo)")
        for g in grupos:
            pg.click(f'#pestanas [data-grupo="{g}"]'); time.sleep(0.6)
            subs = pg.locator("#subnav button").count()
            for i in range(max(subs, 1)):
                if subs:
                    try: pg.locator("#subnav button").nth(i).click(timeout=1500); time.sleep(0.6)
                    except Exception: continue
                pulsar_todo("main.vista.on")
                cerrar_modales()
        try:
            pg.click("#btnAjustes"); time.sleep(0.6); pulsar_todo("#modalAjustes"); cerrar_modales()
        except Exception: pass
    faltan = pg.evaluate("() => [...(window.__faltan || [])]")
    nav.close()
proc.terminate()
for d in (copia, casa, datos):
    shutil.rmtree(d, ignore_errors=True)
ESPANOL = re.compile(r"[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|en|no|un|una|por|para|con|se|al|tu|tus|y|es|está|hay|"
                     r"archivos?|carpetas?|servicios?)\b", re.I)
pendientes = sorted(t for t in set(faltan) | dialogos if ESPANOL.search(t) and not t.startswith(("/", "(/")))
print(json.dumps(pendientes, ensure_ascii=False, indent=1))
print(f"{len(pendientes)} textos que parecen español (de {len(set(faltan))} sin cambiar)", file=sys.stderr)
