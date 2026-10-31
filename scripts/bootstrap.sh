#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python_bin="${PCB_ROUTELAB_BOOTSTRAP_PYTHON:-python3.13}"
"$python_bin" -m venv .venv
.venv/bin/python -m pip install -r requirements-build.lock.txt -r requirements.lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/pcb-routelab build-engine --build-dir ../routelab-build
.venv/bin/pcb-routelab doctor
