# Troubleshooting / 故障排查

| Symptom | Action |
|---|---|
| `doctor` reports no native tools | Set PCB_ROUTELAB_KICAD_CLI and PCB_ROUTELAB_KICAD_PYTHON to the same KiCad installation. |
| Rust import missing | Run build-engine from the installed virtualenv; inspect its build.log. Rebuild after replacing a wheel. |
| macOS unresolved Python linker symbols | Use the bundled build command and preserved .cargo/config.toml; do not build from a different cwd without that configuration. |
| Missing NumPy/SciPy/Shapely | Install requirements.lock.txt in the interpreter that runs pcb-routelab. |
| Existing output directory | Inspect status/logs. Use a new job directory for an intentional retry; no automatic overwrite/resume occurs. |
| Unsupported zones, pads or legacy format | This input is outside the tested release scope. Do not remove geometry/rules merely to make the check pass. |
| Candidate rejected | Read final-audit/result.json, exact DRC reports and changes. An engine exit code of zero is not acceptance. |
| Potentially capped DRC | Complete validation is unavailable. The run fails closed; this release does not suppress errors to obtain a pass. |
| Cancelled or timed out | Output is not accepted. Keep the run as evidence, inspect process logs, and explicitly start a new job if appropriate. |
| Model disabled | Expected default. Native/probe/joint/policy do not require API access. Tests set PCB_ROUTELAB_OFFLINE=1, which overrides online opt-in. |
| Model credential/provider error | Check private environment configuration yourself. The software does not silently retry or validate a key during doctor. Never post credentials/raw private-board logs in an issue. |
| Plan rejected | Regenerate observation for the exact board and supply its hash-bound plan; do not reuse a plan from another board. |
| Export rejected | Only safe improving candidates are exportable, and the review hashes and native audit must still pass. |

Logs and raw candidate files can contain board design details. GitHub release files are selected by an explicit allowlist; your private job directories are not included automatically.
