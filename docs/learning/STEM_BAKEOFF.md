# Shared Stem bake-off and differentiation contract

This document turns the next learning-system step into a qualification plan. It
keeps the existing 421M model as a frozen cognition control, adds
EmbeddingGemma 2 as the short-term multimodal perception and memory stem, and
runs a parallel comparison against a T5Gemma 2 encoder and two native Hepta
latent stems.

This is a serving and evidence contract. The P31–P37 research implementation
adds explicit public-checkpoint acquisition, offline execution and private
task-Head learning; it does not promote a candidate to runtime authority.
Until the artifact, metric, and terminal CI gates are satisfied, the posture
remains \`SHADOW_ONLY / DENY_ALL / HOLD_NO_GO\`.

## Decision

There is no single universally optimal "stem cell" model. The correct choice
depends on which capability must be shared:

| role | candidate | why it is in the bake-off | decision rule |
| --- | --- | --- | --- |
| cognition control | existing 421M | isolates gains from the new stem and keeps the current behavior measurable | freeze it; never use it as a per-Cell copy |
| inexpensive text representation | Granite multilingual 97M | a small pretrained embedding model with CLS pooling | compare task learning and total shared-plus-Cell storage |
| inexpensive text representation | mmBERT-small | multilingual masked-language-model encoder with mean pooling | do not assume its raw representations equal a trained embedding model |
| multimodal perception and memory | EmbeddingGemma 2 | one shared representation for text, image, and audio; a useful teacher for later distillation | short-term default sensory stem if the artifact and memory retrieval gates pass |
| long-context stem | T5Gemma 2 encoder 270M | tests whether context retention is worth an encoder-decoder-family cost | win only when long-context utility survives the same resource budget |
| native latent candidate | Hepta latent 150M | lowest-cost native shared stem | prefer when quality is within the declared tolerance and cost is lower |
| native latent candidate | Hepta latent 300M | capacity ceiling for native distillation | prefer over 150M only when the measured quality lift pays for its extra cost |

For the target of many Neuron Cells, the default architecture is one shared
stem forward per request batch followed by per-Cell gates, lightweight
adapters, Task/Action/Value heads, local state, and external memory
references. A Cell does not own a copy of a backbone, an optimizer, or a
modality encoder.

The resource model is:

\[
C_\mathrm{shared}(N) =
C_\mathrm{stem} + N(C_\mathrm{gate}+C_\mathrm{adapter}+C_\mathrm{heads})
+ C_\mathrm{memory}
\]

whereas copying a 421M backbone costs approximately
\(N \cdot C_\mathrm{421M}\). The bake-off must report both the shared
forward cost and the per-Cell incremental cost; a larger stem is justified
only if its measured task and transfer gains pay for the shared cost.

## What the shared stem must provide

The stem is the common representation boundary. It must expose:

- one immutable feature snapshot and one encoder/model artifact digest per
  generation;
- a fixed latent width and an explicit missing-modality mask;
- source, modality-manifest, and stem digests for receipts;
- one source feature snapshot shared across Cells, with bounded short-lived
  read copies explicitly accounted for at the Head isolation boundary;
- a host/model execution boundary that can be attested independently of the
  Cell heads.

The existing \`SharedEncoderOwnerV1\` and
\`MultimodalStemProjectionV1\` contracts provide this deterministic boundary.
They deliberately do not pretend to run a model: a production adapter must
bind the real artifact digest and terminal runtime receipt.

## How one stem differentiates into multimodal ability

Differentiation happens in layers so that modality expertise is added once and
Cell specialization remains cheap.

1. **Modality frontends.** Text, image, and audio inputs are normalized by
   modality-specific projectors into the manifest's ordered latent width.
   Missing inputs occupy a zero slot and carry an explicit mask.
2. **Shared representation.** EmbeddingGemma 2 (short term) or a Hepta
   latent stem (long term) produces one immutable shared feature snapshot.
   T5Gemma 2 supplies the long-context teacher/competitor path.
3. **Cell gate.** The current private gate reads the shared feature and local
   state and scales the low-rank residual. It is not a calibrated routing or
   abstention probability. Task-confidence calibration is a separate operation;
   neither changes the stem or grants authority.
4. **Light adapter.** A small per-Cell adapter applies a bounded residual
   (initially zero delta). It is the only learned feature transformation that
   belongs to the Cell.
5. **Task/Action/Value heads.** Heads map the adapted feature to task logits,
   action logits, and a value/uncertainty estimate. They remain immutable
   artifacts within a generation.
6. **Local state and external memory.** Local state is bounded and addressed
   to the Cell. Durable memory stays outside the Cell and is accessed through
   a typed reference/digest; no Cell receives an unbounded private replay
   buffer.
7. **Distillation.** Once the teachers are qualified, train the native Hepta
   latent stem on aligned multimodal, long-context, and task-level targets.
   Distill teacher logits/features/uncertainty with modality dropout and
   missingness masks, then repeat the same bake-off against the frozen
   421M control.

This sequence gives the native stem a common multimodal interface without
replicating every teacher inside every Cell.

## Bake-off protocol

Every arm uses the same data split, Cell scales, serving host class, batch
policy, sequence/image/audio budgets, and receipt rules. The control is frozen.
No candidate may tune on the held-out future window.

Run these arms at 1, 8, 64, 256, 1024, and 4096 Cells:

- 421M cognition control;
- EmbeddingGemma 2 shared perception/memory stem;
- T5Gemma 2 encoder 270M;
- Hepta latent 150M;
- Hepta latent 300M;
- shared versus duplicated encoder at an equal quality target.

For each arm record task utility, future-window utility, negative transfer,
multimodal coverage, long-context retention, calibration/abstention,
throughput, p50/p95/p99 latency, GPU peak, RSS, feature-cache reuse,
queue age, and per-Cell incremental bytes. Report confidence intervals and
the exact model, projector, tokenizer, and data digests.

A candidate is not a winner because it has the largest score on one task. The
selection gate is Pareto-based:

1. it must meet the control's safety, receipt, and stale-generation gates;
2. it must improve at least one target capability without a statistically
   meaningful regression on the control suite;
3. for the native 150M/300M candidates, quality must be within the declared
   tolerance of the best teacher on the target suite;
4. among candidates that pass, select the lowest shared-plus-incremental
   resource cost at the required Cell scale.

## Long-term distillation path

The target is a Hepta-native shared latent stem, not a fleet of copied
teachers.

- **Teacher set:** EmbeddingGemma 2 for unified perception/memory,
  T5Gemma 2 for context, and dedicated modality teachers where they add
  measurable signal.
- **Aligned targets:** projected latent features, masked-modality recovery,
  long-context retrieval/ordering, task/action/value logits, uncertainty, and
  memory-write/read usefulness.
- **Training order:** freeze the teacher artifacts; train the native stem
  with modality dropout; add Cell adapters and heads only after stem parity;
  calibrate uncertainty and stale-generation behavior; run the full scale
  matrix.
- **Promotion rule:** the native stem becomes the production shared stem only
  after artifact identity, reproducibility, resource, and terminal CI gates
  close. The teachers remain evidence sources and rollback references.

The manifest next to this document is intentionally a qualification plan. A
result file cannot silently turn a candidate into an admitted model: its
validator requires explicit candidate, artifact, metric, and gate evidence.

## Executable real-model research path (2026-10-22)

The following modules replace the earlier architecture-only measurements for
the bounded experiment they actually execute. The existing admission manifest
and its broader qualification requirements remain in force.

| Component | Implementation | Concrete behavior |
| --- | --- | --- |
| Actual shared Encoder | `qa/stem-bakeoff/real_encoder.py` | Four immutable upstream revisions; strict complete-weight initialization; offline local code; frozen model; actual parameter and storage accounting |
| Shared feature interface | `qa/stem-bakeoff/feature_bundle.py` | Global summary plus real token states, modality/missingness, optional region/time views, full generation/scope/preprocessing identity and source-byte hashes |
| Private learning | `qa/stem-bakeoff/cell_head_training.py` | Same-initialization linear/gated comparison, train-only SGD, calibration-only temperature, three untouched final holdouts, NPZ serialization and exact reloaded predictions |
| Source reproducibility | `fetch_real_checkpoint.py`, `prepare_news_cohorts.py` | Official weight digest checks, bounded acquisition, original UCI archive hash and deterministic complete replay of selected records |
| Actual bake-off | `real_model_bakeoff.py`, `real_head_fanout.py` | Four distinct binary task Cells plus the multiclass comparison; actual independent Head allocations at 1/8/64/256/1024/4096; no repeated Encoder call for one precomputed event |
| Multimodal execution | `real_media_probe.py` | Actual EG2 image-tower and text/image token execution with retained numeric views and input provenance |

The source data is [UCI News Aggregator](https://doi.org/10.24432/C5F61C),
Gasparetti (2017), CC BY 4.0. The fixed archive SHA256 is
`1f5f08691f0ce576cb0b5cfdbcb8c55e0ec14dda8f3e07933da72c500338845a`.
The plan uses 256 March-2014 task-training records, 128 April calibration
records, 128 May and 128 June historical holdouts, and 128 July records from
publishers excluded from all earlier splits. Story, canonical title and source
IDs are disjoint. These are later windows relative to task-Head training;
they are not future deployment traffic and foundation-pretraining exposure is
unknown. All four models use the same 200 steps, learning rate 0.2, seed 7,
rank 4, task budget and class-balanced cohorts.

Create a CPU environment, install torch 2.10.0 and torchvision 0.25.0 from the
PyTorch CPU wheel index, then install `qa/stem-bakeoff/requirements-real.txt`.
The exact dependency versions used in the experiment are pinned there. The
workflow `hepta-shared-stem-bakeoff-shadow.yml` executes the same acquisition,
preparation and offline runner and uploads reports plus trained Head tensors.

Example for the small text candidate (choose an empty external work directory):

```sh
python qa/stem-bakeoff/fetch_real_checkpoint.py \
  --candidate granite97m --destination /tmp/stem-run/granite
curl --fail --location \
  'https://archive.ics.uci.edu/static/public/359/news+aggregator.zip' \
  --output /tmp/stem-run/news.zip
python qa/stem-bakeoff/prepare_news_cohorts.py \
  --archive /tmp/stem-run/news.zip --output /tmp/stem-run/cohorts
python qa/stem-bakeoff/real_model_bakeoff.py \
  --candidate granite97m --snapshot /tmp/stem-run/granite \
  --inventory-sha256 '<inventory_sha256 from granite.acquisition.json>' \
  --cohorts /tmp/stem-run/cohorts --archive /tmp/stem-run/news.zip \
  --output /tmp/stem-run/results --operator-accepted-terms
```

`--operator-accepted-terms` records the operator's acceptance; the program
does not obtain a license grant. mmBERT requires the registered restricted
`convert_mmbert.py` conversion before loading; it never loads arbitrary Hub
Python or unrestricted pickle code. Laya's arm is explicitly **encoder-only**:
the experiment does not compare its complete 421M policy.

Each result directory contains a plan saved before execution, actual forward
receipts, feature manifests, six trained task artifacts and a final report.
The code hashes, checkpoint identity, source record IDs and dataset digest
bind the experiment. Encoder tensor hashes must match before learning, after
learning and after final fanout. A changed source tree aborts the run.

The per-scale Heads are actual private copies of one trained Head. Their
allocation measures scaling; only the four separately trained binary tasks
demonstrate independent parameter learning. Each binary task has one positive
class against three negative classes, so its majority-class accuracy baseline
is 75%. Every candidate's four binary Cells report 75% accuracy on each
historical holdout and the publisher OOD split. This does not establish better
classification or positive-class recall than that baseline; the reports do not
retain per-row predictions needed to infer their confusion matrices. Fifteen
of the sixteen binary Cells have better OOD calibrated NLL than the constant
class-prior predictor (NLL 0.562335), so probability scoring can improve even
when classification accuracy does not. A follow-up protocol must retain
confusion matrices, balanced accuracy and positive-class recall/AUPRC before
claiming useful Cell specialization. A single event shared across
4,096 Cells does not imply 4,096 distinct inputs can be encoded for free.
Three latency samples per scale are descriptive measurements, not p95/p99 or
production SLO evidence. Peak RSS, current RSS and tensor-storage bytes have
different meanings and are reported separately.

The image probe uses an explicitly procedural image to establish actual model
and image-tower execution. It cannot establish semantic retrieval, grounding,
spatial localization, audio/video quality or multimodal learning improvements.
Action, value and uncertainty heads are untrained; task-state training uses
zero local state. Model selection, conditional confidence/coverage, target
hardware and production admission require their own evidence.

### Retained execution results

The reviewable snapshot is
[`qa/stem-bakeoff/evidence/20261022-real-model/summary.json`](../../qa/stem-bakeoff/evidence/20261022-real-model/summary.json).
It links all four original reports and plans, actual image-execution evidence,
and the retained Granite linear/gated Head tensor artifacts. The full per-run
artifacts are regenerated by the CI matrix. Local behavior verification passed
181 tests; GitHub terminal checks remain an exact-published-head requirement.

| Frozen text Encoder | Loaded parameters | Encoder tensors, MiB | May accuracy | June accuracy | Publisher OOD accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Granite97M | 97,441,152 | 371.71 | 78.91% | 84.38% | 74.22% |
| mmBERT-small | 140,493,696 | 535.94 | 64.84% | 63.28% | 53.91% |
| EG2 text profile | 271,002,624 | 1,033.80 | 79.69% | 78.91% | 73.44% |
| Laya encoder-only | 394,781,696 | 1,505.97 | 41.41% | 43.75% | 41.41% |

Linear and gated accuracy is identical at every listed point. The result
establishes task learning on these frozen representations, but does not
establish incremental accuracy from the gate. It is not evidence against
Laya's complete policy, which was not evaluated. With only 128 examples per
holdout, small differences between candidates are descriptive; no statistical
winner or target-domain model is admitted.

At 4,096 physically distinct Granite Heads, actual Head tensor storage totals
114.30 MiB, plus 371.71 MiB of shared Encoder tensors. The complete process
peaked at 1,205.98 MiB, including Python, runtime, retained features, temporary
copies and allocator behavior. The measured Head fanout performs zero extra
Encoder calls after the source event's one encoding. This is not a zero-copy
or zero-overhead serving claim.

The fixed 0.7 task-confidence threshold accepted only 1/128 Granite OOD rows
and 2/128 EG2 OOD rows; mmBERT and Laya accepted none. Thus classification
accuracy alone does not close useful selective coverage. The four multiclass
arms all selected temperature 0.25, the lower boundary of the predeclared grid;
coverage was already low on calibration data (4/128 for Granite and EG2, zero
for the other two). This is not solely evidence of OOD drift. A new training
or calibration protocol needs fresh final evaluation cohorts; changing the
grid or lowering 0.7 after reading these holdouts cannot qualify this run.
The retained summary
keeps target-domain learning/coverage, multimodal task quality, target-hardware
latency/energy, full policy/state learning, and exact-head CI/parent admission
explicitly unclosed. They cannot be turned into passes by execution receipts.
