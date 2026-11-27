# P29 — byte-sealed T5Gemma 2 text+image Encoder research arm

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This is a source-contract experiment,
not proof that a pretrained T5Gemma 2 checkpoint actually executes correctly
with images. Follow-up must run a genuine pinned checkpoint under an isolated
offline worker and independently validate its output/quality.

## Design and immutable parent

P29 is strictly stacked on P28 [#3078](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3078)
exact parent `2d52e19ea84e354f365f9dc233cebcffb0edd377`.
P27/P28 and `main` remain unchanged.

The previous `teacher_forward.py` T5Gemma2 arm accepted only text and could
not perform a comparative text+image Encoder experiment. Hugging Face's
T5Gemma 2 Encoder accepts `pixel_values`; the documented
`AutoProcessor(text=..., images=...)` path is applicable, subject to exact
dependency/model versions and real-checkpoint confirmation.

## Strict source and execution boundary

- Text-only T5 path remains unchanged.
- Image arm requires a **homogeneous** batch (1–8 rows) of exactly
  `{"text","image"}`, one `<start_of_image>` marker per text and one
  local relative regular image per row. Reject audio/video, mixed batches,
  image marker without image and additional markers.
- Hash original source bytes and record layout. Reuse owner-private
  `sealed_media_inputs` after model loading; mutations between initial
  digest and file seal reject. Decode **only sealed** image paths to
  in-memory RGB copies, with a 16,777,216 decoded-pixel cap per image.
- Invoke the pinned local HF processor with the sealed text + image objects,
  require finite 4D `pixel_values` and bounded attention mask, pass
  `pixel_values` through the actual T5 `get_encoder()` call.
- The original text-only tokenization and EmbeddingGemma 2 multimodal
  paths remain distinct, with no remote URLs, no `trust_remote_code`,
  no new model weights and no per-Cell foundation copies.

## Qualification

Fake Processor/Encoder CPU tests assert sealed original bytes, real
`pixel_values` argument forwarding, source digest, and mutation rejection.
These are **interface/security tests only**, not real T5 vision accuracy.
A pinned actual T5Gemma 2 checkpoint, dependency version, licensing,
heldout/OOD/negative-transfer quality, GPU fan-out p95/p99/memory/energy,
Rust/Cargo/Bazel/V8 exact-head CI, rollback and independent authorization
must still be verified. Remain DENY_ALL and do not merge to main.
