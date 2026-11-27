# P19 — bind actual Student slot bytes in offline distillation receipts

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This is an isolated successor
of [P18 #3030](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3030)
at exact parent `4171e15dce1f9f4a7b50b4708f59f1d87c281375`. P18, earlier branches, `main`, production
Neuron/Worker and Memory writer authorities are not modified.

## Reproduced source-level blocker

P18 freezes all raw modality source tensors before any projector runs. P17 also
freezes and hashes the teacher target. However `shadow_distill_step`'s paired
v1 digest included only the source manifest and teacher target: changing
Slotizer weights could produce different actual Student input slots with the
**same** purported paired training receipt. The Student also received the
mutable `slots.slots` object without post-forward byte verification, and an
unexpected pooled Student output could be silently broadcast in the MSE loss.

## P19 scoped fix

- Keep the original differentiable training path by passing an autograd-preserving
  clone of Slotizer output to the Student, not a detached feature.
- Before any Student hook, validate shape, dtype/device and finite Student
  input slots; hash their exact detached raw bytes as `student_input_sha256`.
- Upgrade the local pair digest to `hepta.shadow-distillation-pair.v2`, binding
  actual Student input SHA256, shape and dtype as well as the source manifest,
  frozen target SHA256, target shape/dtype and generation.
- Verify the Student input still matches its pre-forward raw byte digest before
  calculating loss or applying optimizer steps; fail closed on observable
  in-place hook mutation.
- Reject Student outputs that violate the required exact `[batch,slots,width]`
  ABI; no broadcasting a pooled output against the target.
- CPU regressions cover two different Slotizer weights with identical source and
  target receipts, in-place Student pre-hook mutation and malformed output shape.
  Existing positive one-step gradient and P17/P18 custody regressions remain.

## Limits and gates

This is **local byte consistency**, not proof of trusted model weights, data
rights, independent checkpoints or adversarial behavior inside arbitrary
untrusted Student implementations. A hook that changes and restores a tensor
without leaving observable bytes cannot be ruled out by this postcondition;
running only audited Student implementations and separately signed provenance
remains mandatory.

Require exact-P19-head `Hepta shared Stem bake-off shadow checks`, full
`blocking-ci` including cargo-deny and Linux/macOS/Windows Bazel, architecture
convergence and V8. A queued/skipped/cancelled/old-head run is not a pass.

Keep the frozen 421M cognitive control, EmbeddingGemma 2 multimodal perception/
Memory teacher, T5Gemma 2 Encoder context comparator, native Hepta 150M/300M
latent Student candidates, and per-Cell Gate/Adapter/Task-Action-Value heads,
Local State and **external** Memory. No trained checkpoint, independent
future/OOD quality, real multi-GPU p95/p99/energy, model selection, final-use,
Cell split, authority promotion or production activation is claimed.
