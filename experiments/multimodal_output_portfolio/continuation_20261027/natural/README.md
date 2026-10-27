# Natural output portfolios: continuation on 2026-10-27

This directory contains newly executed, source-separated speech, receipt, and
natural-video experiments. It preserves the failed attempts and the stronger
fixed-policy comparisons. **None of the three natural-task allocation studies
establishes a quality-and-cost advantage over its strong fixed comparator.**
The useful positive result is narrower: when continuation is actually requested,
reusing a frozen speech encoder result preserves the generated transcript and
removes a measurable duplicate encoding cost. The video study also produces
actual reconstructed RGB pixels, rather than treating tracking coordinates or
annotated receipt boxes as evidence of learned image synthesis.

The experiments are bounded components for the P1 natural-task workstream.
They do not integrate the original Hepta neuron, train a general multimodal
language model, demonstrate natural speech synthesis, or establish semantic
video generation. The separate root continuation experiments address original
V6 training and the P0 evidence, risk, execution, and feedback requirements.

## Executed results

CPU and wall numbers below include actual inference and delivery work within
each declared task boundary. They are observations from this CPU environment.
Confidence intervals resample whole speakers, merchant groups, or source
videos; timing repetitions and individual video frames are not independent
replicates.

| Experiment | New qualification sources | Actual result | Conclusion |
| --- | --- | --- | --- |
| Same-model ASR | 12 new speakers, 36 utterances, 432 final transcripts | Tiny beam 5: 51/878 word errors. Cached policy: 52/878. WER difference +0.001139, 95% CI [−0.015194, +0.013566]. | The prespecified 0.01 noninferiority margin fails. The fitted gate never continues, so this qualification does not exercise caching. |
| Forced cache mechanism | 8 fitting speakers; 48 paired episodes | Every episode continues. Reuse: 1 encoder + 2 decoders; reference: 2 encoders + 2 decoders. All paired generated text and encoder hashes agree. CPU difference −0.455896 s, CI [−0.499248, −0.414472]; wall −0.457514 s, CI [−0.500940, −0.415908]. | A verified execution improvement on development inputs, not new-source qualification or learned scheduling superiority. |
| Tiny→base ASR cascade | 16 new speakers, 48 utterances, 576 final transcripts | Fixed base: 89/1071 errors, WER 0.083100. Fitted policy: 115/1071, WER 0.107376. WER difference +0.024276, CI [+0.005540, +0.045261]. | Strong fixed-base gate fails. Validation chooses zero base continuations; learned scheduling adds cost to the same tiny transcripts. |
| Receipt field decoder | 24 new recorded merchant groups; 192 JSON/JPEG delivery pairs | Original rules: 41/96 exact fields, quality 0.544555. Learned base: 31/96, quality 0.443784. All refinement: 33/96, quality 0.452459. Selective: 31/96. | Training changed 793 parameters, but heldout output quality decreased. The selected gate performs no extra region OCR. All qualification gates fail. |
| Missing video frames | 3 new source videos, 36 target frames, 432 generated PNGs | Fixed blend: 24.380028 dB; learned motion mixer: 26.433983 dB. Allocation selects all motion and delivers exactly the fixed learned-flow pixels, with +0.004893 CPU s/frame, CI [+0.002224, +0.006651]. | Motion reconstruction is useful; adaptive allocation does not reduce cost. Strong quality/cost gate fails. |

These are separate experiments with different cohorts. Their WERs must not be
compared as if they were measurements on one common test set.

### Speech costs and controller attribution

The cascade executes every validation quota as a real end-to-end batch before
freezing its budget. It fits five ridge-controller coefficients on only the
first study's 24 fitting utterances, uses 24 new utterances from eight new
validation speakers, then tests on 48 utterances from 16 further speakers.
All previous qualification speakers are excluded. The controller sees tiny
transcripts, confidence, no-speech probability, token count, and public audio
duration. It never receives reference text or base output before allocation.

Its objective is the entropic certainty equivalent with risk coefficient 2 of
`1 − clipped WER − 0.01 × measured CPU seconds`. The price and coefficient are
protocol choices, not empirically estimated user preferences. This is an
offline batch allocation, with subsequent base generation on selected items;
the study does not claim a sequential multi-turn feedback mechanism.

| Cascade policy | Mean CPU s/utterance | Mean amortized wall s/utterance | Tiny calls | Base calls |
| --- | ---: | ---: | ---: | ---: |
| Fixed tiny | 0.864066 | 0.390607 | 48 | 0 |
| Fixed base | 1.952309 | 0.941119 | 0 | 48 |
| Learned budget | 0.943740 | 0.434562 | 48 | 0 |
| Same-quota random | 0.878949 | 0.400249 | 48 | 0 |

Call counts are per timing repetition. Random and learned allocation match the
number of additional model calls, **not exact CPU time or FLOPs**: durations
and generated lengths differ when the quota is nonzero. Here both quotas are
zero, so no allocation advantage is identifiable. Learned minus fixed-tiny CPU
is +0.079674 s (CI [+0.044224, +0.112430]) with identical transcripts. Whole
batch timers reconcile exactly with reported row sums. The reported wall
numbers describe amortized offline throughput, not interactive response latency.
Bootstrap intervals condition on this realized cohort allocation; they do not
rerank an independently resampled cohort.

The first same-model study and its failed qualification are preserved. The
forced-cache mechanism experiment was declared separately on fitting inputs;
it is not a replacement analysis of that failed test. Whisper weights remain
fixed in both speech studies. Repeated equality establishes deterministic
outputs for the tested inputs and decoding configuration, not an equality
theorem for arbitrary stochastic decoding distributions.

### Receipt training and masking

The decoder is a two-layer tanh candidate scorer with 793 trainable parameters,
trained for 800 Adam steps. OCR text and layout create the candidates; selected
OCR boxes determine optional 2× region refinement. Reference boxes do not enter
inference. Actual output consists of field answers plus a JPEG showing chosen
boxes. The JPEG is a delivery visualization, not a learned image generator.

Training loss falls from 0.251906 to 0.004996, but this does not transfer to the
24 new test merchants. Learned-base minus original-rules quality is −0.100771
(CI [−0.186564, −0.012548]). The original rule baseline therefore remains the
better observed policy. All-refinement costs about 2.046636 CPU s/document,
versus 0.660897 for learned base and 0.655699 for original rules. Selective
refinement chooses threshold zero and offers no new outputs beyond learned
base; it also fails the prespecified quality noninferiority gate against all
refinement.

The first training attempt encountered a real missing reference address before
any validation/test generation. The preserved pretest amendment masks missing
references rather than inventing a target. There are 95 observed fitting
fields, of which 92 have OCR candidates. Three observed dates produce no
candidate rows and thus contribute no differentiable training mass. Training
weights are balanced over candidate-supported observed fields after global
normalization; this is not equal mass for every observed field. `field_exact`
is the macro mean of each document's observed-field fraction. All 96 test
fields are observed here, so macro and pooled exact match agree.

Group isolation uses normalized annotated merchant strings and image hashes.
Broader corporate-family or receipt-template separation is not proved. The
source labels support field extraction, not general complex-image reasoning.

### Natural video generation and training attribution

The task is to reconstruct an actual missing middle RGB frame from the frames
two indices before and after it. Inputs are canonical 256-pixel-wide PNG
endpoints. Common source decoding/resizing is separately measured at 6.430729
wall seconds; input PNG decoding, endpoint caches, allocation features, optical
flow, generation, serialization, readback, and bookkeeping are in policy cost.

The expensive generator computes bidirectional Farneback flow and midpoint
warps. A four-parameter sigmoid pixel mixer combines that reconstruction with
the cheap endpoint average. It trains on 18,432 sampled pixels from 36 frames
in three development videos for 400 Adam steps. Training RGB MSE falls from
0.001846989 to 0.001617474. Saved weights are reopened and verified. A separate
ridge controller uses only endpoint differences and phase correlation; no flow
is computed before the expensive-action decision. Cached public endpoint arrays
avoid a second input decode, and their preparation cost is charged.

Historical `david`, `dudek`, and `faceocc2` clips are explicitly development
data; some were historical test clips. The only new qualification source
clusters are `realshort`, `vtest`, and `cockatoo`. Rounded equally spaced targets
initially allowed a short clip's target to appear as another example's public
endpoint. Independent review caught this before any frame preprocessing or
model output. A recorded pretest amendment assigns all targets to residues 2
or 3 modulo 4 and endpoints to residues 0 or 1. The final manifest and an
independent source-video reconstruction verify zero overlap across all roles
within each clip. Frames still share scenes and temporal dependence and remain
inside their source cluster for uncertainty estimation.

| Fixed generator | Mean frame PSNR dB | Mean frame RGB MSE | CPU s/frame |
| --- | ---: | ---: | ---: |
| Endpoint blend | 24.380028 | 0.004773394 | 0.022348 |
| Zero-initialized mixer | 26.329611 | 0.003428248 | 0.047608 |
| Pure flow | 26.286298 | 0.003726246 | 0.045303 |
| Learned mixer | 26.433983 | 0.003620150 | 0.045011 |

Learned versus pure flow has +0.147685 dB (source CI [+0.075543, +0.263391]).
Learned versus the same mixer before training has only +0.104372 dB with CI
[−0.343639, +0.616145], and its aggregate heldout MSE is higher. Therefore the
study does not establish a stable benefit attributable to training. The mean
of frame PSNRs and the mean pixel MSE are distinct aggregates. Small timing
differences between structurally identical mixers are not claimed as algorithmic
speedups. There are only three test source clusters; the bootstrap is a bounded
development qualification, not population-level generalization proof.

## Frozen protocols, failures, and independent checks

The four `*_PROTOCOL.json` files, source manifests, and `FROZEN_REGISTRATION`
records define selection and runtime boundaries. Each completed scientific run
has its own executed-source snapshot, which is authoritative for that run.
New studies and audit/package helpers were added afterward; current directory
contents should not be substituted for an older snapshot. The cache mechanism
registered two code hashes before execution; its additive `audited-source-copy`
verifies those unchanged files and explicitly records that the copy was made
after execution.

Preserved failures include the receipt missing-reference crash, an HTTP 429
interruption while fetching cascade sources (resumed on the same frozen order
and verified source bytes), the nonexistent proposed `bag.webm` video source,
and the video frame-isolation amendment. The replacement source and added
training-attribution controls were frozen before video generation. A later
auditor schema-key error is recorded separately; no experiment result or gate
was changed to repair the auditor.

`audit_natural.py` imports no experiment scorer. It fully decodes 132 unique
FLAC inputs; reopens 60 source receipt images; rehashes the source files;
independently recomputes word/character edit scores and RGB pixel scores;
checks all 1,680 final delivery records; reconstructs 270 canonical frame PNGs
from the original videos; verifies code snapshots, checkpoints, source groups,
delivery-before-scoring order, and all 48 cascade/video batch cost sums.
`evidence/INDEPENDENT_OUTPUT_AUDIT.json` records its passing result. Separate
read-only peer audits in `evidence/PEER_DOCUMENT_DIAGNOSTIC.json` and
`evidence/PEER_NATURAL_SPEECH.json` independently verify document denominators,
transcripts, WER, certainty equivalents, call counts, and cache timing intervals.
`evidence/PEER_NATURAL_VIDEO.json` independently reopens all 432 delivered PNGs,
recomputes pixel scores and source-bootstrap comparisons, and confirms the
pretest frame-isolation repair and exact batch cost reconciliation.

Behavioral tests exercise missing-label masking, public-only inference,
target/endpoint isolation, real cached/cold video output equality, expensive
calls after allocation, quota/cost accounting, safe archive restoration, and
external-model mismatch preservation. Run the focused test receipt command
below before the repository-required final formatting pass.

## Reproduce and recover evidence

Python packages are pinned in `requirements.txt`; exact runtime, source
dependencies, FFmpeg/Tesseract versions, and OCR language hash are in
`evidence/RUNTIME.json`. Source data and model revisions are pinned in the
protocols and manifests. Public pretrained-model training exposure to the
evaluation corpora is unknown; source separation here concerns the experiment's
fitting, validation, and historical qualification sets.

From the repository root, with the existing assets:

```bash
python -m unittest experiments.multimodal_output_portfolio.continuation_20261027.natural.test_natural_boundaries experiments.multimodal_output_portfolio.continuation_20261027.natural.test_evidence_archive -v
python -m experiments.multimodal_output_portfolio.continuation_20261027.natural.audit_natural --workspace /path/to/workspace --output /path/to/audit.json
```

Each `speech_study`, `document_study`, `cascade_study`, and `video_study` module
accepts `--assets` and a new `--output` directory. `cache_mechanism` accepts the
speech asset directory. `fetch_*` scripts reproduce the pinned source selection;
prefer the archived source bytes when replaying these exact realized cohorts.
The imported baseline source files are pinned to repository commit
`63f198ad85cfa2aa579032256355f446cfe793a0` and also copied under archived staging
dependencies. These experiments use POSIX process/child CPU accounting and the
recorded CPU OCR/runtime environment.

The raw file `ndu_natural_continuation_20261027.tar.gz` is content-addressed:
`INDEX.json` maps every logical path to a SHA256 and byte count; each blob is
stored once. It includes original audio/images/videos, canonical video inputs,
training and validation outputs, every final output, failed attempts, code
snapshots, and learned checkpoints. It also includes the verified 4.11 MB OCR
English language file. The archive **does not embed** the two public Whisper
weight files (75,537,502 and 145,216,508 bytes), and it excludes an unrelated
unmanifested partial model file. Exact official model URLs, immutable revisions,
sizes, and hashes are in `evidence/MODEL_RECOVERY.json` and the archive index.

```bash
python experiments/multimodal_output_portfolio/continuation_20261027/natural/restore_evidence.py --archive ndu_natural_continuation_20261027.tar.gz --destination /new/workspace
python /new/workspace/hepta-private-ci/experiments/multimodal_output_portfolio/continuation_20261027/natural/recover_models.py --workspace /new/workspace
```

The restore destination must be new. The helper rejects path traversal,
symlinks, duplicate logical paths, unexpected blobs, size mismatches, and hash
mismatches; it reopens every restored file. `--verify-discard` actually restores
and rehashes every logical path before removing that checked file, permitting
full validation with bounded temporary disk use. `--receipt` persists that
validation result. Model recovery uses the pinned public URLs and refuses to
overwrite a mismatched existing model. It downloads approximately 221 MB and
is required for neural reexecution. Restoring experiment code alone does not
restore the entire Git repository: obtain the pinned repository baseline and
apply this continuation before rerunning modules. The auditor remaps recorded
absolute artifact paths to `--workspace`; ordinary archived study manifests
retain their original paths and must be remapped explicitly for a new-location
neural replay. No hidden path rewrite changes the archived bytes.

The source collections are pinned upstream test assets from LibriSpeech,
SROIE, OpenCV, and imageio. Source URLs are preserved per file; this report does
not assign one blanket license to all upstream media.
