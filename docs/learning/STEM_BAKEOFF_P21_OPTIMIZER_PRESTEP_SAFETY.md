# P21 — constrain offline optimizer settings and existing state before Student step

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Isolated successor to
[P20 #3038](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3038)
at exact P20 source `463f2d69ce8c4250992e729fba9956985ff8265d`; no ancestor branches or `main` are edited.

## Reproduced failure mode

P20 validates complete Student/Slotizer parameter ownership and backward gradients.
However stock PyTorch SGD accepts nonfinite learning rates (NaN/Inf) and can write
nonfinite weights on `step()` even with finite gradients. Previously accepted
optimizer state may also contain nonfinite momentum or Adam accumulators. A
projector/Student hook can change a valid learning rate after the initial
ownership preflight without touching the parameter identities.

## Narrow research-only guard

- Accept only unmodified built-in `torch.optim.SGD` and `torch.optim.AdamW`;
  optimizer subclasses with arbitrary `step()` implementations fail closed.
- Check scalar, finite, bounded learning rates (`0 < lr <= 1`), weight decay
  (`0 <= wd <= 1`), SGD momentum/dampening, and AdamW betas/epsilon.
  Disallow maximizing the distillation loss and differentiable step modes.
- Check all present stock momentum/Adam state tensors are dense and finite;
  reject stale foreign parameter state and unknown state values/keys.
- Snapshot the non-parameter optimizer-group configuration before any
  trainable projection and verify it is unchanged after backward and before
  `optimizer.step()`. The P20 complete ownership and finite-gradient
  checks remain in force.
- CPU negative regressions cover SGD NaN/Inf and AdamW Inf rates, poisoned
  momentum, hook-modified (but finite) learning rates, and custom optimizers.
  The existing positive SGD/AdamW distillation tests remain available.

This is **not** atomic optimizer-step execution: an implementation bug or
extreme *finite* gradients can still overflow after `optimizer.step()`.
Independent checkpoint/model/data provenance, post-step atomic rollback,
CPU/GPU full-size students, memory/latency/energy and future-window OOD
qualification are unresolved. Restrict this helper to isolated offline
research; do not advertise it as a trusted production trainer.

## Inherited architecture and mandatory gates

Retain frozen 421M cognition control, EmbeddingGemma 2 Perception/Memory Stem,
T5Gemma 2 Encoder comparator, native Hepta 150M/300M latent Student and
per-Cell Gate/light Adapter/Task-Action-Value Head/Local State/external Memory.
No weight downloads, trained 150M/300M artifact, Memory writes, System2/NDU
activation, governance promotion or `main` changes.

Require **this exact P21 commit's** terminal shared Stem CPU shadow workflow,
architecture source/base convergence, full `blocking-ci` (cargo-deny plus
Windows/Linux/macOS Bazel and native Rust) and `v8-canary`.
Queued/skipped/cancelled/stale statuses are **not** PASS; inherited advisories,
platform failures, licensed checkpoints and physical 1–4096 Cell fan-out are
separate outstanding blockers.
