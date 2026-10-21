# P26 — fail closed on optimizer lifecycle replacement

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.

Research-only successor to [P24 #3053](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3053)
at frozen source `e5095f78797d639579b04413790b194352823983`. Parent branch and `main` remain unchanged.

## Concrete blocker

The previous offline Student/Slotizer owner, finite-gradient, physical-storage
and rollback checks reject a patched `optimizer.step` but allow Python instance
overrides for `optimizer.zero_grad`, `optimizer.state_dict`, and
`optimizer.load_state_dict`. A zero-grad override can mutate a **foreign Cell**
before the Student forward and still let a nominally successful training
receipt escape. A snapshot/restore override can invalidate the claim that an
unsafe physical optimizer step was rolled back. PyTorch 2.10 CPU proves the
side effect: an SGD optimizer with overridden `zero_grad` changes a foreign
parameter from 7 to 10 outside its own param groups.

## Change

- Require the exact stock SGD/AdamW lifecycle methods. Forbid per-instance
  overrides of step, zero_grad, state_dict or load_state_dict and reject
  lifecycle hooks, including state serialization/restore hooks.
- Repeat the lifecycle guard before any projector executes, immediately before
  `zero_grad` following projector hooks, and before the physical step
  following backward/Student hooks.
- Add negative CPU regressions for early and projector-injected zero-grad
  overrides, forged snapshot/restore methods, and Student-hook-injected
  restore overrides. All fail closed before an unauthorized method is called.

No optimizer configuration is automatically trusted. This is a local
research-only denial boundary. The implementation does not sandbox native
Python extensions, malicious global monkey-patches, arbitrary hook side
effects, external I/O, GPU races or cross-process writes. It does not prove
actual EmbeddingGemma 2 / T5Gemma 2 checkpoint provenance or the 150M/300M
Student trained-quality comparison. The frozen 421M cognitive control,
multimodal perception/Memory teacher, T5 encoder comparator, Student variants
and light per-Cell heads/local state/external ledger remain unchanged.

## Mandatory gates

Require exact-head shared Stem CPU checks, architecture source/base/required,
blocking-ci including cargo-deny and Linux/macOS/Windows Bazel, v8-canary,
and independent model/data/OOD/resource receipts. Queued, failed, skipped,
cancelled, inherited or stale checks do not qualify. No authority promotion,
CellSplit, Memory mutation, NDU/System2 or FinalUse admission.
