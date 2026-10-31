"""Explicit local runtime configuration. Importing this module never connects."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


def assets():
    return Path(__file__).resolve().parent / '_assets'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def configure(work):
    work = Path(work).resolve()
    os.environ['PCB_ASSIST_ROOT'] = str(work)
    os.environ['PCB_ROUTELAB_PYTHON'] = sys.executable
    os.environ['PCB_ROUTELAB_ENGINE'] = str(assets()/'krt/py_router')
    for key in list(os.environ):
        if key.startswith('KICAD_') or key in ('PYTHONHOME', 'DYLD_LIBRARY_PATH'):
            os.environ.pop(key, None)
    for name in ('tmp', 'xdg', 'kicad', 'crashlogs', 'pycache'):
        (work/'cache'/name).mkdir(parents=True, exist_ok=True)
    os.environ.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(work/'cache/tmp'),
        XDG_CACHE_HOME=str(work/'cache/xdg'), KICAD_CONFIG_HOME=str(work/'cache/kicad'),
        KICAD_CRASH_LOG_DIR=str(work/'cache/crashlogs'), OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    code=assets()/'legacy'
    paths=[str(code/'src'),str(code/'scripts'),str(Path(__file__).resolve().parent.parent)]
    os.environ['PYTHONPATH']=os.pathsep.join(paths)
    for p in paths:
        if p not in sys.path:sys.path.insert(0,p)
    return work


def native_tools():
    return {
        'kicad_cli':os.environ.get('PCB_ROUTELAB_KICAD_CLI','/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'),
        'kicad_python':os.environ.get('PCB_ROUTELAB_KICAD_PYTHON','/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3')}
