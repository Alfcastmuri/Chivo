/* GESTOR: traducción de la interfaz.
 *
 * El panel está escrito en español. Este archivo traduce en el navegador cada texto en español que aparece
 * (también los que el panel escribe después) usando el diccionario del idioma elegido, que el servidor pone
 * en window.GESTOR_I18N = {idioma, textos: {"texto en español": "traducción"}, idiomas: [[código, nombre]]}.
 *
 * - Un texto con partes variables se busca como plantilla: «Se movieron {} archivos» encaja con
 *   «Se movieron 12 archivos» y la traducción recibe los mismos valores en el mismo orden ({} o {0}, {1}...).
 * - Si un texto no está en el diccionario se queda en español.
 * - Los elementos con translate="no" o la clase notranslate (nombres de archivos, carpetas...) no se tocan.
 */
(function () {
  "use strict";
  const datos = window.GESTOR_I18N || { idioma: "es", textos: {}, idiomas: [] };
  const idioma = datos.idioma || "es";
  document.documentElement.lang = idioma;
  const activo = idioma !== "es" && datos.textos && Object.keys(datos.textos).length > 0;

  const exactos = new Map();
  const plantillas = [];            // [{re, destino}]
  const escapar = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const normal = s => s.replace(/\s+/g, " ").trim();

  if (activo) {
    for (const [origen, destino] of Object.entries(datos.textos)) {
      if (!destino) continue;
      if (/\{\d*\}/.test(origen)) {
        const partes = normal(origen).split(/\{\d*\}/);
        const letras = (partes.join("").match(/\p{L}/gu) || []).length;
        // «de {}», «{} a {}»: encajarían con cualquier cosa. Sí vale si empieza fijo y en mayúscula («Si es {}»).
        if (letras < 5 && !(partes[0].length >= 3 && /^\p{Lu}/u.test(partes[0]))) continue;
        const re = new RegExp("^" + partes.map(escapar).join("(.*?)") + "$", "s");
        // Un valor pegado a «\» es parte de una ruta: no se traduce (la carpeta se llama así en el disco).
        // Lo mismo entre «» o comillas: es un dato tuyo (una carpeta, una palabra que buscas).
        const ruta = partes.slice(0, -1).map((p, i) => /[\\«"“']$/.test(p) || /^[\\»"”']/.test(partes[i + 1]));
        plantillas.push({ re, destino, fijo: partes.join("").length, letras, ruta });
      } else {
        exactos.set(normal(origen), destino);
      }
    }
    plantillas.sort((a, b) => b.fijo - a.fijo);   // la plantilla más específica gana
  }

  function rellenar(destino, valores, ruta = []) {
    let i = 0;
    return destino.replace(/\{(\d*)\}/g, (_, n) => {
      const k = n === "" ? i++ : Number(n);
      const v = valores[k];
      return v === undefined ? "" : ruta[k] ? v : traducir(v);
    });
  }

  const LETRAS = /[A-Za-zÁÉÍÓÚÜÑáéíóúüñ¿¡]/;
  const BORDES = /^([^\p{L}\p{N}¿¡«"'(]*)(.*?)([^\p{L}\p{N}»"'.!?…)]*)$/su;

  // minimo: parte de las letras del texto que debe ser fija en la plantilla (0 = cualquiera).
  function buscar(limpio, minimo = 0) {
    let salida = exactos.get(limpio);
    if (salida !== undefined) return salida;
    const total = minimo ? (limpio.match(/\p{L}/gu) || []).length : 0;
    for (const p of plantillas) {
      const m = p.re.exec(limpio);
      if (!m || minimo && p.letras < total * minimo) continue;
      // Un valor con « → » o « · » es media frase compuesta: mejor trozo a trozo (porTrozos).
      if (m.slice(1).some((v, k) => !p.ruta[k] && /\s[→·]\s/.test(v))) continue;
      return rellenar(p.destino, m.slice(1), p.ruta);
    }
    return null;
  }

  // Textos que el panel arma pegando trozos («Si es Imágenes, sin usar en 30 días → mover a C:\…»):
  // si no están enteros en el diccionario, se traduce trozo a trozo.
  const O = { en: " or ", pt: " ou ", fr: " ou " }[idioma] || " o ";
  const sinLetras = t => !LETRAS.test(t) || /^[.,\w:\\/-]+$/.test(t) && !/[áéíóúñ]/.test(t) && /[.\\:/\d]/.test(t);
  function porTrozos(limpio) {
    for (const [sep, junta, todos] of [[" · ", " · ", false], [" → ", " → ", false], [", ", ", ", true], [" o ", O, true]]) {
      if (!limpio.includes(sep)) continue;
      const trozos = limpio.split(sep);
      const hechos = trozos.map(t => traducir(t));
      const cambiados = hechos.filter((h, i) => h !== trozos[i]).length;
      if (!cambiados) continue;
      if (todos && hechos.some((h, i) => h === trozos[i] && !sinLetras(trozos[i]))) continue;
      return hechos.join(junta);
    }
    return null;
  }

  const cache = new Map();
  function traducir(texto) {
    if (!activo || typeof texto !== "string") return texto;
    const limpio = normal(texto);
    if (!limpio || !LETRAS.test(limpio)) return texto;
    let salida = cache.get(limpio);
    if (salida === undefined) {
      salida = buscar(limpio);
      if (salida === null) salida = porTrozos(limpio);
      if (salida === null) {
        // «+ Imágenes», «GESTOR clásico ✓», «📓 Cuaderno»: se traduce lo de en medio y se dejan los símbolos.
        const m = BORDES.exec(limpio);
        if (m && (m[1] || m[3]) && LETRAS.test(m[2])) {
          const centro = buscar(m[2]);
          if (centro !== null) salida = m[1] + centro + m[3];
        }
      }
      if (cache.size > 5000) cache.clear();
      cache.set(limpio, salida);
    }
    if (salida === null) return texto;
    const inicio = texto.match(/^\s*/)[0], fin = texto.match(/\s*$/)[0];
    return inicio + salida + fin;
  }

  // Fechas y números: el panel pide «es»; se usa el idioma elegido.
  if (idioma !== "es") {
    const LOCALE = { en: "en-US", pt: "pt-BR", fr: "fr-FR" }[idioma] || idioma;
    const cambiar = loc => (!loc || (typeof loc === "string" && /^es\b/.test(loc))) ? LOCALE : loc;
    for (const [proto, metodos] of [[Date.prototype, ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"]],
                                   [Number.prototype, ["toLocaleString"]]]) {
      for (const m of metodos) {
        const original = proto[m];
        proto[m] = function (loc, opciones) {
          // Los números se quedan como en México (1,234.5) salvo en francés y portugués, que usan su formato.
          if (proto === Number.prototype && idioma === "en") return original.call(this, loc, opciones);
          return original.call(this, cambiar(loc), opciones);
        };
      }
    }
    const Formato = Intl.DateTimeFormat;
    Intl.DateTimeFormat = function (loc, opciones) { return new Formato(cambiar(loc), opciones); };
    Intl.DateTimeFormat.prototype = Formato.prototype;
    Intl.DateTimeFormat.supportedLocalesOf = Formato.supportedLocalesOf;
  }

  window.t = traducir;              // para el código del panel que quiera traducir algo a mano
  window.GESTOR_IDIOMA = idioma;

  if (!activo) return;

  const originales = new WeakMap();  // nodo de texto -> {es, mostrado}
  const ATRIBUTOS = ["placeholder", "title", "aria-label", "alt"];
  const SALTAR = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "KBD"]);

  function excluido(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (SALTAR.has(e.tagName) || e.isContentEditable) return true;
      if (e.getAttribute("translate") === "no" || e.classList.contains("notranslate")) return true;
    }
    return false;
  }

  function nodoTexto(n) {
    const actual = n.nodeValue;
    const previo = originales.get(n);
    if (previo && previo.mostrado === actual) return;
    if (excluido(n.parentElement)) return;
    const nuevo = traducir(actual);
    originales.set(n, { es: actual, mostrado: nuevo });
    if (nuevo !== actual) n.nodeValue = nuevo;
  }

  function atributos(el) {
    if (excluido(el)) return;
    for (const a of ATRIBUTOS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const marca = "data-i18n-" + a;
      if (el.getAttribute(marca) === v) continue;
      const nuevo = traducir(v);
      if (nuevo !== v) el.setAttribute(a, nuevo);
      el.setAttribute(marca, nuevo);
    }
    if (el.tagName === "INPUT" && (el.type === "button" || el.type === "submit") && el.value) {
      const nuevo = traducir(el.value);
      if (nuevo !== el.value) el.value = nuevo;
    }
  }

  // Un párrafo con <code>, <b>... en medio se traduce entero, como una sola frase (se pierde el formato
  // de esas partes, pero la frase queda bien). Solo si lo de dentro es formato, nunca botones ni enlaces.
  const FORMATO = new Set(["CODE", "B", "STRONG", "EM", "I", "SMALL", "SPAN", "KBD", "U", "MARK", "BR"]);
  function frase(el) {
    if (el.getAttribute("data-i18n-frase") === el.textContent) return;
    let texto = false, formato = false;
    for (const h of el.childNodes) {
      if (h.nodeType === 3) { if (LETRAS.test(h.nodeValue)) texto = true; }
      else if (h.nodeType === 1) {
        if (!FORMATO.has(h.tagName) || h.id || h.children.length || [...h.attributes].some(a => a.name.startsWith("data-"))) return;
        formato = true;
      }
    }
    if (!texto || !formato || excluido(el)) return;
    const limpio = normal(el.textContent);
    if (limpio.length > 2000) return;
    const salida = buscar(limpio, 0.7);
    if (salida === null) return;
    el.textContent = salida;
    el.setAttribute("data-i18n-frase", el.textContent);
  }

  function recorrer(raiz) {
    if (raiz.nodeType === 3) return nodoTexto(raiz);
    if (raiz.nodeType !== 1 && raiz.nodeType !== 9 && raiz.nodeType !== 11) return;
    if (raiz.nodeType === 1) { if (SALTAR.has(raiz.tagName)) return; frase(raiz); atributos(raiz); }
    const caminante = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n;
    while ((n = caminante.nextNode())) {
      if (n.nodeType === 3) nodoTexto(n);
      else { frase(n); atributos(n); }
    }
  }

  const observador = new MutationObserver(cambios => {
    for (const c of cambios) {
      if (c.type === "characterData") nodoTexto(c.target);
      else if (c.type === "attributes") atributos(c.target);
      else c.addedNodes.forEach(recorrer);
    }
  });

  // Ventanas del navegador (alert, confirm, prompt) y título de la pestaña.
  const alertaOriginal = window.alert.bind(window), confirmarOriginal = window.confirm.bind(window),
        preguntarOriginal = window.prompt.bind(window);
  window.alert = m => alertaOriginal(traducir(String(m ?? "")));
  window.confirm = m => confirmarOriginal(traducir(String(m ?? "")));
  window.prompt = (m, v) => preguntarOriginal(traducir(String(m ?? "")), v);

  function empezar() {
    document.title = traducir(document.title);
    recorrer(document.body);
    observador.observe(document.body, { childList: true, subtree: true, characterData: true,
                                        attributes: true, attributeFilter: ATRIBUTOS });
  }
  if (document.body) empezar(); else document.addEventListener("DOMContentLoaded", empezar);
})();

/* Selector de idioma: se pone solo en la barra de arriba del panel y en la pantalla de la contraseña. */
(function () {
  "use strict";
  const datos = window.GESTOR_I18N;
  if (!datos || !datos.idiomas || !datos.idiomas.length) return;

  function crear() {
    if (document.getElementById("gestorIdioma")) return;
    const sel = document.createElement("select");
    sel.id = "gestorIdioma";
    sel.setAttribute("translate", "no");
    sel.title = "🌐";
    sel.setAttribute("aria-label", "Language / Idioma");
    sel.style.cssText = "font:inherit;font-size:13px;color:var(--texto);background:var(--panel);" +
      "border:1px solid var(--borde);border-radius:6px;padding:4px 6px;cursor:pointer;width:auto;min-width:0";
    const auto = document.createElement("option");
    auto.value = "auto";
    auto.textContent = "🌐 " + (datos.nombre_auto || "Auto");
    sel.appendChild(auto);
    for (const [codigo, nombre] of datos.idiomas) {
      const o = document.createElement("option");
      o.value = codigo; o.textContent = nombre;
      sel.appendChild(o);
    }
    sel.value = datos.eleccion || "auto";
    sel.addEventListener("change", async () => {
      try {
        await fetch("/idioma", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify({ idioma: sel.value }) });
      } catch (e) { /* si falla, se recarga igual */ }
      location.reload();
    });
    const barra = document.querySelector("header");
    if (barra) {
      const antes = barra.querySelector("#btnCuaderno") || barra.querySelector("details.mas");
      barra.insertBefore(sel, antes || null);
    } else {
      const caja = document.createElement("div");
      caja.style.cssText = "position:fixed;top:12px;right:12px";
      caja.appendChild(sel);
      document.body.appendChild(caja);
    }
  }
  if (document.body) crear(); else document.addEventListener("DOMContentLoaded", crear);
})();
