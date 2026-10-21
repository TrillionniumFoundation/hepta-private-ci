# P14 — source-preflight media byte budget

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Exact parent P13 [#3017](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3017) `0e5908dd16ff33b4e017c87be8c65c14c90736cc`. Independent additive child, no prior branch or `main` mutation.

## Resource-bound gap

P12's sealed media copy checks 128 MiB/file and 512 MiB/batch, but `teacher_forward.validate_records` ran first and hashed all candidate input files with only an individual 128 MiB bound. An oversized batch could cost gigabytes of I/O before being rejected by the later media seal, and during that interval the actual teacher model could already have been loaded.

## Correction

- Share the exact `MAX_MEDIA_BATCH_BYTES` limit from `teacher_media_seal`, so validation and the later copy cannot silently drift.
- Bound the summed size of *all references* (including repeated files) before hashing each next file and before any model/tokenizer import or load.
- If a file grows or shrinks after `stat`, reject a byte-count mismatch instead of completing an unbounded hash. This is an integrity and resource-fencing improvement, not independent source provenance.
- Add standard-library tests covering a 2-reference oversubscribed batch and an adversarial source stream that grows between size inspection and hashing. No large model, external download or GPU is used.
- Run the existing exact-HEAD Stem Shadow evidence-contract + CPU Torch suite and all original platform/architecture/V8/blocking gates; do not reuse earlier SHA passes.

## Scope / blockers

P14 preserves the 421M control, EmbeddingGemma 2 multi-modal perception/Memory Stem, T5Gemma 2 Encoder comparator, 150M/300M Hepta student bake-off, and per-Cell Gate/light Adapter/Task-Action-Value Head/Local State/external Memory. Genuine licensed checkpoints, external future/OOD cohort attestation, full training, physical 1–4096 Cell GPU p95/p99/energy, RustSec/cargo-deny remediation, original CI, code owner review and production admission remain blockers. No authority or Memory actuation is granted.
