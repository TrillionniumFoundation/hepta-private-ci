# Shared Stem P9: immutable modality and paired-cohort report evidence

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.
Parent: [P8 #2995](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2995) at `09c565f85594bd6a14503681f0a43b067373ae10`.
This is a narrow local-evidence consistency fix, not a pretrained-model or training capability claim.

## Failure mechanism and correction

P7 computed `MultimodalSlotizer` feature and timestamp SHA-256 only **after**
passing caller-owned feature tensors through its trainable projector. A producer,
forward hook or concurrent caller could change the original features/timestamps
between projection and hashing, leaving a source digest that describes values
different from the material used to produce the slots. The P8 offline distiller
had a related reporting edge: `source_split_digests` were reread from a mutable
`cohorts` dictionary after gradient steps, despite the paired evidence having
already been snapshotted before training.

P9 clones detached modality features and timestamps before calculating digests
or calling the projector. The projector receives its own input clone so it cannot
rewrite the source snapshot. Time-phase and canonical manifest are derived
from the exact same frozen timestamp bytes. Snapshot finite/time-order checks
are repeated after copying, so edits during capture cannot evade input checks.
The copy is once per bounded shared observation, never once per Cell.

P9 emits `source_split_digests` solely from the verified P8
`paired_split_receipts`; a caller replacing a cohort object inside an
optimizer hook cannot alter the reported before/after source identity.

## Regressions and qualification

- `test_multimodal_bridge.py`: projector forward hook mutates both original
  teacher features and timestamps. Observed canonical digest **and** slots must
  equal an unmodified baseline, even though the caller's tensors now differ.
- `test_offline_shard_distill.py`: optimizer hook replaces the entire heldout
  `PairedCohort`. Reported `source_split_digests` and verified paired receipts
  must retain the same preflight source commitment.
- Run the existing exact-HEAD shared-Stem shadow CI with pinned PyTorch/NumPy,
  plus blocking-ci, architecture convergence and V8 Canary; passing synthetic
  tests never qualifies pretrained checkpoints or production policy.

All previous candidate identities remain fixed: frozen 421M cognition control,
EmbeddingGemma 2 perception/Memory teacher, T5Gemma 2 Encoder competitor,
native Hepta 150M/300M student blueprints. Each Cell retains only bounded
Gate/Adapter/Task/Action/Value Head/Local State/external Memory references.
No per-Cell 421M copy, no production Memory write, no autonomous actuation,
no authority change and no parent or main branch merge.

## Still blocked

Independent checkpoint/license and preprocessing attestations, real teacher
execution, disjoint independent future/OOD evidence, full native 150M/300M
training, GPU p95/p99/VRAM/energy, source RustSec and Bazel/Windows failures,
exact-head CI and independent promotion review. No source-local digest proves
independent publisher or sample provenance, and no synthetic test closes
those external blockers.
