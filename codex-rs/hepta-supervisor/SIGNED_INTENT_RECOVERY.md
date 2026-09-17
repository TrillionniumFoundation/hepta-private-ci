# Signed supervisor intent recovery

This runbook describes recovery for an externally authorized `SignedUpgrade` or `SignedRollback` whose durable outcome became ambiguous.

The recovery surface is intentionally narrow. It does not generate or evaluate releases, does not mint production authority, and never starts a child process as part of recovery.

## Entry condition

The daemon enters signed-intent recovery mode when a non-terminal `supervisor-signed-intent.json` survives restart or when a signed mutation fails after durable intent publication.

In this mode:

- `health.ready` is `false`;
- roster, snapshot and signed-intent inspection remain available;
- all ordinary lifecycle mutations are globally frozen, including direct Rust `Supervisor` callers;
- the periodic ticker remains active only to fence/reap an adopted ambiguous child and clear its exact process lease;
- Robrix cannot inspect or resolve signed intents.

A corrupt/tampered journal is fail-closed and cannot be resolved through this RPC because no trustworthy intent digest exists. Repair/quarantine of corrupt authority state is a separate operator procedure and must preserve the original bytes as evidence.

## Procedure

1. **Read health and snapshot.** Confirm the daemon is not-ready because recovery is required. Record `supervisor_epoch`, lifecycle generation, current/previous release and `state_digest`.
2. **Inspect the signed intent.** Call `InspectSignedIntent` for the Agent and record `grant_sha256`, transition, source/target release, expected revisions, authority epoch, status and exact `intent_sha256`.
3. **Wait for quiescence.** The recovery RPC rejects while the Agent runtime, Matrix runtime, release change, manual restart, deferred action, process lease or Matrix process lease remains active. Do not delete a live process lease merely to make the check pass.
4. **Verify durable release truth independently.** Compare FleetRegistry current/previous release with the signed intent and external grant/evidence. Do not infer success from PID liveness or from a matching executable path.
5. **Choose exactly one terminal acknowledgement:**
   - `reconcile_source` only if FleetRegistry already names the exact signed `source_release` as current. This abandons the ambiguous transition and writes terminal `reconciled_source`.
   - `accept_target` only if FleetRegistry already names the exact signed `target_release` as current. This acknowledges the already-durable release transition and writes terminal `committed`.
6. **Submit `ResolveSignedIntent`.** Supply the **current** `SupervisordControlFence`, the exact inspected `intent_sha256`, and the selected resolution. A stale fence, changed intent digest, wrong current release or non-quiescent process state is rejected.
7. **Refresh after every response.** If the state digest changed but the RPC returned an error, treat the recovery result as `operation_indeterminate`; inspect again before retrying. Never blindly replay a recovery request.
8. **Verify readiness.** After terminal recovery, refresh health/snapshot/intent. Ordinary mutations may be used only after the unresolved-intent set is empty. If the lifecycle is `failed` or `stopped`, a later explicit start/restart is a separate operator action and requires its own fresh control fence.

## Why recovery is effect-free

The recovery RPC does not call `start`, `upgrade`, `rollback`, `spawn`, or Matrix launch paths. Its authority is limited to acknowledging an already committed durable release fact after exact fence/digest checks. This prevents a recovery credential from becoming a second release-selection or deployment authority.

## Error classes

- `stale_control_fence`: refresh snapshot; do not retry with the stale fence.
- `signed_intent_recovery_required`: ordinary lifecycle mutation is frozen until recovery completes.
- `invalid_transition`: recovery prerequisites or requested durable release do not match; inspect current state.
- `unresolved_lease`: an exact child lease still exists; verify/reap the child rather than deleting evidence blindly.
- `operation_indeterminate`: a mutation boundary may already have been crossed; refresh all state before taking another action.

## Evidence to retain

Archive the exact daemon binary digest, host identity, request/response bytes, pre/post snapshots, signed intent bytes/digest, FleetRegistry record, process-lease state, relevant child process identity/incarnation, timestamps and operator identity. These receipts are operational evidence; they do not themselves grant promotion, activation or release authority.
