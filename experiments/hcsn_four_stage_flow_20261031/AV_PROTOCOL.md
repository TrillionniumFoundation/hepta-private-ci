# Stage 4: bounded CREMA-D audio/video/text consistency

This is a new data adapter over a pinned public CREMA-D source. The repository
baseline is public commit `1dc975504276d9f7af3b28f0f7b1c2a79ef66d8d`.
The local v4 cohort manifest is an input identity record; this protocol does not
claim that the v4 implementation or its unfinished results were published.

## Scientific scope

The experiment measures two-sentence acted audio/video/text consistency, with
actor-disjoint training, validation and confirmation. It is neither open-domain
language understanding nor a foundation-model or all-modality acceptance test.
The same prepared observations must be supplied to every compared dynamic core.

CREMA-D source commit: `1658cd342dff90010aa843eaeebd53610a08b1dc`.
Official source and transcript mapping:
<https://github.com/CheyneyComputerScience/CREMA-D>.
Database license: ODbL-1.0; individual contents: DbCL-1.0. Keep this attribution
with derived data and preserve the upstream license supplied with the cohort.

## Fixed observations and model-visible arrays

Each recording contributes two half-second windows, ending 0.5 and 1.0 seconds
after the common start `max(audio_start, first_video_timestamp)`. These cutoffs
do not depend on the eventual recording duration. Audio is decoded at its native
sample rate, cropped to the complete preceding half-second, and only then
resampled to 8,000 samples at 16 kHz. Window-local polyphase resampling uses zero
extension at its edges; it cannot use samples from the next window. Video uses the latest original frame whose
timestamp is at or before the cutoff. No interpolation uses a future frame.

The adapter decodes the whole file offline. This work is metered, and the
prepared-prefix semantics do not imply that sensing or decoding was skipped.
The causal claim concerns features of the decoded signal, not codec lookahead,
streaming decoder feasibility or an observed online decoding latency.
The whole-file duration and frame count remain receipt metadata, never inputs.

Features are fixed and have no pretrained weights:

- Audio: 32 log-mel means and 32 standard deviations per window, with 400-sample
  Hann windows, 160-sample hop, 512-point FFT and an explicitly implemented
  triangular mel bank.
- Video: the top-left 8-by-8 orthonormal DCT of a 16-by-16 grayscale frame.
- Text: the actual words of “Don't forget a jacket” or “I'm on my way to the
  meeting,” tokenized with the declared vocabulary. The `x` slice stores the
  mean token one-hot vector. A trainable linear projection is therefore a
  trainable mean token embedding; this is not a pretrained text representation.
  `text_token_ids` and `text_token_mask` are also retained for an explicit
  embedding implementation. Text is given before the first AV observation.
- Three observed flags identify the available modalities. Missing-modality
  ablations remove both the corresponding content slice and its observed flag.

The model interface is `x[N,2,input_dim]` float32 and `dt[N,2]` float32 with
`dt=(0.5,0.5)` seconds. Modality slices and the vocabulary are in `PLAN.json`.
Any normalization fitted by a model must use training actors only. Metadata
arrays (`sample_id`, `actor`, `emotion`, `sentence_indices`) must never enter
the model. Labels and sample weights are training/evaluation targets, not input
features. An explicit text encoder must also honor the missing-text ablation.

## Balanced relational target and exact information bounds

For each actor and emotion, use both DFA and IOM recordings. Enumerate all eight
triples `(audio_sentence, video_sentence, text_sentence)`. The label is one iff
all three sentence identities agree. Assign each of the two positive triples
weight 3 and each of the six negative triples weight 1. There are eight unique
episodes and total weight twelve per actor/emotion group; repeated weight is
not an independent sample. Optimize and report weighted metrics.

The generator independently enumerates the exact weighted Bayes upper bounds
given observable sentence identities:

| Available information | Best possible weighted accuracy |
| --- | ---: |
| None or any single modality | 1/2 |
| Any two modalities | 5/6 |
| All three modalities | 1 |

These are information ceilings, not promised accuracy for raw feature models.
Any single modality has exactly identical class-conditioned marginals.
Accuracy above chance alone does not show use of all three modalities. Report
every single- and missing-modality result, text/content shuffles, weighted
confusion tables, and the relationship of full performance to the 5/6 ceiling.
Use actors as independent resampling units and retain emotion groups; the eight
combinations from one source pair are correlated. Never treat them as eight new
actors or independent source recordings.

## Identity, preparation and confirmation order

`--freeze-only` writes the complete input manifest and data contract to
`PLAN.json` before extraction. It includes cohort/script SHA-256, exact raw media
SHA-256 and sizes, actor splits, target construction, feature definitions and
information bounds. Resume refuses a changed contract or mismatched cached
artifact. An incomplete artifact is retained and reported; it is not silently
overwritten. Original media are always read-only.

Default preparation materializes only train and validation. Test preparation
requires the path to an already saved candidate-freeze JSON. Its SHA is recorded
with the confirmation data. This adapter records that external artifact; the
study supervisor must verify that it freezes all candidate checkpoints and
selection rules before invoking confirmation. No test scores may select a
checkpoint, feature variant, normalization, threshold or schedule.

```bash
python -B -m experiments.hcsn_four_stage_flow_20261031.av_data \
  --media-root /path/to/crema-media --cohort-path /path/to/COHORT.json \
  --out /new/avt-data --freeze-only

python -B -m experiments.hcsn_four_stage_flow_20261031.av_data \
  --media-root /path/to/crema-media --cohort-path /path/to/COHORT.json \
  --out /new/avt-data --splits train validation

python -B -m experiments.hcsn_four_stage_flow_20261031.av_data \
  --media-root /path/to/crema-media --cohort-path /path/to/COHORT.json \
  --out /new/avt-data --splits test --candidate-freeze /path/to/CANDIDATES.json
```

## Cost and execution constraints

Use one preparation process and one decoder thread. The adapter needs ffmpeg,
ffprobe, NumPy and SciPy, and does not import Torch or load large encoder weights.
Each clip saves a feature and extraction receipt. Split receipts link raw bytes,
feature bytes, clocks and source identities. Preparation-body CPU includes
waited decoder children; interpreter imports require the supervisor's outer
process receipt. Nested clip/body timings must not be added again to the outer
receipt. Acquisition occurred previously and its unobserved cost is not zero.
Device energy is `null`. Whole-file preparation must not be counted as work
avoided by a later READ/WAIT policy.

Before starting a resource-heavy preparation, the supervisor registers the
protocol and admits the job under the shared memory/CPU budget. The adapter's
lightweight tests use synthetic arrays and temporary metadata only.
