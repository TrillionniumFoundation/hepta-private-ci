# Cell FastPath ActionIR P0 (research / shadow-only)

This qualification lane defines the smallest reviewable contract for a Cell
that wants lower-latency local dispatch. It is intentionally an intermediate
boundary between a learned Cell head and the existing effect owner:

```text
shared Stem + Cell head -> typed ActionIR -> verifier/cache key -> shadow receipt
                                                    |
                              Guardian / TaskFlow / effect owner (future, unchanged)
```

The module does **not** execute native code, WASM, CUDA, syscalls, GUI events,
or model-generated binary. It only validates a bounded typed program, derives
a deterministic artifact cache key, and records a non-executing receipt.
`DENY_ALL`, `production_activation=False`, `executed=False`, and
`effect_committed=False` are structural invariants rather than caller
conventions.

## Contract surface

- `ActionOpV1` permits a small typed vocabulary (`observe_ax`,
  `observe_screen`, `locate`, `assert`, `click`, `key`, `type_text`, `scroll`,
  `focus_window`, clipboard operations, `wait`, and `emit`). Arguments are
  JSON values only; pointer-shaped fields, raw bytes, opcodes, PTX, machine
  code, file descriptors, and syscalls are rejected.
- `ActionIRV1` binds a Cell to Stem/head/objective digests, app identity,
  body generation, ABI, revocation epoch, capability IDs, and bounded
  operation/time/memory budgets. Duplicate idempotency keys are rejected.
- `FastPathCandidateV1` binds the IR digest to the Cell and app identities, a
  precompiled backend label, target, capability-manifest digest,
  authorization version, revocation epoch, resource limits, and evidence
  digest. The candidate is advisory and cannot activate production.
- `FastPathRuntimeReceiptV1` records pre/post observation digests and resource
  counters while structurally forbidding execution and committed effects.

## Intended implementation path after hosted qualification

1. Keep MCP/App Server/Supervisor and Guardian as the control plane and
   fallback. A fast path may replace only a local leaf dispatch after the
   same authorization decision.
2. Resolve a verified artifact from `(Stem/head/IR/target/ABI/policy,
   authorization version, revocation epoch)`. A future CPU backend may use
   WASM AOT or a separately signed native artifact; a future GPU backend may
   use a signed precompiled kernel or CUDA Graph with bounded scalar inputs.
3. Hand the verified artifact to the existing effect owner, which rechecks
   app identity, capability scope, generation, revocation, budgets, and
   preconditions before committing an effect.
4. Emit the repository's normal model/runtime/effect receipt. This contract's
   shadow receipt is not evidence that an effect was executed.

The next gate is hosted qualification with real Guardian/TaskFlow wiring and
negative tests for stale authorization, revoked capability, generation
mismatch, precondition failure, timeout, memory budget, replay, and fallback.
Until that evidence exists, this lane must remain research/shadow-only.
