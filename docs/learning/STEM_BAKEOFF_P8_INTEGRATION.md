# Shared Stem P8: immutable paired-evidence integration (SHADOW_ONLY)

Status: **DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.
Parent: [P7 #2994](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2994), whose base traces through P6 #2992, P5 #2990, P4 #2985 and the bake-off #2970.
Incorporates the **source-snapshot correction from #2993** without replacing P7's multimodal provenance-byte binding or bounded 1–4096 Cell fan-out.

## Intended model and Cell boundary (unchanged)

* Cognition control: keep the existing frozen 421M model.
* Multimodal perception and Memory-key teacher: EmbeddingGemma 2, with approved checkpoints and independent source metadata required before empirical qualification.
* Context competitor: T5Gemma 2 Encoder.
* Native shared candidates: untrained Hepta 150M / 300M latent-stem architecture blueprints.
* Cell budget: Gate, small Adapter, Task/Action/Value (and uncertainty) Heads, bounded Local State, **external Memory references** only. No copied encoder or Cell-owned optimizer/model checkpoint in the production boundary.
* No license approval, actual model download, pretrained teacher execution, independent data attestation, GPU training, production weight export, memory mutation, autonomous actuation or promotion is performed by this PR.

## P8 implementation

The original P6 preflight digested `slots.detach()` and retained an alias to caller-owned source storage. A later producer change or student in-place forward could therefore make reported train/future/OOD losses depend on bytes different from the previously checked source-slot SHA-256. The fix from sibling #2993 snapshots with `slots.detach().clone()` **before** hashing, clones verified teacher features and presents a fresh slot clone to every Student forward (including train and heldouts). It rejects trainable upstream producers.

P8 also emits `paired_split_receipts` with one entry for each of the **exact five** train, calibration, future_1, future_2 and OOD splits:

* `source_manifest_sha256`: matched against the teacher shard's ordered source commitment, but not independently attested.
* `student_slot_sha256`: SHA-256 of the **cloned bytes used for loss computation**, with the source digest checked before optimizer operations.
* `teacher_feature_sha256`: verified teacher feature-array bytes from the read P5 shard.
* `teacher_npy_sha256`: SHA-256 of serialized P5 file bytes.
* `source_row_count`, `student_slot_shape`, `teacher_feature_shape`: bounded paired dimensions.

These receipts allow reviewers to correlate before/after losses with the **same exact frozen student input and teacher target features**. They are checksums and binding evidence, **not independent provenance**, a valid model license, a trained full-size Hepta Stem, calibrated quality, or a production admission receipt.

The result still declares `pretrained_weights_independently_attested=false`, `heldout_sources_independently_attested=false`, `performance_qualified=false`, `real_target_hardware_attested=false`, `production_activation_allowed=false`, `authority=DENY_ALL`, and `release=HOLD_NO_GO`. It does not select a winning Stem or change global Cell/Memory authority.

## Qualification commands

On an authorized, pinned **CPU PyTorch + NumPy** runner (full suite is not represented by a hand-written micro-smoke):

```bash
python3 -m unittest discover -s qa/stem-bakeoff -p 'test_offline_shard_distill.py' -v
python3 -m unittest discover -s qa/stem-bakeoff -p 'test_feature_shard.py' -v
python3 -m unittest discover -s qa/stem-bakeoff -p 'test_multimodal_bridge.py' -v
python3 -m unittest discover -s qa/stem-bakeoff -p 'test_native_latent.py' -v
python3 -m py_compile qa/stem-bakeoff/offline_shard_distill.py qa/stem-bakeoff/test_offline_shard_distill.py
git diff --check
```

The existing `hepta-shared-stem-bakeoff-shadow.yml` runs these on exact pull-request HEAD with pinned CPU Torch and NumPy. Tests cover late producer mutation, in-place Student input, refusal of heldout/source overlaps, and non-authorizing paired receipts.

## Unclosed external blockers

1. **CI:** The new exact-HEAD shadow, blocking-ci, v8-canary, architecture and applicable Rust/Windows/security checks must reach terminal success; queued/pending/old-HEAD runs never count.
2. **Real teacher and license:** approved immutable EmbeddingGemma 2/T5Gemma 2 revisions, licenses, checkpoint inventory and tokenizer/vision/audio preprocessor digests; independently verifiable feature producer.
3. **Independent evaluation:** licensed, disjoint future_1/future_2/OOD source cohorts; source provenance, contamination screening and calibrated lower-confidence bounds.
4. **Full model training:** genuine 150M/300M native Student training beyond synthetic 8-dimensional CPU steps; hardware resource and correctness replay.
5. **Physical performance:** actual batch-once Stem executions and Cell fan-out counts, p95/p99 latency, RAM/VRAM/energy across 1–4096 Cells, and retriable fault/rollback tests.
6. **Promotion:** explicit independent sign-off; no automatic promotion or DENY_ALL removal.

Only declare each blocker closed when an auditable exact-HEAD evidence artifact exists. Never use simulated receipts as production authorization.
