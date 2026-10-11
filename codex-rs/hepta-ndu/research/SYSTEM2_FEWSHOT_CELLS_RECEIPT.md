# System2: a small local Cell delta, not another global-loss variant

Parent: `b64e0b47bbfa0a608ccd4880ce49626ff5331ed8`, PR #1546.
No default model, old experiment, NDU/FBSDE API, or production path is changed.

## Previous hosted result now completed

Run **38152729866** completed on the parent source `b64e0b47...`, tree
`a8a12a78480c5bd6b0dc9de4f07b8fc2084d3212`. Artifact **11708550459**,
323,530 bytes, ZIP SHA256
`eec44ef839bc33aff88a2343b08697dca3a8b37b0be41e1ce05d6f56d84200af`:
all **163 manifest entries / 164 files** verified. The full regression log has
**1,012 passed, two skipped, 1,014 total**. Both 32-condition replay stages
completed. All 32 margin-condition summaries and per-query records exactly
match the prior local observations; its candidate still has no nonregressing
cross-family gain. This is replication on the same inputs, not fresh evidence.

## Fixed question and protocol

Prior studies fit a head on other source families and tested zero-shot transfer.
That does not directly test whether a new Cell can learn from a few local samples.
This stage fixes a different, explicit personalization experiment before its
first cached-native candidate run. It is NOT a replacement confirmation test.

Use the same final 20 general-Cell TRAIN questions and five recorded source
families from artifact 11706235289, ZIP SHA256
`2d7d1058c724f79298b8ccd28c319629b929a842f2107301c3e1c1adef09bcea`.
For each query, select one or two OTHER same-family questions by canonical-ID
hash order, without looking at their labels. Support sets are nested. Missing
positive/negative support is retained as a zero update, never replaced by an
easier support question or fabricated unanswerability label.

The shared prior uses the existing squared-hinge linear StemHead fit on every
OTHER family. It remains root-disjoint from the target family. The local delta
uses only this episode's support labels. The original forbidden roots remain
forbidden. Local support and query intentionally share a source root: this is
question-disjoint, source-overlapping personalization, NOT root-disjoint transfer.
The exported feature contract does not establish support-before-query timing;
no chronological or prospective online-learning claim is made.

Six methods are fixed: frozen, shared prior, local-only delta, shared-plus-local
(`differentiated`), erased local update, and parameter-free support-neighbor
memory. The neighbor compares nearest positive and weak-negative cosine scores,
with an explicit frozen fallback when no supported contrast is available.
It uses the same support opportunity, not query labels.

The local objective is the same squared hinge with margin one and regularization
0.01, but on `b - A @ prior`; only a 384-float delta is adapted. Content erasure
zeros the delta design, not the existing prior or native frozen logits. Shared
and erased-update predictions must therefore coincide. The fixed frozen-native
stop gate is common to every arm and is NOT a calibrated refusal/value model.
There is no hyperparameter search or post-result choice of support budget.

## Observed LOCAL cached-native result

All **240/240 predictions** completed, with zero execution failures. They comprise
20 leave-one-query episodes, two support budgets, and six methods: NOT 240
independent observations, 40 distinct queries, or a deployed Cell population.
Five shared priors were fitted once and reused across episodes. Every local
support fit, delta state, original feature digest and prediction is retained.
Query scoring starts only after all predictions are durable and sealed. A label
may be support for another cross-validation episode, but never for its own query.

| Method | One support: source hits / 20 | Two supports: source hits / 20 | Two-support family macro |
| --- | ---: | ---: | ---: |
| Frozen | 6 | 6 | 0.280000 |
| Shared prior | 6 | 6 | 0.246667 |
| Local only | 6 | 7 | 0.346667 |
| Shared + local delta | 6 | **8** | **0.380000** |
| Erased local update | 6 | 6 | 0.246667 |
| Support-neighbor memory | 6 | 4 | 0.200000 |

At the fixed primary two-support budget, differentiated versus frozen has two
source hits gained and zero lost; versus shared: two gained/zero lost; versus
local-only: one gained/zero lost; versus neighbor: four gained/zero lost. These
are weak native-source hits, NOT answer correctness or semantic sufficiency.
The two gains over frozen occur in two recorded families. One of those gains
was already supplied by the shared prior; local differentiation must not receive
all of the credit for that individual example.

One support yields no gain over shared, and its comparison with frozen retains
one gain and one loss. Fourteen of twenty one-support episodes and three of
twenty two-support episodes have no local pair opportunity; all remain counted.
Two-support progression is `fresh_confirmation_required`, NOT task/production
acceptance. The primary budget was fixed before these observations.

The local candidate delta has 384 FP32 values: **1,536 weight bytes per episode**,
excluding the shared prior, Encoder, cache, metadata, support storage, training
work and serialization overhead. The neighbor bank stores feature vectors;
its bytes are reported separately. No equal compute or production-TCO claim.
New Encoder and Reader calls: zero. Original encoding and prior artifacts still
cost resources. This run is real cached-native fitting with offline source
contracts, not new multimodal data or an independent Reader judgment.

A separate pool census found eight queries with no positive index in the full
saved pool and one with a positive only outside top four. No candidate pool is
expanded based on that knowledge; no missing label is promoted to a task verdict.

## Implementation and validation

`system2_fewshot_cells.py` reuses existing Features, TrainingCut, StemHead,
source-family splits, archive verification, and bounded hinge solving. It does
not alter the prior global-loss, content, Reader-first or eight-arm experiments.
The workflow preserves all regression checks and previous replays, then adds
this bounded cached-feature study without staging a pretrained model again.

Local **127/127 System2 tests** passed, including sixteen new numerical,
admission, counterfactual and actual-runner fixture tests. The saved native-feature
archive and prior source bundles were verified. The local context is PyTorch
2.10.0+cpu, safetensors 0.7.0, and source overlays with verbatim repository
Features/StemHead constructor-forward contracts. Full-repository hosted execution
under the pinned environment remains a separate required result. Local just/Ruff
are absent; no Rust source changes or CI waivers are made.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_fewshot_cells.py \
  /path/to/system2-content-38147248105.zip /new/output
```

The output retains exact source context, episode plan, original-source audit,
shared prior fits, per-Cell tensors, all failed/successful attempts, the sealed
pre-scoring prediction journal, and comparison against every fixed control.
Current revocation and lineage authentication remain external admission duties.
Unseen independent confirmation, human sufficient-evidence review, genuine
multimodal/compositional task gains, calibrated NDU continuation, and production
acceptance are still unestablished. Do not promote source selection to reasoning.
