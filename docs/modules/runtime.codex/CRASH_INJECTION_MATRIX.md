# runtime.codex crash-injection matrix

This matrix is the closed-world repository fault contract for the named
`runtime.codex` caller. It is aligned with the current irreversible boundary:
Agentd's exact `RunMarkDispatchedExact` compare-and-swap is the server-owned
effect-entry fence. All owner, ingress, context, cancellation, deadline,
revocation and `VerifiedUseToken::enter` checks occur while Agentd is still
`ContextAttached`. Once the fence RPC may have committed, abort and capacity
release are forbidden until exact rejection, terminal evidence or an
independently verified quarantine resolution is durable.

Repository tests model every cut below and exercise selected cuts against real
repository processes and a controlled provider. They do not replace the
protected target-host eight-scenario harness, a real provider, independent
acceptance, activation, promotion or release.

## Global invariants

1. One durable operation may cross physical `turn/start` at most once.
2. Only the caller receiving a fresh, exact, non-idempotent effect-entry ACK
   receives the non-transferable one-shot send permit.
3. A lost, mismatched, stale or idempotent fence response grants no send permit.
4. The local pre-effect abort proof is non-cloneable and non-serializable. It is
   destroyed before an effect-entry RPC whose commit result may become unknown.
5. Exact owner-first abort is legal only while Agentd is `ContextAttached`; a
   post-fence abort is impossible.
6. Local and Agentd identities bind the same operation, request, dispatch,
   payload, revision and generation. Drift is a hard conflict.
7. After the fence may have committed, timeout, cancellation, process death,
   socket failure and unknown acknowledgement are same-operation reconciliation
   only.
8. Typed non-admission closes Agentd first and releases the local reservation
   only after exact owner acknowledgement.
9. Terminal settlement is durable before ephemeral-thread cleanup and is
   idempotent across both owners.
10. An unresolved effect retains capacity. Missing ephemeral history never
    proves absence and enters signed quarantine.

## The 22 cut points

| ID | Cut / observation | Local durable state | Agentd state | Permitted recovery |
| --- | --- | --- | --- | --- |
| RCX-CRASH-01 | Before native admission | no record | no runtime.codex run | a new normal admission may begin |
| RCX-CRASH-02 | After admission, before dispatch prepare | reserved | `Admitted` or `ContextAttached` | reopen the same reservation; no effect exists |
| RCX-CRASH-03 | During local dispatch write/fsync | predecessor or fenced store; never a partial valid dispatch | unchanged | fail closed and repair/reopen the store |
| RCX-CRASH-04 | Exact dispatch prepared, before final validation | prepared plus live abort proof | `ContextAttached` | same live process may continue or exact-abort |
| RCX-CRASH-05 | Local abort intent durable, before owner abort RPC | abort pending; capacity held | `ContextAttached` | replay only the exact abort protocol |
| RCX-CRASH-06 | Owner abort request/ACK lost | abort pending; capacity held | `ContextAttached` or exact `CancelledBeforeEffect` | query/reconcile the exact owner transition |
| RCX-CRASH-07 | Owner abort committed, before local release | prepared/abort pending; capacity held | exact `CancelledBeforeEffect` | finish the matching local release |
| RCX-CRASH-08 | Both pre-effect owners closed | released | exact `CancelledBeforeEffect` | original operation is closed; ordinary policy may create a distinct operation |
| RCX-CRASH-09 | Fence RPC initiated, commit result not yet known | `FenceUnknown`; abort proof destroyed | `ContextAttached` or exact `Dispatched` | reconcile owner; never send without the original fresh ACK |
| RCX-CRASH-10 | Fence committed, response lost | `FenceUnknown`; capacity held | exact `Dispatched` | same-operation reconciliation; idempotent receipt grants no send |
| RCX-CRASH-11 | Fresh fence ACK received, before physical write | `EffectEntered`; one send permit | exact `Dispatched` | the original live caller may attempt one write |
| RCX-CRASH-12 | Partial/unknown socket write | accepted-or-unknown; permit consumed | exact `Dispatched` | same connection/event/history reconciliation only |
| RCX-CRASH-13 | Full write, `turn/start` ACK lost | indeterminate | exact `Dispatched` | exact `turn/started`, then `thread/read`; no new start |
| RCX-CRASH-14 | Typed pre-admission rejection observed | rejection prepared; no provider effect | exact `Dispatched` until terminal rejection CAS | settle Agentd exactly, then release local capacity |
| RCX-CRASH-15 | Rejection owner ACK lost | pending rejection; capacity held | terminal rejection or exact `Dispatched` | reconcile the rejection; do not infer closure |
| RCX-CRASH-16 | Started event observed, before `native_started` persists | dispatch plus observed turn identity | exact `Dispatched` | interrupt where possible; recover exact turn, never replay |
| RCX-CRASH-17 | Started state durable, before terminal event | started; capacity held | `Dispatched`/`Cancelling`/`Indeterminate` | observe or reopen the same turn |
| RCX-CRASH-18 | Terminal event observed, local settlement not durable | terminal fact in process only; capacity held | unresolved | retry exact local settlement; process loss requires history/provider evidence |
| RCX-CRASH-19 | Local terminal durable, owner terminal not durable | terminal durable; capacity held until owner convergence | exact `Dispatched`/`Cancelling`/`Indeterminate` | exact owner terminal CAS/reconciliation |
| RCX-CRASH-20 | Owner terminal committed, ACK/local release lost | terminal durable, release pending | terminal | finish idempotent local release |
| RCX-CRASH-21 | Cleanup/unsubscribe fails after terminal durability, or history is unavailable for an unresolved effect | terminal record plus orphan metric, or quarantined unresolved record | terminal or `Indeterminate` | reaper for terminal orphan; signed quarantine for unresolved history loss |
| RCX-CRASH-22 | Duplicate owner, stale revision or semantic digest conflict | unchanged or quarantined conflict | one fresh winner or unchanged | losers reconcile; stale/drifted mutations are rejected |

## Executable repository model

`codex-rs/hepta-infer-worker-host/tests/runtime_codex_crash_matrix.rs` is an
executable state model for all 22 cuts. Its required tests prove:

- every declared cut preserves the global invariants;
- fresh fence ACK is the only send permit;
- lost and idempotent fence ACKs cannot mint a permit;
- abort is exact before the fence and impossible after it;
- competing workers cannot both send;
- typed pre-admission rejection closes both owners without a provider effect;
- terminal settlement is exactly once and releases capacity;
- 256 duplicate owners still yield one fresh winner/send;
- 10,000 stale revisions and 10,000 digest conflicts are mutation-atomic;
- restart and lost-fence-ACK recovery cannot recreate a send permit.

The source qualification receipt has dedicated `crash-matrix` and
`quarantine-protocol` records. A missing, skipped, cancelled, timed-out,
under-floor or failed record fails the exact-head or synthetic-merge lane.

## Process and target-host execution

The pure model is supplemented by:

- native journal kill/reopen tests around durable writes;
- real Agentd/App Server composition against the controlled Responses server;
- owner-loss, cancellation, deadline, revocation and context-race tests;
- the protected target-host scenarios in
  [`TARGET_HOST_FAULT_HARNESS.md`](TARGET_HOST_FAULT_HARNESS.md):
  provider ACK loss, event lag, worker kill after fence, worker restart, Agentd
  restart, revocation advance before entry, duplicate owner and stale revision.

Every target-host scenario binds the exact source, operation, provider audit,
journal and harness digests and proves zero duplicate/replayed requests,
monotonic owner revision and the required capacity disposition.

## Receipt and claim boundary

Repository receipts are generated by `scripts/runtime_codex_receipt_v2.py` for
the exact source head and deterministic ordered-parent synthetic merge. The
protected workflow separately attests the canonical receipt bytes. A valid
signature authenticates bytes and workflow identity; it cannot turn a failed or
missing record into a pass.

Real-provider/host execution, key custody, trusted time/revocation,
anti-rollback restore, canary/rollback, independent acceptance, activation,
promotion and release remain separate externally governed facts.
