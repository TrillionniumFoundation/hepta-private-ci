# P15 — freeze EmbeddingGemma media routing at preflight

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.** Exact P14 parent
`14a59ce1fe7ef54ac096cb491376c8639c065487` (#3021). This is a new
stacked child; neither parent nor `main` is mutated.

## Reproduced trust-boundary gap

`teacher_forward.validate_records` returns materialized preflight
conversations and an ordered source-byte digest. Before P15, the EmbeddingGemma
path passed the **caller-owned mutable `records`** to
`sealed_media_inputs` only after loading the processor/checkpoint.

If a callback deleted the last media field while the model loaded, the guard's
media-detection branch would treat the now text-only records as proof that no
media seal was necessary. It yielded the old preflight conversation containing
the original media path directly to the processor. A caller could also append
or remove rows after validation. This is an input-custody bypass; it does not
require altering a SHA256 digest.

## Change

- Derive all media paths, modal keys and text from the previously validated
  conversation **before** loading the checkpoint. The guard receives these
  newly materialized rows, never the caller's mutable rows.
- `sealed_media_inputs` independently checks exact row count and per-row
  modality layout against the preflight conversation. If a caller supplies
  changed records, the guard fails closed instead of silently choosing its
  text-only fast path.
- Test the erased-media-key bypass, an appended row, and an end-to-end fake
  EmbeddingGemma processor/model load which mutates caller input between
  preflight and preprocessing. Assert the processor still receives only the
  temporary sealed bytes, original text, original batch cardinality and exact
  source digest. No real model weights or network are needed.

## Admission

Run the *new exact P15 HEAD* CPU and stdlib Stem Shadow suites, plus the
original full `blocking-ci` (including security and platform Bazel),
architecture convergence and V8. Neither ancestor HEAD checks nor the
hermetic fake-model tests prove genuine teacher quality or independent
provenance. Approved licensed EmbeddingGemma 2/T5Gemma 2 checkpoints,
independently sourced future/OOD splits, full 150M/300M student training,
1–4096 Cell hardware p95/p99/energy and code-owner review remain blockers.
Keep the frozen 421M cognition control, shared perception/Memory Stem, encoder
bake-off and per-Cell Gate/Adapter/Task/Action/Value/Local State/external
Memory separation unchanged. No release, production activation or authority.
