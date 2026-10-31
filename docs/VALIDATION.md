# Offline release validation

Release acceptance never calls an external model API or validates provider credentials. Optional SDK construction is checked without starting a model session. Actual MCP tools are exercised over stdio by a scripted caller. This verifies the tool protocol and execution path, not model decisions or live provider compatibility.

Run the same checks from a source checkout after installation/build:

```sh
export PCB_ROUTELAB_OFFLINE=1
python -m unittest discover -s tests -v
python scripts/validate_mcp.py --board examples/two-nets/two-nets.kicad_pcb --output ../mcp-check
python scripts/validate_failures.py --board examples/two-nets/two-nets.kicad_pcb --output ../failure-check
pcb-routelab run --board examples/two-nets/two-nets.kicad_pcb --output ../native-check
python scripts/validate_native_guards.py --example examples/two-nets/two-nets.kicad_pcb --accepted ../native-check --output ../native-guard-check
python scripts/audit_release.py
```

Each output must be new. Native/probe/joint/policy, export, unsupported-input rejection, timeout, background cancellation, same-net connection regression and rule tampering are checked. The example is synthetic and identifies mechanism tests only; no historical difficult task is replaced or counted as repaired.

`evidence/release-validation.json` records completed release checks. `evidence/research-summary.json` contains historical aggregate research results, which are a separate evidence category. No model-efficacy rerun is implied by these release tests. GitHub CI runs offline Python and packaging checks; the native KiCad evidence comes from the recorded macOS environment.

Source sealing is an explicit maintainer operation (`scripts/seal_release.py`); normal users run the read-only audit. Public source and package hashes distinguish this release from the untouched research archive.

Release 0.1.0 passed 18 offline unit tests in a fresh installed-wheel environment, a fresh locked Rust build, native example routing (2 → 0 unconnected), actual stdio MCP execution, candidate revalidation/export and an already-connected input (0 → 0, reported as `no_progress`, export denied). Native same-net connection swaps and relaxed rule sidecars were rejected. The fresh environment and build directories included spaces. External model API calls: **0**.
