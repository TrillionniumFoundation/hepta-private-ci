# Provider effect identity and recovery

This describes the implementation contract owned by `authorized_effect`, the existing TaskFlow dispatch ledger, and Agentd's automation effect host. It is subordinate to the global development plan and grants no additional execution authority.

## One logical identity

A new TaskFlow effect derives its provider key from four separately encoded fields: provider scope, the durable `AutomationStore` owner, run ID, and step ID. The domain is `provider-effect:taskflow:v2`. Payload bytes and attempt number are outside the stable key. A changed payload must conflict with the existing effect instead of silently creating another occurrence.

Once any attempt exists, recovery and an authorized absence retry use its stored key and exact wire bytes. The complete step history must agree on identity, payload, and destination. Old keys remain parseable; missing legacy identity or wire bytes remain recovery-only. Configuration changes must not manufacture replacement identity. A request subject is not the durable owner.

## Dispatch and evidence boundaries

The existing owner creates a fresh dispatch barrier in `BEGIN IMMEDIATE`. It verifies the original run event chain, a current live owner fence, the actual claimed step and immutable intent, and all prior attempts. A retry requires effective proven absence, completed cancellation/requeue of the prior step, and a newer generation. An existing attempt returns recovery state and does not authorize another physical contact.

After contact, an acknowledgement is a fact about the existing attempt. A later lease expiry or cancellation does not erase it. Recording it does not revive the cancelled run or authorize another action. A terminal read checks the actual owner and exact intent, and may return a persisted result after the lease has been released.

## Receipts and uncertainty

Migration `0021` adds versioned provider receipts to the original ledger and pins the first binding to its actual attempt. Receipt identity includes the stable key, payload digest, provider operation ID digest, state, and actual dispatch-response or status-lookup provenance. The first binding and each attempt's observation/reconciliation remain append-only.

An original `Indeterminate` observation stays in history. Recovery appends terminal reconciliation; consumers use `final_outcome` for the known result. A later unknown lookup cannot release a known operation ID. Ordinary 404 / `NotFound` is unresolved and cannot authorize replay. The original owner's explicit absence API remains separate and cannot turn a known accepted operation into absence.

One narrow reverse-provenance continuation is permitted: physical dispatch is awaiting its response when a concurrent lookup first records `Accepted`. Its later `Completed` dispatch response may append a terminal fact only for that same bound attempt, key, payload, and provider operation while the effective observation is indeterminate. The receipt remains labelled `DispatchResponse`. A different operation, rejection after acceptance, a binding from another attempt, or replacement of an existing terminal result is rejected.

Receipts have a 1024-byte limit. Reads cap materialization at the rejection boundary, and startup scans bounded pages. Reopen checks immutable triggers, JSON/digest agreement, exact identity and attempt association, observation/reconciliation consistency, and whole-step identity continuity. Old migration checksums are unchanged.

## Validation boundaries

Controls exercise the actual generic owner, persistent SQLite migration/reopen, concurrent barriers, and Agentd's HTTP adapter. They cover original-key recovery, payload and scope conflicts, distinct durable owners with the same subject, original Unknown retention, same-attempt late ACK, cancellation, and terminal reads without an extra GET.

Use the existing `just test` entry point for the contracts/evidence provider suite, complete automation crate, and explicit Agentd HTTP selectors. The native pair workflow binds each command to exact source tuples and requires observed passing tests; a successful compile or zero-test filter is insufficient. Current results and source hashes belong in PR/CI evidence, not this contract.

The protocol depends on the receiver's declared idempotency and query behavior. A local database marker cannot make an arbitrary HTTP endpoint exactly-once. External-effect completion is also separate from fresh PoN membership: a retained terminal receipt cannot establish that its packet is still on the active chain after a reorg.
