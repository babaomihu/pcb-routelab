# Supported scope / 支持范围

This is a routing research toolkit, not a replacement for an interactive PCB editor or manufacturing review.

- Native tested environment: macOS arm64 and KiCad 10.0.4, with matching CLI/native Python.
- Modern KiCad board serialization (version 20240101 or newer), a supplied `.kicad_pro`, two copper layers, stable unique object UUIDs, ordinary pads and straight copper tracks. Through vias are represented in the native snapshot.
- Zones, copper arcs, custom pads, legacy module format, custom-rule programs and inconsistent generation floors are rejected. No copper stripping, automatic legacy conversion or rule deletion occurs.
- The native validator preserves original pad connected-component membership, locked copper, pad/footprint layout, outline, effective design-rule fields, copper layer count and project/rule sidecars. Candidate admission uses native DRC with all-track errors and original-rule error identity/severity/description comparison. Reports that may have reached the known error-count cap are rejected.
- Existing errors may remain. The exact source/candidate DRC and deltas are retained; warnings are visible but are not treated as new fatal errors. Complete native validation failure prevents candidate acceptance.
- Native job target options do not implement local-region modification permission. This is whole-board experimental routing; review actual changes before export.
- The export command only accepts an improving safe result and revalidates it. It never overwrites an existing destination or merges into an open KiCad editor.
- Original experiment-only PCBWorld coordinate transactions, A2/A4 length-target probes, batch board acquisition and full historical research campaigns are not bundled as runnable product features. Missing backends are not advertised to the model. Their historical presence is not claimed as release capability.
- Plan layers/corridors are soft preferences. An input contract passing does not prove the proposed route is feasible or that the final copper follows every guide.
- The final congestion study selected the native-equivalent `inc` expression. The release provides the mechanism for experiments, not a claimed better learned router.

Changes from research code are recorded in CHANGES. Historical experiment scores describe their original frozen implementations, not a rerun of this release's stronger acceptance checks.
