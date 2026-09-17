# cognitive.read production status

This note is the machine-adjacent status companion to `TECHNICAL.md`. It separates source implementation, product composition, and qualification so that a single `productionImplementation` Boolean is not asked to represent all three claims.

## Status

| Dimension | State | Repository evidence |
| --- | --- | --- |
| Implemented | **yes** | `codex-rs/hepta-cognitive-read`, `DurableCognitiveSnapshot`, SQLite Lane C projection and V2 bounded reads exist. |
| Composed | **yes** | Agentd reads the canonical Lane C cut and the native infer worker attaches the resulting context to the actual App Server model turn. |
| Qualified | **no** | Repository tests and readiness evidence exist, but independent acceptance / activation / release remain separate gates. |

`implemented` means source exists and the owner-bound behavior is represented in code. `composed` means an authenticated product caller reaches that source on the normal runtime path. `qualified` is deliberately stricter: it requires the repository and external acceptance gates named by the module dossier/readiness process. These dimensions must not be collapsed back into one Boolean.

## Canonical production authority path

The production runtime authority path is:

`CognitiveStore::lane_c_snapshot` → `DurableCognitiveSnapshot::read(ReadRequestV2)` → Agentd cognitive-context admission/revalidation → infer-worker final owner re-read → App Server `TurnStart`.

`DurableCognitiveSnapshot` is a read-only observed historical cut. It does not grant writer authority and it is not a future freshness or revocation lease.

`AuthoritativeCognitiveSnapshotProvider` in `hepta-cognitive-read/src/authoritative.rs` remains a conformance/qualification abstraction for callers that already possess one externally frozen full `LaneCGenerationVectorV1`. The current product host does not manufacture the model/template/tool/prompt portions of that vector merely to satisfy the abstraction. Runtime authority therefore remains in the durable owner API instead of being duplicated in a second provider implementation.

This is an intentional convergence decision: production freshness/revocation semantics live in the durable owner path; the provider abstraction must not evolve a parallel set of product semantics. If a future host can supply the complete external Lane C vector, it may adapt the durable cut into `AuthoritativeSnapshotV1` with `bind_context`, but doing so must not bypass the same owner revalidation used by Agentd.

## Final model-dispatch freshness gate

Agentd already reacquires/revalidates the Lane C snapshot before it publishes `CognitiveContextSnapshot`. That response is still only an observed cut. The native infer worker therefore performs a second owner read immediately before its durable dispatch marker and `TurnStart`.

The final gate compares:

- `snapshot_digest`;
- `read_digest`;
- omitted-record count;
- exact admitted items, including memory id, revision, content and content digest; and
- the current `read_allowed` decision.

Any mismatch fails closed before `dispatch_native` and before the model turn begins. The second response is produced through the same Agentd path, so it includes Agentd's existing durable-cut revalidation rather than a duplicated host-side SQLite check.

Plan receipt digests are intentionally not required to be byte-identical across the two observations because the planning receipt contains observation-time material. A changed allow/deny decision, snapshot/read receipt, or admitted item is authoritative for the gate and is rejected.

No freshness lease is claimed. The invariant is that the final owner observation is the last authority-bearing operation before the effect boundary; later long-running owner loss is separately handled by the native worker's existing generation/health monitoring.

## Race regression

Two layers jointly cover the historical-cut race:

1. Agentd's cognitive-context tests create real canonical memory, read it, commit a tombstone and prove the next owner read removes the old item and changes the snapshot receipt.
2. The native-host regression proves that a post-response tombstone / revision-content change causes the final gate to reject before `TurnStart`, including a defense-in-depth case where receipt strings are incorrectly reused but exact item revision/content changed.

Together these tests cover the seam that was previously missing: a context that was valid when Agentd first returned it cannot silently cross the final host dispatch boundary after the owner has observed a conflicting cut.

## Implementation-map source identity

`IMPLEMENTATION_MAP.json` carries a scoped evidence-input list and a generated evidence-tree digest. The implementation-map verifier recomputes that digest from the checked-out file contents. A change to any bound owner implementation, product caller, regression test, technical/status document, or dossier therefore makes the map stale even when its JSON shape remains valid.

This scoped evidence tree is intentionally stronger for module truth than a repository-wide commit equality check: unrelated repository commits do not invalidate the module map, while any relevant source/caller/document change does.
