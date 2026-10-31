# PCB RouteLab

[中文说明](README.zh-CN.md)

PCB RouteLab is a research toolkit for **running, inspecting and comparing PCB routing strategies** on KiCad boards. It packages an existing Harness-based research project into isolated, reproducible jobs.

- Run native routing on a copy of a board and its project rules.
- Inspect native planning observations and execute fixed multi-net order/layer/corridor plans.
- Evaluate bounded congestion-update expressions without executing arbitrary generated code.
- Optionally let DeepSeek Harness orchestrate diagnostic and routing tools.
- Review a separate candidate, a copper change list and a native KiCad acceptance report before export.
- Run in the foreground or background; inspect status and cancel a job.

## Quick start

Native execution is validated on **macOS arm64, KiCad 10.0.4 and Python 3.13**. Install KiCad and a Rust toolchain first. Core operation does not require model configuration.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.lock.txt -r requirements.lock.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/pcb-routelab build-engine --build-dir ../routelab-build
.venv/bin/pcb-routelab doctor
.venv/bin/pcb-routelab run --board examples/two-nets/two-nets.kicad_pcb --output ../routelab-example
.venv/bin/pcb-routelab export ../routelab-example --output ../routelab-export
```

Every output directory must be new. A matching `.kicad_pro` is required; use `--project PATH` when it is elsewhere. Adjacent `.kicad_dru`/legacy `.pro` files are copied and checked. Custom rule programs are currently rejected by the generation contract. The tool does not clear copper or silently simplify unsupported input.

## Supported inputs and results

The release targets modern, two-copper-layer boards with supported ordinary pads, straight tracks and through vias. Zones, copper arcs, custom pads, unstable object identities and legacy imports are rejected. Full details: [support boundary](docs/SUPPORT.md).

`success` means connections improved to completion and the original-rule audit passed. `safe_incomplete` means a verified partial improvement. `no_progress`, `rejected`, `timeout`, `cancelled` and `error` remain distinct. Existing DRC errors may remain; they are reported and compared individually. Success is not manufacturing sign-off. Only accepted improving candidates can be exported, with another audit at export.

## Documentation

- [Installation and native build](docs/INSTALL.md)
- [Routing, planning, policy and model commands](docs/USAGE.md)
- [Scope and limitations](docs/SUPPORT.md)
- [Offline release validation](docs/VALIDATION.md)
- [Research results and reusable components](docs/RESEARCH.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Source attribution](THIRD_PARTY_NOTICES.md)

Examples, aggregate research results and offline release checks are available under `examples/` and `evidence/`.
