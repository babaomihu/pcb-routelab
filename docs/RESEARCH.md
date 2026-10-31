# Research components and historical outcomes

This repository packages execution mechanisms and reusable research code. It does not ship the multi-gigabyte board/response archive or restart past campaigns.

| Historical line | Outcome | Interpretation |
|---|---|---|
| V18–V20 Harness diagnostic scheduling | enhanced 21/48 sessions, native/rule 14/48; 24 families with two repeats | Seven gains began with already-connected but rule-violating candidates. This is not evidence of seven new geometric routing breakthroughs. Family-level sensitivity is weaker than the original session statistic. |
| Local memory repair v0.3 | two formal families stayed at 8 and 3 unconnected items | Execution, neutral branches and rollback were verified; no completion gain in that comparison. |
| Budget scheduling v0.4 | exposed development case 8→7; only eligible new family stayed 1→1 in all arms | Limited development gain, no independent general scheduling benefit shown. |
| Whole-board joint planning | held-out joint 11/14, native four-configuration portfolio 11/14 | Plans were executed, but did not improve held-out legal completion over the stronger baseline. |
| Congestion policy discovery | all selected policies returned to `inc`; held-out 16/17 for all methods/native | No demonstrated deployable cross-family advantage under that interface/protocol. |

These stages use different inputs and protocols; do not compare their percentages as version-by-version progress. `evidence/research-summary.json` provides aggregate source-linked facts without board files. The released validation changes have not been used to recompute these historical scores.

Reusable source in `research/`:

- `memory_planner.py`: serializable failed-action memory and bounded speculative branches.
- `planner_v04.py`: existing cross-target budget scheduling.
- `formal-generators-2026-10-10.py`: fixed numeric/program proposal rules and optional model proposal interface.
- `formal-core-2026-10-10.py`: extracted classification/feedback utilities needed by the generator; historical dataset-specific campaign loops are intentionally not shipped.
- `model-policy-r2-2026-10-11.py`: the corrected streaming receiver, now using the same explicit provider/offline gate as the public package.

These are source-level research APIs, not additional background jobs. Import them after installing the package; the offline tests cover their imports, deterministic proposals and model-access blocking. Execute a selected expression through `pcb-routelab run --mode policy`. The CLI's joint mode accepts a supplied plan; it does not silently run a discovery campaign or claim that a neutral fixture plan came from a model.
