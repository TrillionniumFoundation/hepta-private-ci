# P16 — strict parameter ownership for shadow-only latent distillation

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** This child is based on
P15 #3025 at `06631ca08b41cd784631daee3d7c6693e8d18d55`.
All ancestor qualification and release fences remain unchanged.

## Problem

`qa/stem-bakeoff/multimodal_bridge.py:shadow_distill_step` accepted an
unscoped `torch.optim.Optimizer`. The teacher feature was detached, but the
optimizer itself could include trainable parameters belonging to another
Neuron Cell, teacher, frozen Stem or arbitrary unrelated module. A custom
projection hook could also replace the optimizer's parameter list after the
initial call. Existing P6 offline-shard rehearsal ownership checks did not
protect this separate P2/P7 slotizer distillation entry point.

## Correction and regressions

- Require a real PyTorch optimizer with nonempty, unique trainable parameter
  identities that are owned by this invocation's Student or shared Slotizer.
  Reject parameter ownership overlap between Student and Slotizer.
- Verify exact optimizer parameter identity before projecting, immediately
  after projector hooks, and again after backward but before `step()`.
- Adversarial CPU tests reject an optimizer carrying foreign Cell/teacher
  parameters **before any projector forward** and reject a foreign parameter
  injected by a projector hook **before any weight update**.
- Preserve gradient isolation of teacher targets/features and original
  successful Student+Slotizer training; no optimizer state is created inside
  a Neuron Cell.

## Nonclaims and release posture

Owner identity validation is not proof of licensed checkpoint provenance,
data authorization, gradient correctness, optimizer code trust, model quality
or System2 emergence. Run exact-P16-head Stem Shadow CPU tests, all blocking
CI, architecture and V8 checks. The frozen 421M control, EmbeddingGemma 2
Perception/Memory Stem, T5Gemma 2 Encoder bake-off, Hepta latent 150M/300M
students and Cell Gate/Adapter/Task-Action-Value/Local State/external Memory
division remain as-is. Future/OOD, real checkpoint and hardware qualification
block any production admission.
