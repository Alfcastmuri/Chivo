"""Selector de carpetas nativo de Windows sin tkinter (tkinter en el .exe necesita Tcl y puede romper el arranque)."""

import ctypes
import os
import sys


def elegir(titulo="Elige una carpeta para GESTOR", inicial=""):
    """Devuelve la carpeta elegida o "" si se cancela. Solo Windows; en otros sistemas usa tkinter (desarrollo)."""
    if sys.platform != "win32":
        import tkinter as tk
        from tkinter import filedialog
        raiz = tk.Tk()
        raiz.withdraw()
        ruta = filedialog.askdirectory(title=titulo, initialdir=inicial or None, mustexist=True)
        raiz.destroy()
        return ruta or ""

    from ctypes import wintypes
    shell32, ole32, user32 = ctypes.windll.shell32, ctypes.windll.ole32, ctypes.windll.user32
    BFFCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                    ("ulFlags", wintypes.UINT), ("lpfn", BFFCALLBACK), ("lParam", wintypes.LPARAM),
                    ("iImage", ctypes.c_int)]

    BFFM_INITIALIZED, BFFM_SETSELECTIONW = 1, 0x400 + 103
    inicial_buf = ctypes.create_unicode_buffer(inicial if inicial and os.path.isdir(inicial) else "")

    @BFFCALLBACK
    def al_abrir(hwnd, msg, lparam, data):
        if msg == BFFM_INITIALIZED:
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)       # siempre encima
            if inicial_buf.value:
                user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1, ctypes.addressof(inicial_buf))
        return 0

    ole32.CoInitialize(None)
    nombre = ctypes.create_unicode_buffer(260)
    info = BROWSEINFOW(None, None, ctypes.cast(nombre, wintypes.LPWSTR), titulo,
                       0x0001 | 0x0040, al_abrir, 0, 0)   # solo carpetas del sistema de archivos, diálogo moderno
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return ""
    ruta = ctypes.create_unicode_buffer(32768)
    ok = shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), ruta)
    ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return ruta.value if ok else ""
