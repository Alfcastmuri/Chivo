"""GESTOR: el panel del celular, solo en redes privadas y cifrado.

- Solo en redes privadas: Windows marca cada red como «Privada» o «Pública». El panel del celular solo
  escucha mientras haya una red privada (o de dominio), y solo atiende conexiones que entran por ella.
  En un café, un aeropuerto o cualquier red pública queda cerrado.
- Cifrado (https): la primera vez se crea un certificado propio de este equipo. Todo lo que viaja entre
  el celular y la PC (la contraseña incluida) va cifrado. Como el certificado lo firma tu propia PC y no
  una empresa, el celular avisa la primera vez; la huella que muestra el panel sirve para comprobar que
  es el tuyo.

GESTOR_REDES="192.168.1.20=Private,10.0.0.5=Public" sustituye la consulta a Windows (pruebas y Linux).
"""

import datetime as dt
import hashlib
import ipaddress
import os
import ssl
import subprocess
import threading
import time

import nucleo

CATEGORIAS_PRIVADAS = ("Private", "DomainAuthenticated")
CACHE_SEGUNDOS = 120
ARCHIVO_CERTIFICADO = os.path.join(nucleo.DATOS, "panel-red.crt")
ARCHIVO_CLAVE = os.path.join(nucleo.DATOS, "panel-red.key")

_cache = {"t": 0.0, "redes": None}
_candado = threading.Lock()

SCRIPT_REDES = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'SilentlyContinue'; "
    "Get-NetConnectionProfile | ForEach-Object { $c = [string]$_.NetworkCategory; $n = $_.Name; "
    "Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 | "
    "ForEach-Object { \"$($_.IPAddress)`t$c`t$n\" } }"
)


def _consultar_windows():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SCRIPT_REDES],
                       capture_output=True, timeout=30, creationflags=0x08000000)
    redes = {}
    for linea in r.stdout.decode("utf-8", "ignore").splitlines():
        partes = linea.strip().split("\t")
        if len(partes) >= 2:
            redes[partes[0]] = {"categoria": partes[1], "nombre": partes[2] if len(partes) > 2 else ""}
    return redes


def redes(forzar=False):
    """{ip de este equipo: {"categoria": "Private" | "Public" | "DomainAuthenticated", "nombre": ...}}."""
    texto = os.environ.get("GESTOR_REDES")
    if texto is not None:
        salida = {}
        for par in filter(None, (p.strip() for p in texto.split(","))):
            ip, _, categoria = par.partition("=")
            salida[ip.strip()] = {"categoria": categoria.strip() or "Public", "nombre": ""}
        return salida
    with _candado:
        if not forzar and _cache["redes"] is not None and time.time() - _cache["t"] < CACHE_SEGUNDOS:
            return _cache["redes"]
        try:
            resultado = _consultar_windows() if nucleo.ES_WINDOWS else {}
        except (OSError, subprocess.SubprocessError):
            resultado = {}
        _cache.update(t=time.time(), redes=resultado)
        return resultado


def ips_privadas(forzar=False):
    """IPs de este equipo en redes que Windows considera privadas, que además son direcciones de red local."""
    salida = []
    for ip, datos in redes(forzar).items():
        try:
            local = ipaddress.ip_address(ip).is_private
        except ValueError:
            continue
        if local and datos.get("categoria") in CATEGORIAS_PRIVADAS:
            salida.append(ip)
    return salida


def ip_permitida(ip_local):
    """¿La conexión entró por una red privada de este equipo?

    Si esa IP no se conoce (acabas de cambiar de red), se vuelve a preguntar a Windows en ese momento, como
    mucho una vez cada 10 segundos.
    """
    if ip_local not in redes() and time.time() - _cache["t"] > 10:
        redes(forzar=True)
    return ip_local in ips_privadas()


def hay_red_privada():
    return bool(ips_privadas())


def ip_para_celular(preferida=None):
    """La IP que se le da al celular: la de la ruta principal si es privada; si no, otra privada."""
    privadas = ips_privadas()
    if preferida in privadas:
        return preferida
    return privadas[0] if privadas else None


# --------------------------------------------------------------------------- cifrado

def cifrado_disponible():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _crear_certificado():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GESTOR (este equipo)"),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GESTOR")])
    ahora = dt.datetime.now(dt.timezone.utc)
    certificado = (x509.CertificateBuilder()
                   .subject_name(nombre).issuer_name(nombre)
                   .public_key(clave.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(ahora - dt.timedelta(days=1))
                   .not_valid_after(ahora + dt.timedelta(days=825))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .sign(clave, hashes.SHA256()))
    clave_pem = clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    descriptor = os.open(ARCHIVO_CLAVE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as f:
        f.write(clave_pem)
    with open(ARCHIVO_CERTIFICADO, "wb") as f:
        f.write(certificado.public_bytes(serialization.Encoding.PEM))


def _certificado_vigente():
    if not (os.path.exists(ARCHIVO_CERTIFICADO) and os.path.exists(ARCHIVO_CLAVE)):
        return False
    try:
        from cryptography import x509
        with open(ARCHIVO_CERTIFICADO, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc) > dt.timedelta(days=30)
    except Exception:
        return False


def asegurar_certificado():
    """Crea el certificado de este equipo si no existe o está por vencer."""
    if not _certificado_vigente():
        _crear_certificado()
    return ARCHIVO_CERTIFICADO, ARCHIVO_CLAVE


def huella():
    """Huella SHA-256 del certificado, como la muestra el navegador del celular (AB:CD:...)."""
    if not os.path.exists(ARCHIVO_CERTIFICADO):
        return ""
    with open(ARCHIVO_CERTIFICADO, "rb") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read().decode("ascii"))
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def contexto_tls():
    certificado, clave = asegurar_certificado()
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.load_cert_chain(certificado, clave)
    return contexto
