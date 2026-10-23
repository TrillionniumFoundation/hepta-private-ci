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
- Bound the entire volatile operation journal to 128 output chunks and 1 MiB of
  declared stream bytes, in addition to the existing 32 KiB per-record cap.
  An over-limit chunk fails before journal mutation; terminal completion and
  subsequent independent effect reconciliation remain possible. This is not an
  excuse to truncate evidence silently, nor a cap on an external durable log.
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
