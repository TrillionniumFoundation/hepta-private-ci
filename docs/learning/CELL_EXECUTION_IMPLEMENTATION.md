# Cell execution implementation contract

This document turns the cell/meta-network proposal into an executable staging plan.
It is a test plan and interface contract; it does not claim general intelligence,
universal approximation of a fixed checkpoint, or production online self-modification.
The current branch keeps Codex App Server as the sole model/session/tool spine and
adds a typed cell-to-execution boundary around it.

## P0 — versioned execution boundary

`codex-hepta-codex-adapter` now owns the following authority-free contracts:

- `CellExecutionIntentV1` — operation, cell, organ, generation, input and final-payload binding;
- `ExecutionReceiptV1` — intent/generation/payload-bound observation and recovery posture;
- `RuntimeToolIntentV1` — runtime tool intent carried by the same cell envelope;
- `CodexTurnBindingV1` — exact App Server session, thread, client-message, protocol, home and connection identity;
- `GenerationFenceWitnessV1` — old-writer fence, migration and route-cutover evidence;
- `FinalPayloadDigestV1` — scope/generation/type plus digest of the exact bytes submitted;
- `ToolOutcomeV1` — terminality and output digests;
- `RecoveryDispositionV1` — retry-before-admission, reconcile, quarantine and rollback posture.

`adapt_codex_cell_intent` is the cell-facing admission function. It converts a
validated cell intent into the existing `CodexOperationIntent` and therefore keeps
all current App Server observation and reconciliation rules in one execution spine.
Cells do not import App Server client or Core types.

For native tools, `RuntimeToolIntentV1::intent_digest()` additionally binds the
`tool_id`, argument digest, idempotency key and host scope. Every native result
must be checked through `RuntimeReceiptV1::validate_against` (including its
`runtime_intent_digest`); validating only the embedded Cell-level
`ExecutionReceiptV1` is insufficient to prove the exact tool operation.
This remains a contract check, not independent proof of a physical tool effect.

## P1–P2 — shared encoder and worker host

The intended implementation uses one immutable feature snapshot per batch, a shared
worker lane, and per-cell adapters/heads. A cell owns logical state and lineage; it
does not own an operating-system process. The first implementation must keep a
no-change path and a zero-delta path beside every learned candidate.

Required fixtures are:

1. shared-encoder output equals the duplicated-encoder output for the same frozen snapshot;
2. zero-delta adapter output is byte-identical to the no-update baseline;
3. state migration preserves a cell's bounded hidden-state digest and generation;
4. routing is deterministic for a fixed topology snapshot and request digest;
5. queue admission is bounded and fair across cell scopes;
6. cache entries are invalidated when the feature or topology generation changes.

Only after these fixtures pass should the host add feature batching, activation
batching, reusable immutable buffers, a compatible-model second index, per-scope
worker lanes and group-commit metrics.

## P3 — native hepta-runtime fast path

`NativeExecutionAdapter` is the in-process typed boundary. An implementation may
call the native `hepta-runtime` client directly on the same host. MCP/SSH remains a
remote boundary for cross-process, cross-host, external-agent and non-Rust consumers.
The adapter must validate the intent, submit the exact final payload digest, and only
return `RuntimeReceiptV1` after a terminal runtime observation. Runtime tool execution
cannot mint Codex/model authority.

## P4 — topology lifecycle

Topology changes are candidates until independently evaluated and admitted. The
required sequence is:

```
candidate → independent evaluation → selector → signed successor snapshot
→ state migration → old-writer fence → route cutover → canary
→ rollback rehearsal → production admission
```

Add, split, merge, rewire and retire each need a fault-injection case at every
boundary. An interrupted or unknown effect remains reconcile-only; it cannot be
converted into success by a restarted process. A generation fence witness
requires an exact successor generation when a predecessor is declared;
skipped or regressed generations are rejected before route activation.

## P5 — scale and meta-network evaluation

The scale matrix lives in `CELL_EXECUTION_BENCHMARK_MATRIX.json`. Each size runs the
same comparison arms: no-change, fixed routing, learned routing, single head,
shared encoder and duplicated encoder. Each arm records future-window performance,
negative transfer, lesion/ablation, crash/reopen, stale-generation rejection,
rollback, throughput, p99, queue fairness, RSS and cache cost.

The result is evidence for expressivity, learnability, unseen-task adaptation and
resource scaling separately. Increasing cell count is not, by itself, evidence of a
general-purpose agent.
