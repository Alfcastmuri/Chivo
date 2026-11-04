"""GESTOR: leer el texto de fotos y PDF escaneados (OCR) con el lector que ya trae Windows 10/11.

No hay que instalar nada ni hace falta internet: se usa Windows.Media.Ocr desde PowerShell.
Lo leído se guarda en gestor.db (tabla «textos»), así que cada archivo se lee una sola vez.
Con ese texto funcionan igual las reglas por contenido, los vencimientos y los recordatorios de pago:
un recibo fotografiado se ordena igual que un PDF.
"""

import json
import os
import subprocess
import tempfile
import time

import bd
import nucleo

EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif"}
MIN_BYTES = 15 * 1024          # iconos y miniaturas: no tienen texto que valga la pena
MAX_BYTES = 40 * 1024 * 1024
MIN_TEXTO_PDF = 40             # un PDF con menos letras que esto probablemente es escaneado

SCRIPT = r"""
param([string]$Entrada, [string]$Salida)
$ErrorActionPreference = 'Stop'
$res = @{}
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $metodos = [System.WindowsRuntimeSystemExtensions].GetMethods()
  $asTaskOp = $metodos | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
  $asTaskAc = $metodos | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
  function Esperar($op, [Type]$tipo) { $t = $asTaskOp.MakeGenericMethod($tipo).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
  function EsperarAccion($ac) { $t = $asTaskAc.Invoke($null, @($ac)); $t.Wait(-1) | Out-Null }
  [void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
  [void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
  [void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
  [void][Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
  [void][Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
  $motor = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if (-not $motor) {
    $idioma = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object -First 1
    if ($idioma) { $motor = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($idioma) }
  }
  if (-not $motor) { throw 'Windows no tiene ningun idioma de OCR instalado.' }
  $max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension

  function LeerImagen($stream) {
    $dec = Esperar ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $f = [Math]::Min(1.0, $max / [Math]::Max($dec.PixelWidth, $dec.PixelHeight))
    $tr = New-Object Windows.Graphics.Imaging.BitmapTransform
    $tr.ScaledWidth = [uint32][Math]::Max(1, [Math]::Floor($dec.PixelWidth * $f))
    $tr.ScaledHeight = [uint32][Math]::Max(1, [Math]::Floor($dec.PixelHeight * $f))
    $bmp = Esperar ($dec.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
      [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $tr,
      [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
      [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $r = Esperar ($motor.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $bmp.Dispose()
    (($r.Lines | ForEach-Object { $_.Text }) -join "`n")
  }

  $rutas = Get-Content -LiteralPath $Entrada -Encoding UTF8 -Raw | ConvertFrom-Json
  foreach ($ruta in $rutas) {
    try {
      $archivo = Esperar ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ruta)) ([Windows.Storage.StorageFile])
      if ($ruta.ToLower().EndsWith('.pdf')) {
        $doc = Esperar ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($archivo)) ([Windows.Data.Pdf.PdfDocument])
        $partes = @()
        for ($i = 0; $i -lt [Math]::Min(3, $doc.PageCount); $i++) {
          $pag = $doc.GetPage($i)
          $ms = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
          $op = New-Object Windows.Data.Pdf.PdfPageRenderOptions
          $op.DestinationWidth = [uint32]1800
          EsperarAccion ($pag.RenderToStreamAsync($ms, $op))
          $partes += (LeerImagen $ms)
          $ms.Dispose(); $pag.Dispose()
        }
        $res[$ruta] = ($partes -join "`n")
      } else {
        $st = Esperar ($archivo.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $res[$ruta] = (LeerImagen $st)
        $st.Dispose()
      }
    } catch { $res[$ruta] = '' }
  }
} catch { $res['_error'] = $_.Exception.Message }
[IO.File]::WriteAllText($Salida, ($res | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
"""


def activo():
    return nucleo.ES_WINDOWS and nucleo.cargar_ajustes().get("ocr", True) and not _no_disponible()


def _no_disponible():
    """Si Windows dijo que no puede (sin idiomas de OCR), no se vuelve a intentar en un día."""
    e = bd.leer("ocr:error", None)
    return bool(e) and time.time() - e.get("t", 0) < 86400


def estado():
    e = bd.leer("ocr:error", None) or {}
    return {"activo": bool(nucleo.cargar_ajustes().get("ocr", True)), "windows": nucleo.ES_WINDOWS,
            "error": e.get("mensaje", "") if _no_disponible() else "",
            "leidos": bd.con().execute("SELECT COUNT(*) FROM textos WHERE texto<>''").fetchone()[0]}


def candidato(ruta):
    ext = os.path.splitext(ruta)[1].lower()
    if ext not in EXT_IMAGEN and ext != ".pdf":
        return False
    try:
        tam = os.path.getsize(ruta)
    except OSError:
        return False
    return MIN_BYTES <= tam <= MAX_BYTES if ext in EXT_IMAGEN else tam <= MAX_BYTES


def _mtime(ruta):
    try:
        return os.path.getmtime(ruta)
    except OSError:
        return None


def guardado(ruta):
    m = _mtime(ruta)
    return None if m is None else bd.texto_guardado(ruta, m)


def leer_lote(rutas, segundos=180):
    """Lee varios archivos con un solo PowerShell (arrancarlo cuesta un par de segundos)."""
    pendientes = [os.path.abspath(r) for r in dict.fromkeys(rutas) if candidato(r) and guardado(r) is None]
    if not pendientes or not activo():
        return 0
    carpeta = tempfile.mkdtemp(prefix="gestor-ocr-")
    entrada, salida, script = (os.path.join(carpeta, n) for n in ("entrada.json", "salida.json", "ocr.ps1"))
    try:
        with open(script, "w", encoding="utf-8-sig") as f:
            f.write(SCRIPT)
        with open(entrada, "w", encoding="utf-8") as f:
            json.dump(pendientes, f, ensure_ascii=False)
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", script, entrada, salida], timeout=segundos,
                           creationflags=0x08000000, capture_output=True)
        except (subprocess.TimeoutExpired, OSError):
            return 0
        try:
            with open(salida, encoding="utf-8-sig") as f:
                res = json.load(f) or {}
        except (OSError, ValueError):
            return 0
        if res.get("_error"):
            bd.escribir("ocr:error", {"t": time.time(), "mensaje": res["_error"]})
            return 0
        bd.borrar("ocr:error")
        hechos = 0
        for ruta in pendientes:
            if ruta in res:
                m = _mtime(ruta)
                if m is not None:
                    bd.guardar_texto(ruta, m, (res.get(ruta) or "")[:nucleo.MAX_CARACTERES])
                    hechos += 1
        return hechos
    finally:
        for n in (entrada, salida, script):
            try:
                os.remove(n)
            except OSError:
                pass
        try:
            os.rmdir(carpeta)
        except OSError:
            pass


def texto(ruta):
    """El texto de una foto o de un PDF escaneado ("" si no tiene o no se pudo leer)."""
    ruta = os.path.abspath(ruta)
    t = guardado(ruta)
    if t is None and candidato(ruta) and activo():
        leer_lote([ruta], segundos=60)
        t = guardado(ruta)
    return t or ""
