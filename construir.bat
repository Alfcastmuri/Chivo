@echo off
rem Construye GESTOR.exe en tu equipo. Necesita Python 3.10 o superior instalado.
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller || goto error
python -m unittest discover -s tests || goto error
python -m PyInstaller --noconfirm --clean --onedir --windowed --name GESTOR --add-data "app/panel.html;." --paths app app/gestor.py || goto error
echo.
echo Listo: dist\GESTOR\GESTOR.exe
pause
exit /b 0
:error
echo.
echo Algo fallo. Revisa los mensajes de arriba.
pause
exit /b 1
