# P23 — reject physically aliased Student/Slotizer optimizer parameters

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**
Exact source parent: P22 [#3044](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3044)
at `519a28fbd3350490c002ccb93359a2c7564601c2`.

## Reproduced integrity blocker

P20–P22 check optimizer ownership by Python `nn.Parameter` object IDs.
`nn.Parameter(existing_weight.detach())` creates a distinct ID while
preserving the same underlying backing storage. An optimizer containing both
IDs passed ownership/coverage checks and could update shared weights twice,
violating Student/Slotizer separation. A forward hook could also rebind the
physical storage after the initial check and before the step.

The local CPU reproduction on PyTorch 2.10 confirmed that both object IDs
pass the old owner set test, even though their storage pointers are identical.

## Exact research-only fix

- Reject unsupported, empty or pointerless optimizer-owned parameter storage.
- Check each actual storage span, grouped by device, for overlap. Conservatively
  reject even disjoint views sharing an allocation: intentionally tied weights
  must have a single explicit owner before entering this function.
- Reuse the same check at the existing ownership gates before projector
  execution and after forward hooks, prior to any optimizer update.
- Add adversarial CPU cases for an initial distinct-object/same-storage alias
  (zero projector calls), and a forward-hook-induced late alias (no update).
- Retain frozen 421M control, EmbeddingGemma 2 perception/Memory Stem,
  T5Gemma 2 Encoder comparator, Hepta 150M/300M latent students, and only
  Gate/Adapter/Task-Action-Value Heads/Local State/external Memory per Cell.

## Explicit nonclaims and remaining qualification

This guard detects aliases **among the Student/Slotizer parameters it is
given**. It cannot attest arbitrary unknown Cell/teacher tensors elsewhere
in the process, independent checkpoint/data custody, malicious extensions,
external I/O, forward-hook side effects or crash-atomic checkpoint rollback.
The existing P22 step-rollback safeguards still apply, and real authorized
weights and verified heldout/OOD data are still missing.

The result is a source candidate, not a passing full-scale bake-off.
Require exact-head CPU shadow CI, architecture, complete blocking-ci including
cargo-deny and Linux/macOS/Windows Bazel, v8-canary, independent model/data
provenance and genuine 1–4096 Cell resource measurements. A queued, skipped,
cancelled, inherited or stale outcome is not PASS. No model selection,
production activation, FinalUse, Memory mutation, System2/NDU or Cell Split
authority is granted.
