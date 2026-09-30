# cognitive.store current architecture

```yaml
asOfCommit: IMPLEMENTATION_MAP.json#sourceBindingSnapshot.commit
implementationState: source_present_execution_pending
lastQualifiedCommit: null
lastQualificationRun: null
targetHostState: external_evidence_pending
knownRegressions:
  - CS-REC-FENCE-001: source_fixed_execution_pending
```

This is the sole short-form description of the current implementation. Historical goals and alternatives belong in ADRs and the longer technical documents. Source presence in this file is not compilation, qualification, selected-host acceptance, activation, or release.

## Current owner and capability boundaries

| Boundary | Current type | Authority |
|---|---|---|
| Pure in-memory qualification model | `InMemoryCognitiveModel` | No production authority |
| Durable read surface | `DurableCognitiveReadCapability` | Read, page, retrieval observation, revalidation, federation status/list |
| Federation policy surface | `FederationPolicyCapability` | Named-host-only grant/revoke; no Memory mutation or raw owner escape |
| Semantic production mutation | `ProductionMutationCapability` | Sealed semantic remember/correct/forget operations |
| Product writer host | `AgentdProductionWriterHost` | Exact recovered generation plus retained live authority verifier |
| Physical SQLite owner | `codex_hepta_memory::CognitiveStore` | Internal physical implementation; full private-crate isolation is not yet complete |

`DurableCognitiveReadStore` and `CognitiveStore` remain compatibility spellings. New code should use the capability/model names above so reviews and diagnostics cannot confuse the in-memory model, read surface, policy surface, and physical owner.

Agentd privately composes the read and federation-policy capabilities over the same already-open owner. The public read capability contains no federation grant/revoke methods. The policy capability is absent from the default semantic-crate feature profile. CI API probes compile all three profiles and require attempts to grant, revoke, or semantically mutate through the read capability to fail for the expected Rust visibility/method reason.

## Writable recovery and admission

The current source path is:

```text
independently authenticated exact current cut
  -> exclusive store fence
  -> descriptor-retained private generation copy
  -> schema/state/integrity verification
  -> checkpoint + file/directory durability
  -> reopen and exact-cut revalidation
  -> final live authority verification
  -> active-pointer publication
  -> live-authority-bound production writer
  -> sealed production mutation capability
```

A failed writer admission must close the recovered SQLx pool before the exclusive recovery fence is released. `CS-REC-FENCE-001` has a source fix and a real-SQLite regression, but remains merge-blocking until the exact candidate compiles and both repository qualification lanes succeed in one coherent attempt.

The source does not yet expose every transition as a public typestate value. `AuthenticatedCurrentCut`, `RecoveredExactGeneration`, and `ExclusivelyFencedGeneration` remain design names rather than independently constructible public types. The final writer and mutation capability are explicit types; further typestate conversion must not weaken the current fail-closed checks.

## Qualification truth

Only the dedicated read-only workflow may create execution evidence. It must run the exact source head and one deterministic ordered-parent base merge. The required aggregate fails when either lane is absent, skipped, non-terminal, red, bound to another commit/tree, or assembled from another run/attempt. `action_required`, zero-job, artifact-only, and pending runs are not success.

Source is committed as an ordinary Git diff. Qualification workflows do not delete themselves, rewrite source, commit, or push. The source snapshot and the separately committed `IMPLEMENTATION_MAP.json` binding form one candidate identity; the map cannot make an unexecuted source qualified.

## Current capability matrix

| Capability | Source exists | Exact head passed | Deterministic merge passed | Selected host passed | Released |
|---|---:|---:|---:|---:|---:|
| Semantic mutation | yes | no | no | no | no |
| Writable recovery | yes | no | no | no | no |
| Durable read | yes | no | no | no | no |
| Federation policy / live revocation | yes | no | no | no | no |
| Archive / restore | yes | no | no | no | no |
| Physical deletion | no | no | no | no | no |
| Model or parameter unlearning | no | no | no | no | no |

The machine source of this matrix is `READINESS.json`; per-operation five-dimensional state is `OPERATION_STATUS.json`.

## External trust and lifecycle boundary

Repository source cannot self-issue the independent signer, a current-cut witness outside the rollback domain, commit-to-witness reconciliation, selected-host filesystem fault receipts, operator acceptance, or release approval. Likewise, tombstones, archives, lifecycle receipts, and retention readiness do not prove hot-row pruning, backup/derived-artifact erasure, third-party deletion, or model unlearning.
