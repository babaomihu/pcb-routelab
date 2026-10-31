# Release engineering changes

Version 0.1.0 extracts the V20 diagnostic/session modules, existing joint-planning adapter, congestion expression interpreter and reusable planner/generator components. No path search, rip-up heuristic or congestion policy is newly designed here.

Release repairs:

1. Immutable code/runtime assets separated from per-job writable state; no imports from the author's desktop or old virtual environments.
2. Explicit Python/KiCad paths; the active virtualenv interpreter is preserved without resolving its executable symlink to a different environment.
3. Full source build of Rust extension, Cargo.lock and preserved macOS dynamic-lookup link configuration.
4. Model provider configuration via environment, explicit opt-in, offline override and request caps. SSE relay stops at the protocol terminal event instead of waiting for transport EOF.
5. Original-rule generation floor contract reused across public/native and Harness paths. Raw engine project changes are retained as evidence but never delivered as the accepted rule set.
6. Native acceptance additionally protects connected pad groups, locked copper and layer count; worsening a DRC item description cannot be hidden behind unchanged error counts. Potentially capped reports fail closed.
7. New independent CLI output/status/export lifecycle, cancellation and timeouts; export re-audits improving candidates. Original board and sidecars are hashed before/after.
8. Model tool listing excludes unbundled experimental backends. The protocol helper retains only its required schema/validation/storage functions.
9. Source allowlist, provenance, dependency locks, licenses, installation docs, compact evidence and offline CI added.

Failures during release validation are preserved outside the public source directory in the local acceptance workspace. They include a missing macOS linker configuration, virtualenv path resolution, and a protocol-helper import omission; subsequent regressions cover the repaired paths. No failed algorithm run was rewritten as a success.
