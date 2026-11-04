"""GESTOR: adjuntos de Outlook ordenados según quién te los envió.

Cada 15 minutos (si lo activas) mira los correos nuevos de la Bandeja de entrada de Outlook y guarda sus
adjuntos en una carpeta por contacto (Documentos\\Adjuntos\\CFE, ...\\Contador Juan, ...) o en la carpeta
que elijas para cada remitente («cfe.gob.mx» → Documentos\\Casa\\Luz).

Usa Outlook clásico a través de COM (el que viene con Office). El «nuevo Outlook» y WhatsApp no
permiten que otro programa lea quién envió un archivo; los archivos de WhatsApp Desktop se siguen
reconociendo por su nombre con la procedencia «WhatsApp» en las reglas normales.
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time

import bd
import nucleo

CADA_MINUTOS = 15
POR_DEFECTO = {"activo": False, "carpeta": "", "por_contacto": True, "reglas": [], "dias_atras": 30}

SCRIPT = r"""
param([string]$Entrada, [string]$Salida)
$ErrorActionPreference = 'Stop'
$res = @{ adjuntos = @(); error = ''; revisados = 0 }
try {
  $cfg = Get-Content -LiteralPath $Entrada -Encoding UTF8 -Raw | ConvertFrom-Json
  $desde = [DateTime]::Parse($cfg.desde, [Globalization.CultureInfo]::InvariantCulture)
  $vistos = @{}
  foreach ($v in $cfg.vistos) { $vistos[$v] = 1 }
  try { $ol = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
  catch {
    try { $ol = New-Object -ComObject Outlook.Application }
    catch { throw 'No encontré Outlook clásico en este equipo (el «nuevo Outlook» no lo permite).' }
  }
  $items = $ol.GetNamespace('MAPI').GetDefaultFolder(6).Items
  $items.Sort('[ReceivedTime]', $true)
  $n = 0
  foreach ($m in $items) {
    $n++
    if ($n -gt $cfg.maximo) { break }
    if ($m.Class -ne 43) { continue }
    if ($m.ReceivedTime -lt $desde) { break }
    $res.revisados++
    if ($m.Attachments.Count -eq 0) { continue }
    $correo = ''
    try {
      if ($m.SenderEmailType -eq 'EX') { $correo = $m.Sender.GetExchangeUser().PrimarySmtpAddress }
      else { $correo = $m.SenderEmailAddress }
    } catch { }
    for ($i = 1; $i -le $m.Attachments.Count; $i++) {
      $a = $m.Attachments.Item($i)
      if ($a.Type -ne 1) { continue }
      $clave = $m.EntryID + '|' + $i
      if ($vistos.ContainsKey($clave)) { continue }
      $nombre = $a.FileName
      if ($a.Size -lt $cfg.min_bytes -and $nombre -match '\.(png|jpg|jpeg|gif|bmp)$') { continue }
      $destino = Join-Path $cfg.temporal ([string]$res.adjuntos.Count + '_' + $nombre)
      $a.SaveAsFile($destino)
      $res.adjuntos += @{ clave = $clave; nombre = $nombre; archivo = $destino; remitente = [string]$m.SenderName;
                          correo = [string]$correo; asunto = [string]$m.Subject; fecha = $m.ReceivedTime.ToString('s') }
    }
  }
} catch { $res.error = $_.Exception.Message }
[IO.File]::WriteAllText($Salida, ($res | ConvertTo-Json -Depth 4 -Compress), (New-Object Text.UTF8Encoding $false))
"""


def config():
    c = {**POR_DEFECTO, **(nucleo.cargar_ajustes().get("adjuntos_outlook") or {})}
    if not c["carpeta"]:
        c["carpeta"] = os.path.join(nucleo.carpeta_conocida("Documentos"), "Adjuntos")
    return c


def guardar_config(cambios):
    ajustes = nucleo.cargar_ajustes()
    c = {**config(), **{k: v for k, v in cambios.items() if k in POR_DEFECTO}}
    c["reglas"] = [{"remitente": str(r.get("remitente", "")).strip(), "carpeta": str(r.get("carpeta", "")).strip()}
                   for r in c.get("reglas") or [] if str(r.get("remitente", "")).strip()][:100]
    ajustes["adjuntos_outlook"] = c
    nucleo.guardar_ajustes(ajustes)
    return estado()


def estado():
    e = bd.leer("correo:estado", {}) or {}
    return {**config(), "windows": nucleo.ES_WINDOWS, "ultimo": e}


def destino_para(adjunto, c=None):
    """La carpeta donde va un adjunto según su remitente (o None si no se guarda)."""
    c = c or config()
    quien = f'{adjunto.get("correo", "")} {adjunto.get("remitente", "")}'.lower()
    for r in c["reglas"]:
        if r["remitente"].lower() in quien and r["carpeta"]:
            return r["carpeta"]
    if not c["por_contacto"]:
        return None
    contacto = nucleo._limpiar_nombre(adjunto.get("remitente") or (adjunto.get("correo") or "").split("@")[0])
    return os.path.join(c["carpeta"], contacto or "Sin remitente")


def _ejecutar(entrada):
    carpeta = tempfile.mkdtemp(prefix="gestor-correo-")
    rutas = {n: os.path.join(carpeta, n) for n in ("entrada.json", "salida.json", "correo.ps1")}
    entrada["temporal"] = os.path.join(carpeta, "adjuntos")
    os.makedirs(entrada["temporal"])
    with open(rutas["correo.ps1"], "w", encoding="utf-8-sig") as f:
        f.write(SCRIPT)
    with open(rutas["entrada.json"], "w", encoding="utf-8") as f:
        json.dump(entrada, f, ensure_ascii=False)
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                        rutas["correo.ps1"], rutas["entrada.json"], rutas["salida.json"]],
                       timeout=300, creationflags=0x08000000, capture_output=True)
        with open(rutas["salida.json"], encoding="utf-8-sig") as f:
            return json.load(f), carpeta
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        return {"adjuntos": [], "error": f"No se pudo leer Outlook: {e}"}, carpeta


def revisar(forzar=False):
    """Guarda los adjuntos nuevos. Devuelve un resumen."""
    c = config()
    if not c["activo"] and not forzar:
        return {"ok": False, "mensaje": "Desactivado."}
    if not nucleo.ES_WINDOWS:
        return {"ok": False, "mensaje": "Solo funciona en Windows con Outlook."}
    previo = bd.leer("correo:estado", {}) or {}
    if not forzar and time.time() - previo.get("t", 0) < CADA_MINUTOS * 60:
        return {"ok": True, "mensaje": "Revisado hace poco."}
    vistos = bd.leer("correo:vistos", []) or []
    desde = previo.get("hasta") or (dt.datetime.now() - dt.timedelta(days=int(c["dias_atras"] or 30))).isoformat(timespec="seconds")
    inicio = dt.datetime.now() - dt.timedelta(minutes=5)  # margen por correos que llegan mientras se revisa
    res, temporal = _ejecutar({"desde": desde, "vistos": vistos[-3000:], "maximo": 2000, "min_bytes": 20 * 1024})
    ops, guardados = [], 0
    try:
        for a in res.get("adjuntos") or []:
            vistos.append(a["clave"])
            carpeta = destino_para(a, c)
            if not carpeta or not os.path.isfile(a["archivo"]):
                continue
            destino = os.path.join(carpeta, nucleo._limpiar_nombre(os.path.splitext(a["nombre"])[0]) + os.path.splitext(a["nombre"])[1])
            if os.path.exists(destino) and os.path.getsize(destino) == os.path.getsize(a["archivo"]):
                continue  # ya lo tenías
            destino = nucleo._nombre_libre(destino)
            os.makedirs(carpeta, exist_ok=True)
            shutil.move(a["archivo"], destino)
            guardados += 1
            ops.append({"accion": "copiar", "origen": f'Correo de {a.get("remitente") or a.get("correo")}: {a.get("asunto", "")}',
                        "destino": destino, "bytes": os.path.getsize(destino)})
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
    if ops:
        nucleo.indexar({"nombre": "Adjuntos de Outlook"}, ops)
        nucleo.avisar("Adjuntos de Outlook", f"Guardé {guardados} adjunto(s) en sus carpetas.")
    estado_nuevo = {"t": time.time(), "fecha": dt.datetime.now().isoformat(timespec="seconds"),
                    "revisados": res.get("revisados", 0), "guardados": guardados, "error": res.get("error", "")}
    if not res.get("error"):
        estado_nuevo["hasta"] = inicio.isoformat(timespec="seconds")
    elif previo.get("hasta"):
        estado_nuevo["hasta"] = previo["hasta"]
    bd.escribir("correo:estado", estado_nuevo)
    bd.escribir("correo:vistos", vistos[-5000:])
    return {"ok": not res.get("error"), "mensaje": res.get("error") or f"{guardados} adjuntos guardados.", **estado_nuevo}


def mantenimiento():
    if config()["activo"]:
        revisar()
