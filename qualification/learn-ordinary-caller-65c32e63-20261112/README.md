# Completed source gates for the fixture-scope repair

These are original source-level gates, with their exact source snapshots. No native test or whole-chain outcome is inferred.

| Exact source | Complete command scope | Observed result |
| --- | --- | --- |
| `65c32e639e99912fc5a437afe5dd128271ec05ae`, tree `ae158ee0f2e611a6b9fd5f01e07728102811dd17` | `python3 scripts/verify_hepta_callers.py verify --root <frozen checkout>` | Exit 0 in 701.311972598 s; 6,885 Rust files, 1,104 boundaries, 1,104 privileged inventory entries, 870 protected files; source unchanged |
| Same exact65 tree | Initial complete ordinary-callers QA file | Exit 1; five failing fixture subtests in four methods; original output preserved |
| Same exact65 tree | Complete file-test-cfg QA file | 5 / 5 pass; source unchanged |
| `31a67f4782d5279034d4c90786d3b944d5da629d`, tree `c6b3a1a7cc5471bab3c8afc9782ea338dfc6afed` | Actual in-repository complete ordinary-callers QA file | 4 / 4 pass in 20.392943545 s; source unchanged |
| Same exact31 tree | Complete file-test-cfg QA file | 5 / 5 pass; source unchanged |

The exact65 driver as a whole exits 1 because its initial QA failure is retained. Its full caller CLI is independently a real PASS, not a timeout, selected-boundary scan, self-test or inferred result. The caller receipt reports `authorityGranted=false`.

Five pre-existing helper files are used solely under actual `#[cfg(test)]` parent module chains. Exact65 adds explicit file-level `#![cfg(test)]`; every original Rust byte is otherwise unchanged. It adds negative controls for removing, commenting or widening that condition. The first negative-control implementation omitted authority fields found by the complete CLI and failed. Exact31 only derives those actual fields from the original complete Rust source index and supplies them to the unchanged verifier. All omission, unknown-caller and cfg-mutant checks remain.

The original full exact32 QA and caller failures, the exact33 caller failure and source bundles are retained in earlier evidence commits. Source bundles for 65 and 31 are in immutable commit `39c0f8205fb068c7e297b163b90b9fee52b4e44a`, under `qualification/learn-ordinary-caller-33a5a338-20261112/`.

The archive roundtrips all 30 files / 594,817 input bytes, including failed and successful QA logs, the full 530,550-byte caller receipt, both actual drivers and before/after source hashes. Full CLI PASS remains bound to exact65. The later integrated a0 source gate is a separate execution and is not covered by this receipt. Whole Adopt / evaluated post-B NoUpdate / cold-recovery counts remain 0 / 0 / 0.
