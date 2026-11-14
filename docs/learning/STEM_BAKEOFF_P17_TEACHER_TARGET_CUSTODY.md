# P17 — freeze teacher target bytes before offline Student hooks

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Exact source parent P16
[#3026](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3026)
at `bd5e9348828e3c484cc384bf6332481bb73946ee`; no changes to `main`, P16, Cell authority or production serving.

## Actual P16 custody gap

`shadow_distill_step` used `target = teacher_global.detach()` **after**
trainable Slotizer execution. The detached tensor aliases the caller's storage.
A projector hook could change the teacher target before it was chosen; a
Student hook could change it after validation but before MSE. Receipts bound
the source features, not the target used for the loss. This permits an
untracked training-target mutation even when P16 optimizer ownership holds.

## Repair and reproducible regressions

- Validate bounded target shape, floating dtype and finite values before any
  projector or Student work, then create `detach().clone()` immediately.
- Digest frozen target bytes with SHA256 and return
  `teacher_target_sha256` and `paired_distillation_sha256`. The paired
  digest includes frozen target shape/dtype, source-slot manifest and generation.
- Require exact target device/dtype/shape agreement with projected global
  feature. Keep P16 optimizer ownership checks before/after hooks and backward.
- Compare loss and exact Student/Slotizer updates against an independent,
  identical control while projector and Student hooks mutate caller-owned
  teacher tensors; reject malformed targets before any projection.

These receipts provide **local byte consistency only**; they do not authenticate
the upstream teacher, dataset, checkpoint, memory evidence or data license.

## Qualifications still required

Run exact-P17-head `Hepta shared Stem bake-off shadow checks`, full
`blocking-ci` (cargo-deny, platform Bazel/Rust), architecture and V8. Skipped,
queued, cancelled or old-head runs are not qualification. Licensed EmbeddingGemma
2/T5Gemma 2 teacher execution, real future/OOD splits, complete Hepta
150M/300M distillation, physical 1–4096 Cell energy/p95/p99, external memory
governance, independent review and release approval remain open. Preserve the
frozen 421M cognition control and Gate/Adapter/Task/Action/Value/Local State/
external Memory-only Cell model, with `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.
