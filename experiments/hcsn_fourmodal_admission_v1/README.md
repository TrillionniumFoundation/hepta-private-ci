# HCSN P3 four-modal source admission (research-only)

**Status: DRAFT / DENY_ALL.** An executable, fail-closed **data-source preflight**, not a trained four-modal encoder, certified annotation audit, or successful P3/P4/P5 scientific gate. Successful receipts explicitly report real_four_modal_quality_established=false and production_activation_allowed=false.

## Scope

This gate checks that each sample has all four declared modalities (text, image, audio, video), four distinct versioned encoder identities, SHA-256-matched source bytes, event/entity pairing and a common timestamp window. Source files are verified as nonempty UTF-8 text, fully decoded PNG/JPEG/WebP image, completely read PCM WAV audio, or a video with a probed stream and at least **one actually decoded frame** confirmed by FFmpeg framecrc. It rejects actor, session, event, source, path or identical-modality-content reuse across train/val/test splits.

The submitted manifest declares actor/entity/event labels, timestamps and encoder digests. Those metadata values **are not independently proven** by this tool: raw annotation provenance, real encoder checkpoint hashes, whole-video decoding and any task-quality evaluation remain distinct P3 blockers. Byte-identical captions across splits are conservatively rejected even if their duplication was benign. The tool also assumes an immutable, trusted source directory during validation.

## Strict manifest schema

The root JSON object has exactly four fields: schema_version, max_skew_ms, encoders, samples. The schema_version must be hcsn-fourmodal-source-v1. The max_skew_ms must be a nonnegative integer no greater than 1000. The encoders object must contain exactly text, image, audio, video, each with encoder_id and revision_sha256 (distinct IDs and 64-hex lowercase revisions).

The samples array must contain one or more entries and at least one entry from each split: train, val, test. Each sample has exactly sample_id, split, actor_id, session_id, event_id, entity_id, label, modalities. Each modality record has exactly path, sha256, source_id, event_id, entity_id, start_ms, end_ms. Paths are relative to the provided asset root and may not contain traversal, symlinks or noncanonical components. Timestamps are integer milliseconds on a common timeline; the windows must overlap within max_skew_ms. Event/entity identifiers must match across all four modalities.

Invalid data, duplicate JSON keys, NaN/Infinity, changed file hashes, missing decoders and incompatible media formats are refused. Requires Python 3.11+, Pillow and ffmpeg/ffprobe. The current small research gate accepts PCM WAV audio and PNG/JPEG/WebP images; video formats depend on installed FFmpeg.

## Reproduce

Run from repository root:

~~~bash
python -m unittest -v experiments.hcsn_fourmodal_admission_v1.test_manifest_gate
python -m experiments.hcsn_fourmodal_admission_v1.manifest_gate /path/to/frozen_manifest.json /path/to/immutable_assets
~~~

An accepted run exits 0 and emits a canonical-manifest SHA-256 descriptive receipt. Rejection exits 2 with status=DENY and its explicit code. Freeze the manifest identity and registration protocol **before** accessing evaluation results. No production admission occurs.

## Executed, bounded local evidence

- 16/16 unittest methods passed locally; zero skipped. Synthetic fixtures generate three temporary samples across train/val/test, with actual text, PNG, WAV and MP4 data.
- Negative tests include missing or duplicate encoder/modality, event/entity shuffle, invalid and non-overlapping times, actor/session/source/split leakage, edited bytes, disguised media, duplicate JSON keys, invalid numeric types, symlink and traversal.
- One specific fail-open witness was independently reproduced: FFmpeg process exit 0 with no decoded frame record was accepted by the initial version. The amended framecrc gate refuses it; the negative test fails before the repair and passes after it.
- This test suite does **not** validate real four-modal task quality, full corpus provenance, model training, native Rust/GPU execution, joules, or foundation-scale generalization.
- All changes are contained in experiments/hcsn_fourmodal_admission_v1; existing HCSN research and production Rust, permissions, CI workflows, checkpoints and historical negative evidence remain unchanged.

## Remaining P0-P5 blockers

P0: complete HX coupled obstacle/fixed-point, interval-certified numerics and low-precision gradients. P1: causal improvement for locally slope-matched Call/Risk/Margin under equal resources. P2: verified repeated-event long memory and task benefit. P3: independently audited real four-modal sources, independently run encoders, pairing-shuffle controls, cross-modal retrieval, temporal grounding, missing-modal and OOD performance. P4: native Rust/GPU, 64/256/1024/4096 Cell performance, energy and crash recovery. P5: compute- and quality-matched win against tuned Transformer/SSM. **all_blockers_closed=false; production_activation_allowed=false.**
