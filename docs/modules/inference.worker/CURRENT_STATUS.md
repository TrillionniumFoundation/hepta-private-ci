# inference.worker current status and evidence

This module exposes three different capability ceilings. They must not be collapsed into one generic “worker complete” claim.

| Surface | Repository status | Claim ceiling |
| --- | --- | --- |
| `HostedAppServerWorker` | production candidate | May claim exact App Server provider execution observed through the durable native journal. It does not claim local weights, target-host qualification, activation, promotion or release. |
| `LocalModelWorker` | experimental / non-production | Available only with `local-model-experimental`. It requires verified grants, artifact/device attestation, aggregate resource accounting and durable no-replay coordination. No production caller may treat an injected driver or fixture as real-model proof. |
| `LegacyReceiptBoundary` | validation only | Validates existing request/lease/reservation tuples and emits deny-all receipts. It does not prove that a provider or local model executed. |

## Exact qualification artifact

`.github/workflows/inference-worker-qualification.yml` runs exact source-head and deterministic synthetic-merge qualification. After all owner jobs finish, `scripts/hepta-inference-worker-status.py` emits `CURRENT_STATUS.json` as a workflow artifact. The generated record includes:

- source commit, tree and mapped blob identities;
- exact-head and merge-candidate run identity and result;
- Linux and macOS results;
- library, binary and strict Clippy results;
- explicit external-gate states for real hardware, product composition and independent acceptance;
- reconciliation status separated into exact App Server history, missing-history resolution, trusted usage resolution and target-host qualification.

The generated artifact is authoritative only for the exact workflow run that produced it. A tracked JSON file cannot contain the hash of the commit that contains itself, so the repository tracks the generator and qualification workflow rather than a stale self-referential receipt.

## Reconciliation truth

- Exact App Server `thread/read` recovery for the original durable dispatch is implemented and never creates another `turn/start`.
- Missing App Server history can be resolved only through the independently verified provider-receipt port in `native_recovery`; repository code cannot manufacture that receipt.
- A terminal event with missing trusted token usage remains `UsagePending`; missing usage is never encoded as zero.
- Real-provider retention, deployed receipt authority, target-host identity, trusted time, key custody, revocation distribution, hardware fault qualification and independent acceptance remain external evidence gates.

## Documents

- [`TECHNICAL.md`](TECHNICAL.md): stable module design and ownership guide.
- [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json): source navigation and claim boundary.
- [`../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md`](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md): final-use authority semantics.
- [`../../../codex-rs/hepta-infer-worker-host/NATIVE_RECOVERY_RUNBOOK.md`](../../../codex-rs/hepta-infer-worker-host/NATIVE_RECOVERY_RUNBOOK.md): indeterminate recovery and operator actions.
- [`../../../codex-rs/hepta-infer-worker-host/LOCAL_MODEL_EXPERIMENTAL.md`](../../../codex-rs/hepta-infer-worker-host/LOCAL_MODEL_EXPERIMENTAL.md): experimental local-model contract and non-production ceiling.
