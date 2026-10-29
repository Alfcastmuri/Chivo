# Doble clic para abrir GESTOR sin consola cuando Python está instalado.
# Alternativa al .exe si el antivirus lo bloquea: así lo ejecuta pythonw.exe, que está firmado.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gestor  # noqa: E402

gestor.main()
