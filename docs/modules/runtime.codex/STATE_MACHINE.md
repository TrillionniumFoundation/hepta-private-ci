# runtime.codex state machine and crash invariants

This document is the executable-state companion to `TECHNICAL.md` and `FAULT_MATRIX.md`. It defines what each durable owner may claim at every boundary. It is a repository-side contract, not target-host qualification.

## 1. Owners

| Owner | Durable fact | May not claim |
| --- | --- | --- |
| `hepta-infer-core` native journal | local admission, exact request binding, local capacity, pre-effect abort preparation, observed turn and terminal facts | Agentd run state, provider billing, external acceptance |
| Agentd run coordinator | admitted intelligence run, context attachment, exact dispatch binding, cancellation and terminal reconciliation | App Server transport delivery unless reported by the runtime.codex observer |
| Codex App Server | thread/turn admission and process-local terminal events | Hepta final-use authority or cross-owner settlement |
| final-use authority | signed grant, epoch, revocation frontier and nonce | provider outcome or local journal settlement |
| provider/effect owner | real external admission and terminality | Hepta owner readiness or release authority |

No actor may synthesize another owner's fact.

## 2. Local native states

```text
Reserved
  -> Dispatching
      -> AbortPending -> Released
      -> Running -> Cancelling | Indeterminate | Released
      -> Indeterminate
  -> Released
```

`AbortPending` is a durable promise that this operation will not cross the external `turn/start` boundary. It retains capacity until Agentd has accepted the same exact abort proof. Recovery may finish that abort; it may never resume the send path.

Legacy `AbortBeforeEffect` records remain replayable. New cross-owner operations use `PrepareAbortBeforeEffect` followed by `ConfirmAbortBeforeEffect`.

## 3. Agentd owner states

```text
Admitted
  -> ContextAttached
      -> Dispatched
          -> AbortedBeforeEffect
          -> Cancelling
          -> Cancelled | Succeeded | Failed | Indeterminate
```

`AbortedBeforeEffect` is closed but is **not** a provider terminal observation. It releases Agentd capacity only after all of the following match:

- run identity and expected revision;
- runtime.codex request/dispatch digest;
- nonce commitment stored at `Dispatched`;
- opened nonce;
- reason-bound abort proof.

A legacy unbound `Dispatched` record cannot use this transition.

## 4. Cross-owner abort saga

1. The worker generates a cryptographically random, non-serializable abort nonce when it durably prepares the native dispatch.
2. It derives a domain-separated commitment from `(run_id, dispatch_binding_digest, nonce)`.
3. Agentd records `Dispatched`, the exact dispatch binding and the commitment in one owner transition.
4. Before any physical send, a final-use failure causes the worker to derive a reason-bound proof from the same tuple.
5. The local journal commits `AbortPending`, including the nonce opening and proof. From this commit onward no code path may send.
6. Agentd verifies the commitment and proof and transitions to `AbortedBeforeEffect`.
7. The local journal records `ConfirmAbortBeforeEffect` and releases capacity.

The ordering is deliberate. A crash after step 5 but before step 7 leaves a recoverable, non-sendable operation rather than contradictory closed/open facts.

## 5. Crash matrix

| Crash boundary | Local journal after reopen | Agentd after reopen | Allowed recovery | Forbidden recovery |
| --- | --- | --- | --- | --- |
| before local dispatch | `Reserved` | `ContextAttached` or earlier | definitive local stop | claiming a provider attempt |
| after local dispatch, before owner mark | `Dispatching` | `ContextAttached` | prove owner did not mark, then local stop | sending without a fresh exact owner transition |
| owner mark request acknowledgement lost | `Dispatching` | `ContextAttached` or exact `Dispatched` | query exact run; continue only on matching nonce commitment, otherwise abort | blind second owner mark with changed semantics |
| after owner mark, before local abort prepare | `Dispatching` | exact `Dispatched` | same live token may prepare abort; after process loss reconcile-only | reconstructing the in-memory nonce from unrelated state |
| after `AbortPending`, before Agentd abort | `AbortPending` | exact `Dispatched` | replay exact owner abort proof | physical `turn/start` |
| Agentd abort acknowledgement lost | `AbortPending` | `Dispatched` or `AbortedBeforeEffect` | query/retry exact proof; then confirm locally | changing reason, nonce, binding or run |
| after Agentd abort, before local confirm | `AbortPending` | `AbortedBeforeEffect` | confirm exact proof locally | reopening provider execution |
| after token entry/socket write, before ACK | `Dispatching` or `Running` | `Dispatched` | same-operation App Server reconciliation only | pre-effect abort or a new `turn/start` |
| terminal event before local settlement | `Running`/`Cancelling` | unresolved | replay exact terminal observation | inferring success from handler return |
| App Server history lost | indeterminate | indeterminate/unresolved | external signed resolution or indefinite quarantine | timeout-based “not applied” |

## 6. Runtime typestate

The implementation should preserve the following compile-time conceptual states even where they are split across helper types:

```text
Preflight
  -> ThreadPrepared
  -> PayloadFrozen
  -> AuthorityClaimed
  -> LocalDispatchJournaled
  -> OwnerDispatchCommitted
  -> EffectEntered
  -> StartObserved | StartUnknown
  -> TerminalObserved | Quarantined
```

Only `OwnerDispatchCommitted` may enter the effect boundary. Only states before `EffectEntered` may produce a pre-effect abort proof. `EffectEntered` consumes the final-use token and invalidates the abort path.

## 7. Invariants

1. A reused operation identity with changed semantics conflicts.
2. A persisted `AbortPending` operation is never sent, including after restart.
3. `AbortedBeforeEffect` never sets `terminal_observed=true`.
4. Provider completion alone cannot authorize success after owner loss.
5. Cancellation, deadline or transport loss after effect entry never refunds the grant and never proves non-delivery.
6. Capacity is released only by an exact closed transition, not by elapsed time or log deletion.
7. Every digest is domain-separated and length-framed.
8. Recovery preserves original absolute deadline, generation, session, model/provider, request payload and stable client-message identity.

## 8. Required metrics

- `runtime_codex_abort_pending_total`
- `runtime_codex_abort_reconcile_attempt_total`
- `runtime_codex_abort_reconcile_conflict_total`
- `runtime_codex_orphan_thread_cleanup_total`
- `runtime_codex_start_unknown_total`
- `runtime_codex_quarantine_active`
- `runtime_codex_owner_loss_total`
- `runtime_codex_provider_event_lag_total`
- latency histograms for authority claim, durable prepare, owner mark, effect entry, start ACK, first token, terminal observation and reconciliation

Metrics are observations, never settlement authority.
