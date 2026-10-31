# Installation / 安装

Follow the root README commands. Native validation uses macOS arm64, KiCad 10.0.4, CPython 3.13.14 and Cargo 1.98.0. Do not copy an old virtual environment or a precompiled engine from another machine. `build-engine` compiles the bundled Rust source using Cargo.lock and installs the library into this package's KRT directory. The active environment must be writable. Build logs go to the requested build directory.

KiCad is external. The CLI and native Python must come from the same KiCad installation. Default paths are the macOS app bundle. Override them explicitly if needed:

```sh
export PCB_ROUTELAB_KICAD_CLI=/path/to/kicad-cli
export PCB_ROUTELAB_KICAD_PYTHON=/path/to/python-with-pcbnew
.venv/bin/pcb-routelab doctor
```

Python 3.11+ is declared for the package; only the stated release environment has native end-to-end evidence. Linux unit/package CI is not a native routing compatibility claim. Windows is not supported by the POSIX locking/process lifecycle in this release.

Optional Harness dependencies:

```sh
.venv/bin/python -m pip install -r requirements-harness.lock.txt
```

Installing dependencies can access package indexes. Installing or checking dependencies does not call a model provider. `doctor` performs local imports/version checks only. Model mode requires separate explicit configuration and opt-in described in USAGE.

A source distribution contains the fixture, tests and documentation. A wheel contains the CLI and runtime assets; use the repository/source archive for examples and research component scripts. Binary wheels of the native routing engine are intentionally not distributed. To rebuild after installing a new wheel, rerun `build-engine`.
