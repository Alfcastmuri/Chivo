# Instala en tu PC la versión de la Microsoft Store de GESTOR, sin firmar, para probarla antes de enviarla.
# Necesita el «Modo de desarrollador» de Windows (Configuración › Sistema › Para programadores).
#   Abre «Probar GESTOR de la Store.bat» (o este archivo con clic derecho › Ejecutar con PowerShell).
#   Para quitarla:  Probar GESTOR de la Store.bat -Quitar

param([switch]$Quitar)
$ErrorActionPreference = 'Stop'
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifiesto = Join-Path $aqui 'paquete\AppxManifest.xml'
$nombre = ([xml](Get-Content -LiteralPath $manifiesto -Encoding UTF8)).Package.Identity.Name

function Pausa { Write-Host ''; Read-Host 'Pulsa Enter para cerrar' | Out-Null }

$previo = Get-AppxPackage -Name $nombre -ErrorAction SilentlyContinue
if ($Quitar) {
  if ($previo) { $previo | Remove-AppxPackage; Write-Host 'Quitada la versión de prueba de la Store. Tus datos siguen en %APPDATA%\GESTOR.' }
  else { Write-Host 'No estaba instalada.' }
  Pausa; exit 0
}

$dev = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -ErrorAction SilentlyContinue
if (-not $dev -or $dev.AllowDevelopmentWithoutDevLicense -ne 1) {
  Write-Host 'Falta activar el Modo de desarrollador. Te abro la página: activa «Modo de desarrollador» y vuelve a abrir esto.'
  Start-Process 'ms-settings:developers'
  Pausa; exit 1
}

# La versión normal (la del instalador) y la de la Store no deben ordenar a la vez: se quita la tarea
# programada de la normal. Tus servicios y datos se conservan y la versión de la Store los usa.
$normal = Join-Path $env:LOCALAPPDATA 'Programs\GESTOR\GESTOR.exe'
if (Test-Path $normal) {
  Write-Host 'Pausando la versión normal de GESTOR (se quita su tarea programada; tus datos se quedan)...'
  Start-Process -FilePath $normal -ArgumentList '--desinstalar' -Wait -WindowStyle Hidden
}

if ($previo) { $previo | Remove-AppxPackage }
Add-AppxPackage -Register $manifiesto
Write-Host ''
Write-Host 'Listo: «GESTOR» de la Store está en el menú Inicio. Ábrelo desde ahí.'
Write-Host 'Para volver a la versión normal: quita esta con -Quitar y elige «Reiniciar los servicios»'
Write-Host 'en GESTOR - Herramientas (menú Inicio).'
Pausa
