# P30 — strict T5Gemma 2 Encoder processor tensor custody

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** No production, Cell,
Memory, System2, NDU, FinalUse or model-quality authorization.

## Immutable ancestry

P30 is strictly stacked on P29 [#3082](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3082)
at exact parent `04c20e9497adb57d0c79c6196d6e0d144b74a014`. No mutation of P29, its ancestors
or `main`.

## Reproduced source-level gap

P29 verified that text+image processor outputs contained finite rank-four image
pixels with the expected batch size, but did not bind the text token IDs and
attention mask to each other or the preflight batch. Its dictionary comprehension
copied *every* returned tensor to the model device, including unused arbitrary
processor fields. A malformed local processor/checkpoint combination could thus
misalign teacher targets and source receipts, allocate unbounded extra GPU
buffers, or reach the Encoder with a mismatched token/image row count.

## New fail-closed guard

- Require exact T5 processor fields: `input_ids`, `attention_mask` and, for
  homogeneous image batches, `pixel_values`. Unexpected fields never cross
  the CUDA transfer boundary.
- Require CPU int32/int64 token IDs, a same-shaped CPU integer/bool attention
  mask, exact preflight row count, nonempty sequences <=8,192, nonnegative
  IDs, binary and nonempty masks.
- Require one CPU floating, finite, three-channel image tensor per input,
  positive spatial dimensions, <=16,777,216 pixels per row and at most
  3*16,777,216 processed pixel elements across the full batch. Check the
  cheap shape/element budget **before** scanning every pixel for finiteness.
- Keep EmbeddingGemma 2's separate multimodal processor behavior and P29's
  sealed local-media and source-digest protections unchanged.
- Add synthetic CPU negative tests for extra tensors, batch/mask drift,
  unbounded expanded pixel views, image channels, nonbinary/empty masks,
  negative/noninteger token IDs, NaN and infinity. Tests require no model
  download, remote code, license acceptance or GPU access.

## Remaining gates

This is only local shape/data and transfer preflight. A *genuine* original
pinned T5Gemma 2 checkpoint and processor may expose a different documented
field contract; do not silently relax the allowlist. Investigate under an
isolated approved offline worker, then extend with independent evidence.
No real checkpoint execution, paired held-out/OOD quality, Cell fan-out GPU
p95/p99/energy, security lock, Windows/macOS/Linux Bazel, rollback or
independent approval has been established by these tests. Exact P30 head
Stem/architecture/blocking-ci/V8 terminal checks are required before any
merge or promotion. Inherited Cargo advisories and Windows failures
remain independently blocking.
