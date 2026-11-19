# HCSN physical CPU acceptance on ai395 — 2026-11-06

All three bounded engineering acceptance jobs completed with exit code 0, durable complete output, no timeout, and no automatic retry.

| Backend | Durable job ID | Logical cells | Parameter gradient coverage | Optimizer steps |
| --- | --- | ---: | ---: | ---: |
| value_kernel | 1a1b0be9fe3-fc05-728c | 2 | 172 / 172 | 1 |
| population_grid | 1a1b0bec6eb-fc05-728d | 2 | 8 / 8 | 1 |
| population_age | 1a1b0bf6575-fc05-7291 | 2 | 8 / 8 | 1 |

The actual runtime was Python 3.14.4, Torch 2.9.1+cpu, NumPy 2.3.5 and SciPy 1.17.0, using CPU float64. Each job was launched with a 200% CPU quota, 3 GiB memory limit and 300-second deadline; at most two jobs ran concurrently.

## What was exercised

The configured signed AutomationStore path admitted a real HCSN supervisor and CPU worker. The native test rejected an invalid signature before provider contact, injected a lost first reply, reopened the native authority and SQLite store in a different process, and reconciled the same logical attempt without another provider contact. The worker produced actual candidate, task-gradient receipt and handoff bytes. The verifier validated the complete candidate state and reproduced that state and final prediction exactly from the admitted initial state.

The immutable step receipt preserves its original observation `indeterminate`; successful reconciliation is represented by `state=reconciled` and `final_outcome=succeeded`. The test checks those fields, the terminal digest and complete owner receipt equality after another SQLite reopen. All three cases retained one worker job and zero replay contacts.

This physical helper executes one admitted training block. The separate local three-backend bridge also covered candidate-owner admission and second-block complete-state recovery; that local evidence is not relabelled as a physical second-block run here.

## Exact source and binary identity

- Source base commit: `fcffa43043ec7f36fa680c449c54b9b3446eb6a6`.
- Execution Python source digest: `e5917bf413f416a6491c10ad797f3f8f31e66dc87b1c1f74a4ddb198495cf50c`.
- Deployment package SHA256: `401a43c849525200293a38259bea5c200109994633c8125d8aa1b6ff348e1f11`.
- Deployment manifest SHA256: `a39b337353a9a45720665cd75d0f9d856d9d7ec37cd2c0787a73f1347511f252`.
- Executed stripped native binary SHA256: `2a195957ea1f4f0288ec4af7e00210f96ad78b7283b74da59360aea13494ce46`.
- Native test source SHA256: `dbb7af5257128ea8ab462e3e14c336cd7a9c3127af569da407ddc9b8898c4199`.

The archive includes the external native build linkage, Cargo artifact stream and strip receipt. The deployment verifies their consistency. This does not claim that the native binary was rebuilt on ai395. The signed-worker target does not depend on the neuron crate; native clock and full Agentd qualification have separate gates.

This preservation branch contains evidence based on the source base commit. The tested implementation was the package's preformat source snapshot, including then-uncommitted changes. Neither this evidence-only branch nor a later formatted Git head is thereby established as the exact source used to build the tested binary. The final source head requires an independent CI rebuild and validation.

## Evidence retained

`acceptance-evidence-03.tar.xz` contains 134 regular file members, including all three complete output trees, candidate checkpoints, signed grants/receipts, authority/SQLite recovery state, process incarnations, logs, source snapshots, the file manifest, and native build/strip/deployment receipts.

- Archive bytes: 120344.
- Archive SHA256: `afbed582ff0d56510085faf82c0c7ae92282dda40611b29ca9ceacacb5789648`.
- Archive Git blob SHA: `ffcffcce3290297178f32ae3117294993154e211`, independently matched with `git hash-object --no-filters` on ai395.
- Evidence file-manifest SHA256: `13e95c178897656002ca792b6c16f467e14f41597e56d88b649b4214c40f265e`.

The original archive and package remain in the isolated remote task directory. This Git preservation was necessary after the local execution environment became unavailable during evidence collection. No training job was repeated because of that outage. The first collection-only attempt used an incorrect manifest path prefix and stopped before writing an archive; its failure and the corrected collection attempt are retained.

## Scope

The authority profile is `synthetic_ed25519_v1` with a synthetic test key. Every result states `host_registration_exercised=false`, `production=false`, `production_trust=false`, `production_adoption=false` and `candidate_only=true`. This is CPU engineering qualification, not production PQ registration, scientific benefit, energy measurement, or a CUDA campaign. The existing desktop CUDA campaign was not contacted or changed.
