# P27 — fail closed on process-global optimizer step hooks

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Research-only, not a production safety sandbox.

## Frozen ancestry

- Parent: P26 [#3059](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3059) at exact SHA `0a0799ea81f0397f1e85562dda8602a6737fff57`.
- This P27 proposal changes only `qa/stem-bakeoff/multimodal_bridge.py`, `qa/stem-bakeoff/test_multimodal_bridge.py` and this document.
- The P26, P24 and earlier source branches and `main` must not move due to P27.

## Reproduced blocker (PyTorch 2.10 CPU)

Stock `torch.optim.SGD` and `AdamW` can dispatch globally registered
`register_optimizer_step_pre_hook` and `register_optimizer_step_post_hook`
callbacks during `optimizer.step()`, even if every instance hook registry is
empty. P26 rejects per-instance overrides and hooks but did not inspect these
process-global registries. A registered hook can write to a foreign Cell before
or after the legitimate Student/Slotizer weight step, bypassing owner checks
while allowing a nominal success receipt.

A standalone PyTorch 2.10 CPU reproduction registered a global pre-hook for an
SGD optimizer and changed a foreign `nn.Parameter` from 1.0 to 8.0, with the
optimizer's instance pre-hook registry empty. No full-model training claim.

## Bounded patch

- Fail closed on nonempty process-global pre **or** post optimizer step hook
  registries in `_verify_optimizer_lifecycle` before any projection.
- Existing lifecycle fences also run after projector hooks (before
  `zero_grad`) and after Student/backward hooks (before `step`), stopping
  late registration at both points.
- CPU regressions exercise pre/post hooks registered before entry, and global
  pre-hooks registered by a projector or Student forward hook. Tests verify
  hooks never execute and foreign/Student weights remain unchanged.
- Detection intentionally relies on global registries of the pinned
  PyTorch 2.10 runtime; future framework upgrades must requalify this seam.

## Preserved topology and nonclaims

Frozen 421M cognition control; EmbeddingGemma 2 shared Perception/Memory Stem;
T5Gemma 2 context Encoder comparator; native Hepta 150M/300M latent Student
candidates; per-Cell Gate, lightweight Adapter, Task/Action/Value Heads,
Local State and external evidence-ledger Memory. No per-Cell backbone, no
runtime authority, no checkpoint promotion, no Memory write, no CellSplit,
no NDU/System2 FinalUse.

This guard does **not** sandbox arbitrary Python, monkey-patching of global
functions/registries, native extensions, concurrent cross-process writers or
malicious code in model hooks. Untrusted teacher/model code must run in an
isolated worker with independently verified artifacts.

## Still blocking

Require fresh terminal exact-head shared-Stem CPU checks, architecture
source/base/required, full blocking-ci/cargo-deny/native platform and V8;
independent signed teacher/model/data lineage and heldout/OOD/negative-transfer
quality; genuine GPU 1–4096 Cell latency/memory/energy receipts; provenance,
rollback and authority review. Queued, cancelled, skipped, inherited, stale
or partial checks cannot close these gates. Production posture remains
`SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.
