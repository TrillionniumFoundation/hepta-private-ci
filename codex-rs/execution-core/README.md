# codex-execution-core: canonical ABI v1

This crate is a **control/evidence protocol**, not an executor. It has no
dependency on Codex App Server, Hepta neuron, MCP, a model, TUI, shell,
network, credential provider, or authority store.

The nine serialized record variants are: ExecutionIntent,
ExecutionReservation, ApprovalRequest, ExecutionStarted,
ExecutionOutputChunk, ExecutionCompleted, ExecutionCancelled,
ExecutionReconciled, EffectReceipt. Each embeds the complete
ExecutionBinding including explicit schema version, stable identities,
operation/generation/fence correlation, content digests, predecessor,
currentness, FinalUse posture, idempotency key and rollback reference.

**Security invariants**

- Deny unbound operation/identity/generation changes and predecessor drift.
- Deny replay and illegal transitions; chunk sequence is strictly increasing.
- Deny side-effectful starts without a FinalUse verification claim, and
  privileged or cross-host starts without a prior approval request/receipt.
- **Do not trust serialized grants, approval or outcome claims.** The
  trusted runtime must implement ExecutionVerifier and
  EffectReceiptVerifier against independent owner-issued evidence.
- Recording a result is not executing it. Callers must durably append and
  fsync accepted events before any real operation.
- This volatile, single-operation journal is not a distributed transaction,
  an idempotency database or a production recovery log.

**Deployment ordering**

1. Shadow-only Codex adapter -> Agentd/DecisionCell candidate (no effects).
2. Independently measured future-window matched-compute canary and frozen
   no-change baseline; separately verify negative transfer and retention.
3. Host-signed currentness, authorizer-produced FinalUse and actual effect
   receipt, persistent CAS and crash-recovery/reconciliation checks.
4. Gradual effect-class cutover from inspections to privileged device actions.
5. Independent release cadence only after two tested live consumers exist.

Until these steps have real execution receipts and accepted CI gates, this is
an **ABI foundation**, not a production cutover or a closed Phase 2-5.

## Shadow native Agent Loop cursor (P4 staging)

`shadow_loop.rs` adds a strict, bounded, **volatile** Agentd integration seam.
It consumes the existing `AgentStepRequestV1`/`AgentStepObservationV1`
contract, permits one pending proposal at a time and refuses additional
steps until a separately provided `ShadowStepCommitVerifier` confirms the
exact owner state transition and independently observed tool/model terminal
outcome. Unknown effects are sticky `Indeterminate` and never retryable
from this cursor. Waiting runs require a separately verified wake.

This module never opens a provider, dispatches a tool, mints FinalUse,
persists run ownership, verifies signatures on its own or attests source/
model/physical identity. A test verifier returning `Ok(())` is intentionally
**not** a qualified production verifier. A real Agentd integration must
durably store the step intent and commitment before publication, require
the independent Final-use issuer for physical effects, reconcile lost
acknowledgements and fail closed on generation/revocation drift. The
existing Codex App Server remains authoritative until an independent
full P2/P4 physical cutover qualification succeeds.
