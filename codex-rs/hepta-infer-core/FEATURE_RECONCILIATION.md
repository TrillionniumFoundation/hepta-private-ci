# Neuron feature outcome reconciliation

`FileNeuronFeatureExecutionStoreV1` is an inference.control-owned journal, not an authority issuer or a physical driver. Owner authentication and current-fence observation remain the caller's responsibility.

## Unexecuted, dispatched and unknown

`Reserved` means the dispatch fence has not been recorded. `Dispatched` means an effect may have occurred; neither restart nor a lost response permits fresh execution. `Indeterminate` retains the original request and observed receipt in the unresolved set. Only observed `Succeeded`, `Failed` or `Cancelled` outcomes close the operation. Cancellation intent alone is not a cancelled observation.

An identical receipt is idempotent without another journal append. A final receipt is immutable. Resolving an indeterminate receipt requires the original request identity and the same complete model/runtime/device tuple and encoder/head binding. The journal cannot dispatch an indeterminate operation again. Wrong-generation requests reject before writing, so a live admission cannot create a history rejected by the replay generation check.

## Compatibility

Existing HPTNFS01 headers, request/receipt hashes and reserve/dispatch/observe event meanings remain unchanged. Resolution uses the explicit critical event `resolve_indeterminate_v1`. Old decoders reject this event; they must not be used to reopen a journal after a resolution is appended. Do not downgrade a binary by removing or truncating the event. Rollback needs a compatible reader and must preserve the original unresolved operation, deletion and generation fences. This change is a semantic bug repair and an additive journal-event capability, not blanket backwards-writer compatibility.

Both the live writer and replay reducer validate resolution bindings. Invalid or reordered critical events fail closed. Checksums detect corruption but are not signatures or proof of an independently observed external effect.

## Regression coverage

`neuron_feature_store_tests.rs` covers unknown outcome reopening, final success/failure/cancellation reconciliation, duplicate-receipt byte stability, redispatch rejection, post-sync uncertainty, generation rejection before mutation and a validly checksummed model-substitution event rejected on replay. Run through the existing repository entry point:

```sh
just test --locked --lib -p codex-hepta-infer-core --retries 0
```

The source tests do not establish successful execution until an exact-candidate native result is retained. This journal repair does not complete physical Laya execution, Agentd/TaskFlow wiring, cross-owner recovery or a trusted provider reconciler.

## Exact-candidate recovery and retained-history qualification

The architecture workflow selects actual tests through the repository `just test`
entry point with retries disabled. A successful process exit with zero observed
passing tests remains a failed execution record. The prior nonexistent history
and alternating-writer selectors are replaced by the current retained-history
curve and `exclusive_owner_turnover_retains_unknown_and_completed_work`.

The turnover test reopens sixteen successive exclusive owners, rejects overlap,
retains a cancelled but dispatch-fenced operation and its occupied capacity,
rejects replacement-worker identity and repeated dispatch, and checks complete
historical records without extra journal bytes. Only an explicit matching
completion settles the unknown computation; prior cancellation still prevents
eligible delivery. This is not a claim of live split/merge, parallel writers,
incremental replay, memory reclamation, power-loss recovery or compaction. The
existing legacy maintenance selector continues to disclose that it measures
retained append/fsync/reopen rather than compaction.

All commands within each architecture scope retain their independent execution
records even when an earlier command fails; any failure still makes the step
fail. Source-head and fixed-base-merge remain separately executed, with the
existing command/identity/zero-test and repository-control checks unchanged.

Reservation uniqueness uses a derived ordered identity index rather than scanning
all retained semantic records at each admission. The index is rebuilt through the
same validated replay reducer and published only with the existing successful
append/fsync. Terminal, cancelled and stopped identities stay reserved; failed
admissions do not consume identities. No journal bytes, authority semantics or
owner boundaries change. Conflict lookup is logarithmic in retained identity count;
this removes one quadratic replay/admission component, not every history-dependent
cost or the need for compaction. Live/reopen and forged-event tests cover these
invariants; target-host timings must come from current execution records.
