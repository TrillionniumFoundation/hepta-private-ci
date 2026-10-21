# Shared Stem bake-off and differentiation contract

This document turns the next learning-system step into a qualification plan. It
keeps the existing 421M model as a frozen cognition control, adds
EmbeddingGemma 2 as the short-term multimodal perception and memory stem, and
runs a parallel comparison against a T5Gemma 2 encoder and two native Hepta
latent stems.

This is a serving and evidence contract. It does not download weights, claim
that a checkpoint is trained, or promote a candidate to runtime authority.
Until the artifact, metric, and terminal CI gates are satisfied, the posture
remains \`SHADOW_ONLY / DENY_ALL / HOLD_NO_GO\`.

## Decision

There is no single universally optimal "stem cell" model. The correct choice
depends on which capability must be shared:

| role | candidate | why it is in the bake-off | decision rule |
| --- | --- | --- | --- |
| cognition control | existing 421M | isolates gains from the new stem and keeps the current behavior measurable | freeze it; never use it as a per-Cell copy |
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
- a single feature batch that every Cell can read without a per-Cell copy;
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
3. **Cell gate.** The gate reads the shared feature, task identity, and local
   state and selects an activation or abstains. It does not change the stem
   or grant authority.
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
