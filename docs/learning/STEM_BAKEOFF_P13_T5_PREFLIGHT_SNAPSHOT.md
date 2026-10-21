# P13 — freeze T5Gemma 2 text at teacher preflight

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. Additive child of P12 [#3011](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3011) at exact parent `84c1fbd9f0506d7a2b5926b24e5489f00ac91fdf`. No rewrite or merge of an existing source branch.

## Proven integrity gap

`run_forward` binds the ordered source-manifest SHA-256 to the text from `validate_records`. For the T5Gemma 2 path it later passed `[row["text"] for row in records]` directly to its tokenizer *after* loading model/tokenizer objects. A caller-side mutation or loader callback could alter the text or number of rows after the evidence digest was computed, giving a misleading source receipt. P12 already seals EmbeddingGemma 2 media bytes, but did not cover this T5 text re-read.

## Source correction and regression

- The T5Gemma 2 tokenizer now receives only the immutable text strings materialized by the validated conversation snapshot, never re-reading mutable caller-owned records.
- Forward output cardinality and returned `batch_size` bind to the exact preflight snapshot rather than the mutable original list.
- A hermetic, CPU Torch, no-checkpoint/no-network test mutates both the first text row and the batch length during the simulated T5 checkpoint load. It must observe precisely the preflight text, one forward, the original digest and a one-row receipt.
- The already existing Stem Shadow workflow executes this test in its Torch job. The source and tests require an **exact-P13-head** result before claiming qualification.

## Admission and blockers

The 421M cognition control, EmbeddingGemma 2 Perception/Memory Stem, T5Gemma 2 Encoder competitor, Hepta 150M/300M students and per-Cell Gate/light Adapter/Task-Action-Value Head/Local State/external Memory boundary are unchanged. No model weights or real forward were downloaded or qualified. Independent license/checkpoint/source evidence, future/OOD cohorts, full student training, real GPU p95/p99/energy and all source-head blocking CI, V8, architecture, Cargo/RustSec/security and review gates remain mandatory. This source-integrity correction cannot promote Stem or Cell authority, grant Memory mutation or unblock production.
