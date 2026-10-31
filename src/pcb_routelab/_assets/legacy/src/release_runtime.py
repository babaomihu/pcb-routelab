import os, sys
from pathlib import Path
CODE=Path(__file__).resolve().parents[1]
ASSETS=CODE.parent
WORK=Path(os.environ.get('PCB_ASSIST_ROOT', '.')).resolve()
ENGINE=Path(os.environ.get('PCB_ROUTELAB_ENGINE', str(ASSETS/'krt/py_router'))).resolve()
ENGINE_PYTHON=Path(os.environ.get('PCB_ROUTELAB_PYTHON', sys.executable)).absolute()
KICAD_PYTHON=Path(os.environ.get('PCB_ROUTELAB_KICAD_PYTHON', '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3'))
KICAD_CLI=Path(os.environ.get('PCB_ROUTELAB_KICAD_CLI', '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'))
