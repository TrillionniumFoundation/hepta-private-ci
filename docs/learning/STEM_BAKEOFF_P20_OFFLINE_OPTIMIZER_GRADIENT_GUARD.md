# P20 — complete offline optimizer coverage and nonfinite-gradient guard

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** This is a research-only
successor to [P19 #3035](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3035)
at exact source `1511ff107d958fc62d900d4a1de62abfc6ef3db9`. It does not modify P19, any ancestor, `main`,
model selection, Cell/Memory authority, CI policy, or production routing.

## Concrete P19 follow-up blockers

1. The P19 optimizer owner check accepted *any subset* of trainable Student
   and Slotizer parameters. A Slotizer-only optimizer could return a successful
   Student distillation receipt without optimizing a single Student weight.
2. P19 checked finite Student forward outputs and finite scalar loss, but never
   checked backward gradients before `optimizer.step()`. A finite output/loss
   with an NaN-producing custom backward hook could corrupt Student or Slotizer
   weights and still leave a nominally successful training path.

## Scoped changes

- Require the optimizer's unique parameter identities to match the complete
  trainable Student+Slotizer parameter set. Deliberate freezing is expressed
  with `requires_grad=False`, not silently by omitting trainable weights.
- After backward hooks and the existing exact optimizer-owner recheck, reject
  NaN/Inf gradients before any weight update. Reject unsupported gradient
  layouts and distillation steps with no Student gradient. Parameters with
  `grad is None` remain legal for unused modalities.
- CPU regressions for Slotizer-only/partially covered Student optimizers,
  rejecting before any projector forward, and for a Student whose forward
  output is finite but whose custom backward emits NaNs. The negative
  regression verifies both Student and Slotizer weights remain unchanged.

This is a local fail-closed *pre-step* guard, not a transactional optimizer:
an unusual optimizer with toxic momentum/state or an enormous user-supplied
learning rate could still produce invalid weights during `step()`. Signed
checkpoint provenance, post-step audit/rollback and safe optimizer-state
controls require a separate qualification path.

## Exact-head qualification

Require the latest P20 commit's terminal **Hepta shared Stem bake-off shadow
checks**, **blocking-ci** (including full cargo-deny and Linux/macOS/Windows
Bazel), **Hepta architecture convergence**, and **v8-canary**. Queued,
skipped, cancelled, stale or inherited checks are not passes. CPU prototype
checks and a new PR alone are not production qualification.

Continue frozen 421M cognition control, EmbeddingGemma 2 multimodal
perception/Memory teacher, T5Gemma 2 Encoder comparator, native Hepta
150M/300M latent Student and per-Cell Gate/Adapter/Task-Action-Value
Head/Local State/external Memory. No pretrained weights, full-scale distillation,
independent future/OOD evaluation, 1–4096 Cell hardware measurements,
System2/NDU production, Cell split, or production activation are claimed.
