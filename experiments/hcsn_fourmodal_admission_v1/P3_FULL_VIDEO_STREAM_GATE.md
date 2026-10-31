# HCSN P3 full-video-stream source integrity gate

**Research-only / Draft / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false**

## Exact provenance and changes

- Base PR #4458 immutable HEAD: `b07871a42421fd63a68f7ce9a06124b3f44c5e04`.
- Original `manifest_gate.py` verified source blob `717b20c2fba26596a6fdef5429f48f5e3dcdf9fc`.
- Patched remote blob `0142a4521bc42a28dedfe46c4afc9ef5c69fe13a`, byte-identical to locally executed source.
- New test remote blob `8410ecc460d16ccc443535a5d7e0511cfb404ca3`, byte-identical to locally executed tests.
- Exactly the P3 research decoder file, new tests, and this note; no changes to encoder weights, original media, model training, runtime/authority, Rust, GPU, CI or deployment.

## Failure and minimal repair

The inherited checker ran FFmpeg with `-frames:v 1`. That only attests a first decoded frame; it may accept a clip with declared `nb_frames=3` when only one frame is returned, if FFmpeg reports successful execution.

The new checker:
1. Runs FFmpeg `-xerror` over the **full** selected video stream, not just the first frame.
2. Parses non-header framecrc rows and requires a valid frame record and positive bytes per frame.
3. If FFprobe exposes a positive finite `nb_frames` count, requires exact equality with decoded frame records; invalid or oversized counts fail closed.
4. For missing/`N/A` count, still completely attempts decode and requires at least one frame, but cannot certify the expected temporal length. The audit never treats this as proof of aligned real labels.

## Executed source-exact local evidence

Python 3.13.5, Pillow and native FFmpeg/ffprobe available. The original parent **17/17 tests passed**. Added five tests without changing source: **5 methods with 6 failures/assertions** (first-frame-only acceptance, missing count checks and invalid count admission). Against the modified file, the **combined 22/22 methods PASS, 0 skipped**, including generated real 10-frame MP4 stream decode and inherited complete source/path/hash/split tests. Total `unittest` wall time approximately 3.85 s.

Reproduce on a full checkout:
```sh
python -m unittest -v \
  experiments.hcsn_fourmodal_admission_v1.test_manifest_gate \
  experiments.hcsn_fourmodal_admission_v1.test_video_full_decode_gate
```

This is a source-exact local **relevant-module** test using verified remote parent blobs and the exact committed patch/test blobs, not full repository CI. It is a structural data-integrity improvement, not evidence of label truth, text-image-audio-video encoder training, matched-model quality, hardware efficiency, or scientific P3 admission.

## Still blocked

- **P0:** coupled HX obstacle/QVI, precision certification and hardware gradients.
- **P1:** registered Call/Risk/Margin causal gain with slope/cost matching.
- **P2:** long memory, repeat events, real tasks and temporal recovery.
- **P3:** independently labeled true four-modal data, learned encoders, cross-modal retrieval/grounding, missing-modal and OOD paired comparisons; full-clip metadata may still be wrong.
- **P4:** native GPU and Rust performance/energy/recovery evidence.
- **P5:** quality-conditioned compute-matched foundation-model superiority.
