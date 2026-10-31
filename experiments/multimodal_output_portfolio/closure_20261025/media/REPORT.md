# Final media experiment: execution succeeds under local gates; speech quality remains limited

The implementation now has real learned audio/video input paths, a shared neural
generation state, trained acoustic and image-conditioned motion heads, and four
actual output artifacts per request. The once-only final run completed all 640
planned outputs on **64 new source tasks**, with every frozen local acceptance
gate passing. This establishes a bounded executable multimodal experiment.

There is also material negative evidence. A frozen, target-free Whisper
supplementary audit recognized only **22/64 generated audio pairs (34.38%)**,
compared with **55/64 real input pairs (85.94%)** on the same tasks. The primary
independent mel criterion and physical codec gates remain exactly as registered;
their success does **not** establish natural, intelligible speech or general
four-modal output quality. No model or threshold was changed after these final
outcomes. This limitation is part of the result, not an omitted failure.

Machine-readable results are in `RESULTS.json`; independent review is in
`review/AUDIT.json`; execution boundaries are in `COST_SCOPE.md`.

## Frozen candidate and sample census

The candidate is the newly trained canonical-voice conditional VAE, the learned
recurrent image-conditioned motion head, the trained acoustic/video ingress
models, and the original frozen NDU-trained shared generator. The inference
prefix is fixed: `refine_semantic`, then `couple`. This experiment does not test
whether a dynamic NDU controller outperforms another controller.

`FINAL_PROTOCOL.json` was frozen before final access, with 55 exact file pins.
Its SHA-256 is
`66db720064d45fc2e38cc9f8123767f51bfb82029767a093062971e05aff3a34`.
The runtime verified the candidate, qualified development report and allocation
before loading the reserved 64 source pairs and FSDD test recordings.

The final census is:

- 64 source tasks and 128 unique MNIST image identities.
- Five input routes: image, text, audio, video, and audio plus video.
- Two paired conditions, hard and soft, sharing exactly the same encoded state.
- 640 complete output bundles, containing 2,560 actual output files.
- 64 physical input bundles, containing 256 input files and 128 unique FSDD
  recordings. Those joint input recordings cover four speakers: george 50,
  jackson 47, lucas 26, nicolas 5. The separate 300-recording speech qualification
  census covers all six speakers.

The 640 rows are repeated measurements of 64 source tasks. They are not 640
independent examples, and the experiment contains one selected trained model
combination. Independent review recomputed the census, checked all 2,816 input
and output file hashes, and verified the 320 hard/soft state identities.

## Final primary results

The primary condition is hard predicted semantics. Each success requires the
generated caption and relation, both image panels, both speech events, and all
twenty video frames to agree with the source task, with nonempty audio, moving
video and complete physical readback.

| Input route | Strict joint success | Rate | Descriptive 95% Wilson interval |
| --- | ---: | ---: | ---: |
| Image | 49/64 | 76.56% | 64.87–85.25% |
| Text | 64/64 | 100.00% | 94.34–100.00% |
| Audio | 62/64 | 96.88% | 89.30–99.14% |
| Video | 55/64 | 85.94% | 75.38–92.42% |
| Audio + video | 59/64 | 92.19% | 82.98–96.62% |

These are per-route descriptive source-pair intervals, not simultaneous
intervals or intervals over independent training seeds. The image point estimate
passes the fixed 75% gate by **one successful task**; its interval does not show
that the population success rate exceeds 75%. Forty-six of the 64 tasks succeeded
in all five hard-condition input routes. Hard and soft conditions had identical
binary success outcomes for every task and route; this experiment provides no
success-rate advantage for hard discretization over soft conditioning.

On the 300 FSDD test recordings, the frozen independent mel auditor scored
96.33% and the acoustic input model 98.00%. The conditional acoustic probe scored
10/10, and the conditional video probe scored all 200 frames correctly. All
unchanged primary thresholds passed. These scores concern the declared digit
domain and local observers.

## Where failures remain

| Input route | Text correct | Image correct | Audio correct | All video frames correct |
| --- | ---: | ---: | ---: | ---: |
| Image | 61/64 | 60/64 | 61/64 | 49/64 |
| Text | 64/64 | 64/64 | 64/64 | 64/64 |
| Audio | 62/64 | 62/64 | 62/64 | 62/64 |
| Video | 56/64 | 58/64 | 57/64 | 56/64 |
| Audio + video | 62/64 | 62/64 | 61/64 | 59/64 |

The predicted shared semantic code disagreed with the task on 3 image, 0 text,
2 audio, 7 video and 3 audio-video cases. When that shared code was correct,
the independent mel observer found no acoustic digit error. This is a local
content-faithfulness observation, not a perceptual-quality certificate.

In the image route, eleven cases had a correctly recognized emitted image but
at least one incorrectly recognized video frame. The corresponding counts were
two for video input and three for combined audio/video input. This localizes an
additional weakness to temporal rendering and/or the frame observer's response
to motion. It does not establish a unique causal explanation. The complete
per-frame predictions and shared-state semantics are retained in
`final-failures.json` in the evidence package.

There were no physical clock/readback failures. Every primary output contained
16,000 PCM samples at 8 kHz and twenty frames at 10 fps over two seconds, with
event two starting at sample 8,000 and frame ten. These values came from actual
ffprobe/ffmpeg reopening and lossless byte comparisons. Frame-level semantic
failures are still failures even when those timestamps are valid.

The final negative controls all started from an actually successful unequal-digit
bundle. Silence, swapped audio events, swapped video events, repeated frames and
a missing modality were physically created and rejected. The event-swapped
files retained valid PTS; their failure therefore depended on content alignment.
An independent reviewer also decoded the development positive and four physical
mutations and verified the exact PCM/frame transformations.

## What is learned, and what is constructed

Audio input consists of actual FSDD speech samples read from the serialized WAV,
then transformed by STFT/mel normalization and a trained CNN. Video input consists
of actual codec-decoded frames of **constructed MNIST motion**, processed by a
trained frame CNN and GRU. It is not naturally recorded video. Text and image
inputs enter the existing shared learned encoder. The audio/video posterior
bridge uses learned token embeddings and fusion; no Target enters the generation
function or output heads.

The original neural core emits the caption and image. The acoustic head is a
conditional spectral VAE trained on 300 original generator-role recordings from
one declared voice, jackson. Its zero latent inference path is explicitly trained.
Griffin–Lim reconstructs its learned spectrum into a waveform; there is no
retrieval of a recorded output. The video head learns a recurrent spatial field
from real training-image reconstruction and applies it to the same generated
image panels. It produces distinct sampled frames, not repeated-frame playback.
This is a bounded image-to-video model rather than a general video foundation
model.

## Failures and repairs retained

Four actual training stages are preserved with their source snapshots, initial
and final parameter identities, loss histories and nonzero gradients. Their wall
times were 309.33 s, 429.15 s, 147.42 s and 385.29 s; their measured Python CPU
sum was 1,268.45 s. Existing shared-core pretraining was not rerun here.

The first acoustic auditor was unqualified. A later, stronger, recording-disjoint
mel auditor overturned an apparent 10/10 synthesis result: the old VAE actually
scored 2/10. Thirty actual recordings, their Griffin–Lim reconstructions and
time-aligned reconstructions each scored 30/30, while the VAE's predicted spectrum
and reconstructed waveform both scored 2/10. On sixty original generator
examples, posterior-mean reconstruction scored 71.67% versus 20% from the
zero-latent inference prior; posterior standard deviation averaged 0.0271.

The prospectively registered repair used one canonical voice, explicit
zero-prior reconstruction loss, stronger KL regularization and a newly trained
reward observer after differentiable waveform reconstruction. The independent
auditor's recordings and gradients were never used to fit the generator. The
evidence is consistent with repairing a large posterior/prior mismatch, but
the changes were combined and do not identify one exclusive cause.

The exact acoustic objective was `0.5 posterior spectral L1 + 0.5 zero-prior
spectral L1 + 0.005 KL + 0.05 fixed reward CE` after four differentiable
Griffin–Lim iterations. Inference uses 24 iterations. Original role separation
and every failed output remain in the package.

## Independent speech cross-checks

Whisper was frozen, received only actual waveform files, and received no intended
text, target classes, candidate list or custom grammar. Its strict supplementary
parsing on the final 64 text-route pairs gave:

| Actual waveform | Exact pairs | Correct digit positions |
| --- | ---: | ---: |
| Real FSDD input | 55/64 (85.94%) | 110/128 (85.94%) |
| Canonical VAE output | 22/64 (34.38%) | 47/128 (36.72%) |

This is serious negative evidence for speech quality beyond the in-domain mel
criterion. It is not hidden by the primary gate pass, nor does it prove how a
human listener would score every clip. It shows that a broad, natural-speech
claim would be unsupported. The same 64 tasks were reused; this adds no new
independent sample count. This audit incurred an additional 70.35 s wall and
70.26 s CPU, outside the primary execution cost below.

A separately identified frozen Piper/LJSpeech neural reference also ran. Its
original two-second bare-word profile and subsequent strict dual-ASR carrier
profile failed. A four-second Whisper-primary carrier profile completed real
four-modal outputs, but full independent ASR eligibility failed: on all 300
old validation recordings, Whisper word-event accuracy was 31.33% and Vosk
23.33%. On generated carrier controls their respective scores were 100% and 50%,
and silence, event swaps, a wrong digit, missing event and actual digit-word
excision were rejected. These output-domain mechanisms do not replace failed
general eligibility. The Piper reference was never used for the canonical final
conclusion or to reopen final sources.

## Actual cost and artifact custody

The canonical final run took **430.15 s wall**, **30.04 s main Python CPU** and
**392.86 s child codec CPU**, totaling **422.90 s measured process-tree CPU**.
This includes source/model checks, input-bundle serialization/readback, observer
qualification, all generation and codec roundtrips, audits and physical negative
controls. Python imports before the main timer and the final summary write are
outside the boundary. Per-output execution wall averages were approximately
264–277 ms, excluding later independent scoring and excluding each source pair's
input-file construction; audit-included row averages were 613–637 ms. Row sums
double-count shared hard/soft encoding and must not replace whole-run cost.

All 55 candidate pins, thirty runtime source snapshot files, twelve selected
runtime assets and 2,816 final input/output file hashes passed independent
review. The source was frozen before final access, and the output rows preserve
source identities, model/state identity, actual file hashes, decoded outcomes,
clock receipts and costs. The archive contains all failed stages and historical
source snapshots as well as final evidence. `ASSET_INVENTORY.json` and the bundle
dependency manifest identify shared inputs and pretrained reference assets by
exact hash. The Vosk ZIP was verified member-by-member to reconstruct every
actual extracted dependency without duplicating those weights in the archive.

The completed work establishes a reproducible bounded multimodal forward
process under its original local criterion. It does not establish natural
speech/video quality, unseen-speaker generalization, foundation-model scale,
end-to-end NDU training of all four modalities, dynamic NDU superiority, global
optimality or production qualification. Those remain separate claims requiring
new, prospectively designed evidence.
