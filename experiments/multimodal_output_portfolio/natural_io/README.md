# Natural-input ingestion and pretrained codec evidence

Status: **one real, licensed source recording successfully ingested; pretrained TAESD image/video-frame, T5 text and DAC audio interfaces executed separately; no joint multimodal generation, training, semantic-quality or NDU-benefit validation**.

This standalone directory does not modify the registered v3 source, protocol, training arms, or confirmation data. Its [receipt](evidence/ingestion-001.json) records actual `ffprobe` output, tensor statistics, commands, source integrity, and artifact hashes.

## Source and attribution

- Source: [Wikimedia Commons file page](https://commons.wikimedia.org/wiki/File:Lachender_Hans_(Tierpark_Zittau).webm), [pinned page revision](https://commons.wikimedia.org/w/index.php?title=File:Lachender_Hans_(Tierpark_Zittau).webm&oldid=1138468463).
- Creator: **Fiver, der Hellseher**; the source page declares the recording to be the uploader's own work, created 2022-05-08.
- Media and the retained derivatives: [Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Preserve attribution, the license link, and the listed transformations when distributing them. No endorsement is implied.
- The caption comes from the existing human German Description field; it was not translated or generated. It is a file description, not a synchronized speech transcript.
- The exact original URL and source SHA-1 from Commons are pinned in `ingest.py`; the downloaded bytes were independently SHA-256 hashed.

Source SHA-256:

```text
bc957c8a0382d9a4d2d54acbfc61c61e5fd57bcef909364bad3f41a5957c91ef
```

## Observed result

| Item | Actual observation |
|---|---|
| Original media | 12,123,649 bytes; 10.483 seconds |
| Original video | VP8, 3840 × 2160, 25 fps, 262 decoded video frames |
| Original audio | Vorbis, 44,100 Hz, stereo |
| Audio tensor | float32 `[1, 167602]`, resampled to 16,000 Hz mono, finite and nonconstant |
| Image tensor | float32 `[3, 144, 256]`, one natural-video frame at 2 seconds |
| Video tensor | float32 `[4, 3, 72, 128]`, four distinct temporal frames from original seconds 1–5 |
| Human text representation | uint8 `[55]` UTF-8 bytes; this is byte I/O, not a semantic text encoder |
| Temporal check | Mean absolute difference between adjacent normalized frames: 0.0795992389 |
| Elapsed ingestion | 9.53 seconds for the completed run; not a neural inference benchmark |

All tensors are finite and nonempty. The image was visually inspected as a frame of the recorded scene. Audio's 167,602 resampled PCM samples correspond to the decoded audio stream; container duration, video timing and codec frame counts are retained separately rather than treated as interchangeable sample counts.

The image is extracted from the same natural video, and the audio is its recorded soundtrack. These are four typed representations of one recorded event plus a human description, **not four independently acquired modalities**. The four-frame derivative comes from a real temporal recording; it is not a repeated still image or synthetic animation.

## Reproduce

With Python, NumPy, Pillow, FFmpeg and FFprobe installed:

```bash
python experiments/multimodal_output_portfolio/natural_io/ingest.py \
  --output-directory /tmp/hepta-natural-io-new \
  --receipt experiments/multimodal_output_portfolio/natural_io/evidence/new-receipt.json
```

Use a new output directory and receipt filename; completed receipts are never overwritten. The script downloads only the fixed public original, imposes a 20 MiB download cap, verifies the pinned source size and SHA-1, executes extraction, and writes hashes and `ATTRIBUTION.json`. Normal shell network access was blocked in this session; the completed run used the approved network-enabled execution path.

The reproducible intermediate media and tensors for the recorded run are in `/tmp/hepta-natural-io-001`. Binary media are deliberately outside git. The original clip and image/audio/video derivatives retain the source license independently of the repository's code license.

## What this evidence closes

The ingestion check demonstrates a working input path for actual captured audio/video, a sampled image, and an existing human description. That check does not load a pretrained checkpoint, feed the eight-class synthetic generator, generate any neural output, evaluate quality, measure generalization, or close the natural-data foundation-model blocker. The remaining concrete conditions are in [the natural-data plan](../v3/NATURAL_DATA_PLAN.md).

## Executed pretrained image/video codec check

A separate [codec script](codec_smoke.py) and [immutable receipt](evidence/codec-001.json) now execute the pretrained [official TAESD](https://github.com/madebyollin/taesd) encoder and decoder on the verified natural tensors. Both code and weights are fixed to commit `fdbae2df989db95761f482efb8977e1182fb68d2`. Their original MIT license and exact file URLs, sizes and SHA-256 hashes are retained. The script verifies each asset before import/loading, uses explicit `torch.load(..., weights_only=True, map_location="cpu")`, and loads strict state dictionaries. All 2,445,063 pretrained parameters remain frozen.

| Actual roundtrip | Input → latent → output | Clipped RGB MSE | PSNR, peak 1 |
|---|---|---:|---:|
| Recorded image | `[1,3,144,256]` → `[1,4,18,32]` → `[1,3,144,256]` | 0.0132458812 | 18.7792 dB |
| Four recorded video frames | Four batch-one calls, each `[1,3,72,128]` → `[1,4,9,16]` → `[1,3,72,128]` | 0.0115034908 aggregate | 19.3917 dB aggregate |

Raw decoder outputs and clipped outputs are both scored in the receipt. Latents stay float32 without quantization. PNG display files clip RGB to `[0,1]` and round to eight bits; metrics above precede PNG quantization. Every tensor is finite and the original spatial dimensions are recovered. Visual inspection shows substantial loss of fine mesh/detail; this is interface evidence, not a high-fidelity quality claim. The four frames are decoded independently, without a temporal model.

Five actual encoder/decoder roundtrips ran on CPU with batch size one and one Torch intra-op/inter-op thread, without hidden warmup calls. The measured forward calls total **0.93395 s wall / 0.92421 s process CPU**. The entire main function, including asset checks, loading and artifact export, took **1.65787 s wall / 2.62433 s process CPU**; child-process CPU for export is separately recorded. Module-import startup is outside those measurements. Actual hooks count **350 Conv2d calls and 37,079,285,760 convolution MACs**; activations, interpolation, residual additions and memory operations are excluded from that MAC count and included in measured runtime. This is one run, not a latency benchmark or comparison.

Reproduction with the existing PyTorch/NumPy/Pillow/FFmpeg environment:

```bash
python experiments/multimodal_output_portfolio/natural_io/codec_smoke.py \
  --assets-directory /tmp/hepta-taesd-assets \
  --input-receipt experiments/multimodal_output_portfolio/natural_io/evidence/ingestion-001.json \
  --output-directory /tmp/hepta-natural-codec-new \
  --receipt experiments/multimodal_output_portfolio/natural_io/evidence/codec-new.json
```

The asset directory is reused only after integrity checks; missing pinned assets are downloaded. Use a fresh output directory and receipt. On another machine first reproduce ingestion, then pass its receipt, which identifies that machine's actual input paths.

Completed-run artifacts are in `/tmp/hepta-natural-codec-001`: `image-comparison.png`, `video-comparison.png`, individual reconstructions, `video-reconstructed.webm`, float32 latent/output tensors and attribution. The exported VP9 sequence was independently probed as four frames at 128×72, 1 fps, four seconds. Original media and codec reconstructions preserve CC BY-SA 4.0 attribution; upstream code and weights retain MIT. Binary model/media artifacts stay outside git.

The TAESD check closes only the image/video-frame portion of the pretrained-codec interface condition. It does not execute audio/text codecs, train a model, predict unseen natural outputs, demonstrate semantic understanding, optimize an NDU objective or validate a foundation model. The original ingestion script and its receipt were not changed.

## Executed pretrained text interface

The separate [T5 script](text_model_smoke.py) and [original execution receipt](evidence/text-interface-001.json) now exercise `google-t5/t5-small` on the existing human German description. Model revision `df1b051c49625cf57a3d0d8d3863ed4d13564fe4` is fixed; the Apache-2.0 model card, config, tokenizer and safetensors checkpoint have recorded upstream identities and verified hashes. Loading uses `local_files_only=True`, `trust_remote_code=False` and `use_safetensors=True`. The isolated runtime uses PyTorch `2.5.1+cpu` and Transformers `4.57.1`; its complete package versions are in the receipt.

| Actual interface | Observed result |
|---|---|
| Human caption tokens | int64 `[1,25]` with attention mask |
| Encoder hidden states | float32 `[1,25,512]`, finite |
| First decoder logits | float32 `[1,1,32128]`, finite |
| Autoregressive output | int64 `[1,26]`: one start token plus **25 new tokens including EOS**, under a cap of 32 |
| Decoded text | Identical to the human input description; no translation/summarization task prefix |
| Measured inference | 0.598949 s wall / 0.598629 s process CPU for all three interface operations |

These are actual neural encoder, decoder and bounded generation calls. The reproduced input string is not evidence of semantic adequacy, translation, summarization or unseen-caption prediction. No training or NDU optimization was performed.

An [independent read-only review](evidence/review-text-interface-001.json) verified the source, seven assets, implementation module, two output files, five saved tensors and the caption's hash binding to the ingestion receipt. It did not rerun inference. An independent configuration-based calculation exactly reproduces the recorded **2,573,074,432 Linear MACs**: three encoder passes, 26 decoder token steps, and two sets of cross-attention context K/V projections. This includes the standalone encoder probe, the first-logits probe and generation; it is not the cost of one encoder call. Attention matrix products, embeddings, softmax/activations, normalization and control are excluded from this Linear-only count and remain included in the measured inference runtime.

The runtime model has **60,506,624 unique parameters**. The checkpoint contains 256 additional legacy cross-attention relative-bias values; the pinned official implementation explicitly ignores that unused key. This is documented in the review and is not a strict all-checkpoint-keys loading claim.

To repeat with the recorded compatible runtime and a fresh output/receipt:

```bash
/tmp/hepta-natural-text-env/bin/python \
  experiments/multimodal_output_portfolio/natural_io/text_model_smoke.py \
  --assets /tmp/hepta-t5-small-assets \
  --caption /tmp/hepta-natural-io-001/human-description.de.txt \
  --output /tmp/hepta-natural-text-new \
  --receipt experiments/multimodal_output_portfolio/natural_io/evidence/text-interface-new.json
```

The completed run's tensors and decoded text are in `/tmp/hepta-natural-text-001`. Current-fixture provenance is verified: its caption bytes match the earlier human-description artifact. The script's fixed German/Commons provenance metadata must not be reused as a verified declaration for arbitrary replacement captions. This text interface is separate from a shared natural four-output model; the latter remains unimplemented and unvalidated.

## Executed pretrained audio codec interface

The [audio script](audio_codec_smoke.py) now performs an actual DAC roundtrip on the fixed first **32,000 samples / two seconds** of the verified 16 kHz mono recording. Selection uses the fixed prefix, not reconstruction quality. The final [003 execution receipt](evidence/audio-codec-003.json) and [independent verification](evidence/audio-codec-independent-verification.json) preserve the input hash, source attribution, model assets, runtime, saved integer codes and decoded waveform.

The official Descript source is fixed to commit `c7cfc5d2647e26471dc394f95846a0830e7bec34`; the native 16 kHz weights are release `0.0.5`, with SHA-256 `95ab7176b67137d4d4c6c54b8d6ef3cea797faec228cb03ad084badcad570b4d`. These are the author's original release assets, not the alternative Hugging Face mirror considered during planning. The author explicitly licenses the model weights under MIT; the source statement, license text and hashes are retained. The actual model has **74,175,906 frozen parameters**, 12 codebooks of size 1,024 and hop length 320.

All three attempts remain visible:

| Attempt | Recorded result and interpretation |
|---|---|
| [001](evidence/audio-codec-001.json) | Failed after neural decoding because the returned waveform was shorter than the 32,000-sample input. This original receipt did not record the exact decoded length and remains unchanged. A separate later upstream probe using 32,000 literal zeros returned 31,992 samples, matching the transposed-convolution length calculation; that is independent boundary evidence, not a retroactively inserted measurement of attempt 001 |
| [002](evidence/audio-codec-002.json) | Added one fixed 320-sample zero hop on the right: input length 32,320, decoded length 32,312, retain the first 32,000 samples. The rule uses no left crop, no reference-dependent shift/gain search and no quality-based segment selection |
| [003](evidence/audio-codec-003.json) | Retained that adapter and loaded with explicit `torch.load(weights_only=True, map_location="cpu")`, validated constructor metadata and strict state loading: 322 entries, no missing/unexpected keys, no custom safe globals or unsafe fallback. Independent verification confirms **all seven saved artifacts are byte-for-byte identical to 002**, including codes, float32 reconstruction and WAVs; the receipts themselves differ |

The decoder's input is rebuilt **from the saved integer codes and frozen codebooks**, rather than bypassing quantization with an encoder activation:

| Actual stage | Shape / observation |
|---|---|
| Original audio prefix | float32 `[1,1,32000]` |
| Input with fixed right-zero guard | float32 `[1,1,32320]` |
| Integer codes | int64 `[1,12,101]`, observed values 0–1022 |
| Code-derived quantized latent | float32 `[1,1024,101]`; maximum absolute difference from the encoder's quantized latent `1.9073486328125e-6` |
| Raw decoder output | float32 `[1,1,32312]` |
| Retained reconstruction | float32 `[1,1,32000]`, all finite; range approximately `[-0.846917, 0.949493]` |
| Listening derivative | 16 kHz mono PCM16, 32,000 samples, no clipped samples |

The measured reconstruction is **not lossless or quality validated**. Same-index float32 comparison before PCM rounding yields MSE **0.0203313247652315** and SNR **−2.392409 dB**, defined as `10 log10(mean(input²) / mean((output−input)²))`. No shift or gain was fitted to improve this score. The negative samplewise SNR is retained as an observed limitation of this fixture and alignment; perceptual quality and corpus-level codec performance were not established.

The final run used CPU with four Torch threads and no warmup/repetitions. It took **5.45583 s wall / 10.68806 s process CPU**, excluding earlier dependency installation and weight download. Encoding/quantization, code-to-latent reconstruction and decoding have separate timing records. These are measured timings for one interface run, not an NDU or codec-speed comparison; no operator-level audio MAC total is claimed.

To repeat with the recorded compatible runtime and fresh output/receipt:

```bash
/tmp/hepta-audio-codec-env-001/bin/python \
  experiments/multimodal_output_portfolio/natural_io/audio_codec_smoke.py \
  --input-directory /tmp/hepta-natural-io-001 \
  --weights /tmp/hepta-audio-codec-001/weights-16khz-0.0.5.pth \
  --upstream-license /tmp/hepta-audio-codec-001/LICENSE-MIT-Descript.txt \
  --output-directory /tmp/hepta-audio-codec-001/reconstruction-new \
  --receipt experiments/multimodal_output_portfolio/natural_io/evidence/audio-codec-new.json \
  --threads 4
```

Final listening/tensor artifacts are in `/tmp/hepta-audio-codec-001/reconstruction-003`; they retain the Commons source's CC BY-SA 4.0 attribution, while the model code/weights retain MIT. The isolated dependency versions and `pip check` result are in the receipt. This closes a **single-fixture audio codec interface**: actual recorded waveform → integer codes → code-derived latent → decoded waveform. It does not synthesize speech from a caption, predict unseen audio, train a generator, invoke the NDU controller or establish natural-data generalization. Together with the other interfaces it supplies concrete components; a shared conditional model, independent corpus, temporal video model and natural NDU-training experiment remain outstanding.
