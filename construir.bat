@echo off
rem Construye GESTOR.exe en tu equipo. Necesita Python 3.10 o superior instalado.
cd /d "%~dp0"
set PYINSTALLER_COMPILE_BOOTLOADER=1
python -m pip install --no-binary pyinstaller pyinstaller==6.11.1 || goto error
python -m unittest discover -s tests || goto error
python -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name GESTOR --version-file version_info.txt --add-data "app/panel.html;." --paths app app/gestor.py || goto error
echo.
echo Listo: dist\GESTOR\GESTOR.exe
pause
exit /b 0
:error
echo.
echo Algo fallo. Revisa los mensajes de arriba.
pause
exit /b 1
