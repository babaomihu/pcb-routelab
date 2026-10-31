# Usage / 操作

All examples assume `pcb-routelab` is on PATH from the activated virtual environment. Save the disk board first. A job never reads the editor's unsaved buffer.

## Native routing and review

```sh
pcb-routelab run --board project/board.kicad_pcb --output runs/job-001 --seconds 120
pcb-routelab status runs/job-001
pcb-routelab export runs/job-001 --output exported/job-001
```

Optional `--net NAME` and `--rip-net NAME` can be repeated. They select stock router targets/rip candidates; they are **not a local-region permission boundary**. The underlying whole-board router may reconcile other open nets. This release does not promise bounded-region edits. The accepted change list shows actual effects. Original locked copper, pads, layout, rules and existing pad connectivity are checked.

`--options PATH` accepts a JSON object with the inherited bounded options: grid_step, via_cost, heuristic_weight, max_ripup, force_reroute, track_width, via_size and via_drill. Geometry dimensions never override original DRC requirements. Unknown keys are rejected. Engine-generated project files are retained only under `raw/`; candidate/review/export always use the original sidecars and are independently checked against them.

## Background and cancellation

```sh
pcb-routelab run --board project/board.kicad_pcb --output runs/job-002 --background
pcb-routelab status runs/job-002
pcb-routelab cancel runs/job-002
```

Cancellation invalidates delivery from that run. Do not edit or delete its working directory while active. A job is not automatically retried after a crash; inspect its report and logs, then create a new output directory if you intentionally want another run. Engine timeout excludes the additional native preflight/final audit time; the supervisor imposes an outer deadline as well.

## Fixed whole-board plans (offline)

```sh
pcb-routelab run --mode probe --board examples/two-nets/two-nets.kicad_pcb --output runs/probe
pcb-routelab run --mode joint --board examples/two-nets/two-nets.kicad_pcb --output runs/joint \
  --observation runs/probe/observation.json --plan runs/probe/plan.json
```

The probe exports native candidate corridors and an editable neutral plan. `order` must permute every observed net and preserve the native direct-first partition. Assignments select an allowed layer or null, and an observed corridor name or `none`. Hashes bind the plan to its observation and board. Layers/corridors remain soft engine preferences, not hard final copper constraints. Planning generation and plan execution are separate budgeted jobs.

## Congestion policies (offline)

```sh
pcb-routelab run --mode policy --board examples/two-nets/two-nets.kicad_pcb \
  --policy examples/policy-inc.json --output runs/policy
```

`inc` is the native-equivalent baseline. The inherited expression interpreter accepts old, inc, contest, rip, frontier; bounded constants/arithmetic and minimum, maximum, sqrt, log1p. No attributes, arbitrary Python or I/O. Runtime charges must remain finite in [0,1]. `policy-trace.json` records updates/consumption; a simple board may never activate history, which is not proof of a beneficial policy.

## Optional real model mode

This sends board observations to the provider you configure. Only use it with boards you authorize that provider to receive. Credentials remain in environment variables and are not copied into the job configuration.

```sh
export PCB_ROUTELAB_BASE_URL=https://your-provider.example
export PCB_ROUTELAB_MODEL=your-model-id
# Set PCB_ROUTELAB_API_KEY privately in your shell; do not commit it.
unset PCB_ROUTELAB_OFFLINE
pcb-routelab run --mode harness --enable-model --requests 8 --seconds 600 \
  --board project/board.kicad_pcb --output runs/model
```

The provider must implement Anthropic Messages streaming with tool use. Harness uses the diagnostic MCP server; requests are reserved durably and not automatically retried. The inherited session has at most 8 engine actions / 600 engine seconds, further bounded by the outer job deadline. The public request limit is 1–24. `PCB_ROUTELAB_OFFLINE=1` overrides `--enable-model` and blocks provider access. The release acceptance deliberately does not authenticate or contact an external provider. Offline protocol coverage is documented in VALIDATION; live provider compatibility remains dependent on the configured service.
