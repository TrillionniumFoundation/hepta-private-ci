# Ordinary learning integration: original native failures

These records preserve two exact, clean source attempts. This evidence commit does not claim to be their executed source. The source bundles retain the original Git objects; import the 399 bundle after base `106f5e41f2ff8421c5aad10eeb746d453ed00563`, then the 82 bundle after 399. Every archived original has a byte count and SHA256, and extraction was checked against every member digest before this commit.

| Source / tree | Actual result | Test count |
| --- | --- | --- |
| `399ff25830fac9717f1838cc0b07adf107cd847f` / `f4e85bd47779865df29925cbd2b3f5ea53e4b1f5` | Same-source helper build failed: E0271 at `production_initial_q24.rs:151`, a `u64` clock callback where `CircuitCellTimeV1` is required. Cargo exited 101; helper runner exited 1. | 0; no JUnit; ordinary and UID0 suites did not start. |
| `82c895ceb49732ccd7097cde39d1c4da232e8507` / `5e87bab0f30335dc69862b032daca4e32b108776` | Same-source helper build passed. Three-library `just test` then failed during test compilation with ten E0659 diagnostics in `run_start_read_only_frame_tests.rs`, all caused by the child module's ambiguous assertion macro import. | 0; no JUnit; UID0 suite did not start. |

The 399 helper ran from 07:10:54 to 07:12:37 UTC on 2026-11-12. Its complete stderr is 35,318 bytes (`c1a48b58300662978c5f1262a8b7815463ab98a952093798b88cc6670fa7d325`). The 82 helper completed successfully in 103.06 seconds; ordinary compilation ran from 07:27:54 to 07:28:03 UTC. Its complete command log is 38,137 bytes (`c3636fac41b3e4de05d9be366c2f09a4fd0bd0c873b1209e839693624935c938`). The original raw archives contain the complete Cargo JSONL, stderr, commands, source snapshots, helper manifests and runner metadata, including failed outcomes.

Both attempts used actual UID 1000, rustc 1.96.0, cargo-nextest 0.9.151 and just 1.51.0 on the independent `ai395` executor. The requested test policy is zero retries. The 82 command requests the complete Agentd, Agent Protocol and Learning Ledger library suites. The retained 399 plan misspelled the Protocol package as `codex-hepta-protocol`; execution never reached that command. The 82 plan corrects it to the existing `codex-hepta-agent-protocol`. This is a harness correction, not a passed test.

The separately started 399 complete caller scan has no recovered terminal result. Its original manifest and empty log are retained in `harness-and-source.tar.gz`. The cloud execution channel disconnected; resumption failed after 45 seconds. Its status is **unknown**, not PASS and not an assertion failure. No caller scope was removed and the agent did not cancel the scan. A new exact-source durable scan is required for the repaired candidate.

The two archives are `raw-attempt-1.tar.gz`; their adjacent JSON manifests describe the original members. `harness-and-source.tar.gz` retains the actual orchestration script, planned command set and immutable source metadata without reformatting those originals. `files.json` inventories the committed evidence files. The small macro import repair and its following validation have separate source identity and results; none is retroactively applied to these records.

These are component/build records. The complete ordinary positive, NoUpdate and daemon-plus-Root cold-restart acceptance counts remain **0 / 0 / 0**. No independent evaluator or full A-to-C learning qualification is established by these artifacts.
