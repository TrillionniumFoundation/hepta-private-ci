# Chrono retirement: transitive dependency map

The direct-edge inventory in `chrono_lock_audit.py` identifies 36 importers. `chrono_reachability.py` answers the distinct question: **which source-less Cargo.lock packages can reach `chrono` indirectly**, and which external importers must be replaced or have their dependency features changed to eliminate it from the locked graph.

Pinned to Codex HIA predecessor `bbb534d8be9098c041d5f3dd1ca1214fbcc2fd8a`, `codex-rs/Cargo.lock` blob `e1fdaf3fde907d24fec7ea787d49c0e29b3eb4bd`, and workspace `Cargo.toml` blob `145c9b24e7203461337a68cf9938f9f0bce720a9`. An independent exact-blob graph traversal finds **1,530 locked packages, 193 source-less non-vendored root candidates, 121 with a path to chrono, 28 with a direct edge, and 93 with only an indirect path**. Eight immediate importers are external (seven registry, one patched under `third_party`). These categories identify migration and retest scope, not actual binary reachability.

Run with Python 3.11+:

```bash
python -B hia/chrono_reachability.py codex-rs/Cargo.lock > chrono-paths.json
python -B -m unittest discover -s hia/tests -p test_chrono_reachability.py
```

Each root entry includes a shortest deterministic path to chrono. Each external direct importer includes a shortest path from a source-less package if reachable. Duplicate-version edges are resolved by their explicit Cargo.lock version; missing or ambiguous edges fail closed instead of producing invented paths. Patched third-party packages are not classified as workspace roots.

The report deliberately labels all source-less packages **candidates**: the lock graph does not establish Cargo feature activation, exact workspace membership or executed runtime call paths. CI closure still requires a lock without chrono, original `cargo deny`, exact Cargo/Bazel lock regeneration, native/default owner tests, and Linux/macOS/Windows acceptance. This source-only graph tool neither suppresses RUSTSEC-2026-0543 nor qualifies HIA execution or legacy Rust retirement.
