# Round 03 reviewed ordinary-branch integration

This is an intermediate integration checkpoint. Main remains at `732e934ba496d90fbe042b8d41d479ef901643e5`. No branch has been deleted and no HIA/Cell ref has been written. Full repository qualification remains incomplete.

## Exact source and ancestry

- Source commit: `f571db956745d0702baba6da800b6c923aed34cc`.
- Source tree: `8b7633e92ff38bbbd6f5b4d1f7449e532f287b4e`.
- Previous integration: `acb0e94275e118b813e400fc52435d7a24e5b645`.
- The source commit has the previous integration as its first parent and 21 individually reviewed ordinary heads as additional parents. It introduces 49 original ancestor commits and changes 210 paths.
- The final inventory contains 7,239 ordinary branch names and 254 protected HIA/Cell names, plus main. The planned ancestry covers 2,029 ordinary names, up from 1,990; 5,210 remain pending. These figures describe the recorded inventory, which may change as other work continues.
- The complete 77,423-node parent graph and a separate walk of the actual created Git commit both exclude all 261 historical/current protected pins. Missing graph parents are rejected. Protected lineage markers and their descendants are excluded even when names differ.
- Final inventory SHA-256: `2c39f4384fbcdd21a3d107966ad942d5d7eb520e4ce8e38592aec67618e6d8e0`.

`source-commit.json`, `integration-plan.json`, `graph-preflight.json` and `local-source-alignment.json` provide the exact identities. The archived original manifests retain the protection snapshot used when each review happened; the complete final batch was subsequently checked against all 261 pins.

## Reviewed changes and evidence scope

| Area | Integration and validation |
| --- | --- |
| Memory terminal reconciliation | Preserve full terminal receipts, reasons, leases and digests in the bounded journal; keep typed HOS2/Notes/Calculator requirements and uncertain-HOS2 quarantine. Scoped Linux memory library: 440 passes, 9 existing ignored cases. The failed initial build attempt is retained. |
| Authorized file reads | Port method/version/kind error metadata and transport regressions while preserving dedicated `-32012` overflow, exact legacy fallback, redaction, capability refusal and encoded/decoded bounds. Linux: 38 selected cases plus 6 compatibility cases, with 2 overlaps, hence 42 distinct passes. Historical macOS collectors and unconditional native assertions remain exact inactive carriers. |
| NDU and causal Neuron research | Compose causal-prefix and frozen-proposal rules with current guards. NDU: 143 passes; Python: 83 passes and 11 optional PyTorch skips. Scoped Neuron: 29 passes, 352 unrelated cases filtered. Retain reproduced depth, mask, nonlinear-budget and temporary-file regressions and their repairs. These research paths do not activate product effects. |
| SDK and build fixtures | Restore exact PR/source checkout binding, retain current cache/cquery behavior, and preserve source-frozen SDK/Wine/Windows harness variants without broadening historical admission. Linux synthetic and syntax checks do not establish Windows, macOS, Wine or Docker qualification. |
| Agentd readback and test scheduling | Preserve serialized initial/outcome assertions and complete old receipts. Four deterministic unit-test shards keep the original per-target timeout and disable retry-based flaky treatment. The shard census is a synthetic launcher proof, not a complete native Agentd rerun. |
| Scope-WAL fixture | Replace a demonstrated same-clock temporary-directory collision with exclusive private directory creation. A real failing control and 111 passing Linux library cases are retained. Production WAL behavior is unchanged. No Windows rerun is claimed. |
| Clock dependency stages 1 and 2 | Migrate reviewed leaf clock uses and remove unused SQLx Chrono support. Leaf baseline/proposed case statuses match, including 29 existing failures; state/thread-store scoped suites have 448 passes. Preserve explicit supported-range and timestamp-format comparisons. |
| OAuth2 time migration | Maintain the real upstream OAuth2 5.0.0 implementation with `time`, preserving explicit numeric-date bounds, negative flooring, duration limits and wasm clock behavior. Public clock/introspection types change. All 75 upstream/boundary cases pass. MCP proposed/control case statuses match: 264 passes, 4 failures and 7 existing skips. This is not a claim that the complete consumer suite passed. |
| Windows clock migration and lock alignment | Use Jiff with exact AutoSi UTC, local millisecond and filename compatibility in the tested range. Portable differential oracle and real rolling-writer/home-path checks pass; 8 added Windows tests await native CI. ACL, token, process, registry and authority behavior are unchanged. |

Each native or synthetic result is bound to its recorded source. Final repository `just fmt` completed with no additional file changes. No tests were rerun after the final fix/format stages. Package fixes, lock generation, byte-equivalence proofs and all limitations are retained in the evidence archive.

The previous full caller-closure result is also preserved: source `df9abe5011a9595a0c5a3bf61b0ced77d10d8fb0`, tree `c46d97b1e6acb237035c715f904d3e591f0a553b`, 1,645 call boundaries, 819 protected files and 7,664 Rust files. It qualifies that earlier source only and is not relabeled as a Round 03 verification.

## Outstanding gates

The stored CI snapshot is for the previous `acb0e9` integration, not this new source. It contains successful format and platform Clippy checks alongside dependency, Linux and Windows failures. The two main required checks must be obtained for the final proposed head before merge; no stored scoped result substitutes for them.

The complete previous native job log is preserved byte-for-byte: 2,672 regular cases passed, with 184 skipped. Its separate explicitly ignored qualification run executed 68 cases: 50 passed and 18 failed. Sixteen resident-root cases returned `InvalidGrant`; two initial-root cases reported retained-lock/cache-unavailable uncertainty. These failures remain unresolved in this checkpoint. Expected panics inside passing tests are not counted as failures.

Chrono is still reachable through RMCP and first-party packages; the advisory gate is not repaired yet. Further RMCP work, the 183f family, broader Windows history and all other pending heads are not accepted by this source commit. No advisory ignore, weaker ACL, widened authority lifetime, retry-based success or branch-history shortcut is introduced.

## Complete original evidence

`evidence-manifest.json` records all 616 archived files, their exact byte counts and SHA-256 values, plus the complete tar and compressed-stream identities. A single deterministic gzip stream is split into ordered parts no larger than 450,000 bytes. The parts are not independent gzip files. Reassembly and every extracted file were verified before publication.

Restore and verify into a new directory:

```sh
python restore_evidence.py --output /tmp/hepta-round03-evidence
```

The archive includes full successful and failed logs, frozen patches and source identities, dependency comparisons, review decisions, current inventories and parent-edge additions. The original full graph is already preserved under the earlier `20261116/graph-and-ci-audit` checkpoint and is referenced by hash. Compilers, build caches, temporary indices and repeated checkout trees are excluded.
