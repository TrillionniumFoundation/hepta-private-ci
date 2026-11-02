# V12: actual raw-media recovery and strong-audio availability

**Real waveform preparation is now executable. A pretrained strong-audio result remains blocked.** This round does not repeat the 504-fit weak-feature search, reconstruct absent v6 weights, or label historical media as new recordings.

The fixed V3 source remains CREMA-D upstream commit `1658cd342dff90010aa843eaeebd53610a08b1dc`. Its media manifest binds original `VideoFlash/*.flv` URLs, integer sizes and SHA256. The original V3 raw-media cleanup receipt records deletion after feature extraction; those 48 historical feature arrays cannot recover the original waveform or a stronger encoder representation.

A separate, already present project contains genuine CREMA-D FLVs at `/workspace/scratch/65d0df4e0cbd/video_raw_r2_media`. Its unfinished raw-video campaign retains `COHORT.json` SHA256 `b65adcd877528b7cb5b81962ff3662c59ee1e144c26034b8a4e1d5e6426cf37a`, with 288 training, 72 historical validation and 96 old-test recordings. We read that project's media without changing it. Its acquisition directory was growing during inspection; earlier 34-path enumeration included eight zero-byte files, which were not admitted as media. This round freezes a precise **31-recording snapshot**, not the directory's eventual contents.

| Availability question | Actual evidence |
|---|---|
| Genuine bytes now usable | 31 FLVs, 10,726,397 bytes; every size/SHA matches the frozen cohort |
| Population and split | Four actors, all historical training; no validation/test media inspected |
| Actual decoder execution | All 31 decode as native 44.1kHz mono audio with genuine video streams |
| Prepared prefixes | 68 real 1/2/3-second prefixes; 25 longer-than-source requests rejected without padding |
| Actual retained waveform | `local_raw001/ACTUAL_PREFIX_SAMPLE.npz`: one 1-second, 16kHz float32 prefix from `1002_DFA_ANG_XX` |
| Strong pretrained weights | Not present or downloaded; no pretrained inference or head fit |
| Original v6 ledger/strong reference | Still unavailable; original strong-frontend and independence gates remain HOLD |

`probe_local_media.py` actually verifies source bytes, invokes ffprobe/ffmpeg, crops native PCM at the declared audio prefix **before** resampling, and records all native/prefix output hashes. A real future-NaN intervention leaves its accepted prefix bitwise unchanged. Resampling uses fixed zero extension only for the finite filter boundary after cropping; it never pads a short recording to manufacture a legal longer prefix. Full-file offline decoding is preparation, not proof of streaming decoder causality or reduced acquisition cost. Source-length availability recorded in this preparation report is not an inference input or an early EOF oracle. Audio-prefix time here is relative to native audio start; integrating a joint AV controller requires an explicit shared source clock.

The complete enclosing worker cost is **5.701940 CPU seconds / 6.753022 wall seconds**, including waited ffprobe/ffmpeg children. The internal timer is already contained in that receipt and must not be added again. Scanning, source lookup, network probes, reporting and independent checks are outside this cost. No energy or full-family memory estimate is substituted.

## A concrete stronger baseline path

The publisher provides a raw-audio emotion encoder at [audEERING's fixed model revision](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/README.md). Its [official safetensors pointer](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim/blob/6eba34a2485ea31cb03600241787c3a5edab8626/model.safetensors) declares SHA256 `efa5ac1a13b2d2f42182738e44794b1eb4c0cdd221a8b4ae11304c3a5f5fae95`; the displayed size is 661 MB. The model's research license is CC-BY-NC-SA-4.0. It supplies pooled 1024-dimensional features and arousal/dominance/valence regression, so it is a plausible **encoder candidate**, not a ready five/six-class CREMA-D or audiovisual binding classifier. These facts are primary-source metadata, not observations on locally recovered weights. Exact config/preprocessor byte hashes remain unavailable.

The executable route is therefore:

1. In an environment with permitted access, obtain that exact revision's safetensors, config, preprocessor and license; verify the actual weight SHA and pin the other file hashes. Load only local safetensors and the publisher-documented architecture, without remote-code execution or a random-weight fallback.
2. Supply compatible Transformers/safetensors. This environment has reusable Torch via `/tmp/hcsn-torch-runtime`, but these two dependencies are absent. No installation or model execution is claimed.
3. Run the frozen encoder independently on each actually accepted 16kHz prefix, normalizing that prefix alone. Reusing a full-recording bidirectional embedding for an earlier prefix would leak future input. Charge every encoder rerun and preparation step.
4. Obtain complete declared development and calibration media, retaining actor/recording separation. Fit the class readout using training labels; select on development selection data and fit empirical correctness on separate calibration data. Keep five-class emotion and semantic binding identities explicit. Do not convert three regression dimensions directly into the missing class/reference labels.
5. Recompute strong-audio and common-head references on the same subsequent qualification cohort. The original complete v5/v6 exclusion ledger is still needed to call that cohort independent; the 31 raw recordings here are only historical training material.

`OFFICIAL_AUDIO_CANDIDATE.json` records the exact candidate, missing assets/dependencies and the absence of any local inference. Two actual local HEAD probes—one original-media URL and this exact official weight URL—each timed out after 20 seconds. **No HTTP status or policy-denial response was received.** No source byte was downloaded, no proxy setting changed, and no mirror or retry was attempted. `NETWORK_ATTEMPTS.json` records these limits rather than asserting that the public assets disappeared or were explicitly denied. Primary-source model-card retrieval through the search service is metadata access, not a successful transfer into this execution environment.

`PARTIAL_HISTORY_INDEX.json` conservatively indexes 1,176 unique IDs from three existing manifests. It includes planned/historical allocations, not an authenticated complete v5/v6 execution ledger. Being outside this index proves neither absence of historical use nor new-object independence. Old branch/bundle-name searches were not repeated.

To reproduce the completed local-media preparation, retain the frozen `HISTORICAL_COHORT.json`, point `--media` to the genuine matching files, and use new output paths:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_v8_execution_20261101.economics.worker_cost \
  --out /new/output/raw_cost --timeout 180 --sample-interval .5 -- \
  python -m experiments.hcsn_v12_followup_20261101.frontend.probe_local_media \
  --cohort experiments/hcsn_v12_followup_20261101/frontend/local_raw001/HISTORICAL_COHORT.json \
  --media /path/to/genuine/crema_media --out /new/output/raw_preparation
```

The source directory is live, so another run can discover additional historical training files. Per-run identities, accepted outputs and rejected shorter prefixes are retained explicitly. The original data-license notice is included in `LICENSE_CREMA_D.txt`; source URLs and attribution travel with every recording record. No production activation or new scientific acceptance is established.
