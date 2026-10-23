# P39: five original Neuron model physical shadow probes

**Status:** DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. This work is stacked
on the evidence-only P38 PR #3412. No model is installed, selected, promoted,
granted Final-use or admitted to a production Organ/Cell. A successful CI job
proves only its exact-source original-weight CPU probe.

## What executes (and what does not)

- Laya English 421M and Typed Decisions 421M: original pinned **complete
  DecisionModel**, including scorer and typed decision Head. Do not confuse
  with P37's Encoder-only Laya results.
- Laya Multilingual 322M: same complete typed-choice call with its own
  exact pinned tokenizer/model/weights. This English historical diagnostic is
  **not** multilingual quality evidence.
- Arctic 305M: one frozen original-weight Encoder forward per selected
  record, official CLS pooling, followed by a fresh **task-only** linear
  Head using frozen training and calibration cohorts.
- Harrier 270M: one frozen original-weight Encoder forward per selected
  record, official last-token pooling, followed by the same class of Head.

All five arms verify *physical* on-disk safetensors SHA256 against P38's
publisher pin, load CPU models, recompute per-row multiclass Brier/NLL/ECE,
retain original predictions and 40 individual forward timings, and rehash
the weights after evaluation. The source UCI News Aggregator zip is
revalidated against its original SHA256, story-disjoint chronological
cohorts are rebuilt and replayed, and the pilot selects eight class-balanced
rows from each of five named splits. All arms bind the exact same row IDs.

The two new encoder Heads use AdamW, 200 optimizer steps, seed 7, identical
class order, fixed LR and zero weight decay. Their tensor initialization
shapes and per-update FLOPs differ with width; this is equal training *step*
budget, not equal FLOPs or equivalent adaptation of the Laya policy Heads.
Laya is evaluated as an unchanged pretrained policy, so cross-family
numbers cannot be reported as a matched-specialization model bakeoff.
Temperature for newly trained Heads is selected on the calibration split
from the fixed grid (0.5, 1, 2, 4), never from future/OOD splits.

## Source and runtime isolation

P39's workflow pins the parent repository **PR head SHA**, uses pinned CPU
PyTorch/Transformers packages from the P37 environment, validates each Hub
commit and LFS weight pointer, downloads exact revision bytes, and hashes
the real file. Laya's implementation is fetched at
<c7527708f9f5220c669d8aa385077cd28d04708a>, then required to be a
clean Git checkout. All execution is CPU-only with no final-use credentials
or production state. Arctic requires publisher GTE Python modeling code
from the exact Hub revision; it is permitted **only** inside the shadow
research worker. No unsigned publisher code may enter the authority plane.

The check-in invokes only public artifacts and historical data. The
workflow retains the actual output JSON plus the independently fetched
publisher revision and measured weight digest as distinct artifacts.
An exact-head success cannot be transferred from another head or from the
synthetic fixture tests. If a model cannot load under the installed
version, produces nonfinite output, has incomplete parameters or a digest
mismatch, that candidate's job fails; no simulated fallback is allowed.

## Reproduction

Run the PR-scoped workflow
[hepta-neuron-five-model-physical-shadow.yml](../../.github/workflows/hepta-neuron-five-model-physical-shadow.yml).
The exact Python CLI (inside the runner, after immutable checkpoint/source
acquisition) is:

~~~bash
python3 qa/stem-bakeoff/replacement_physical.py \
  --candidate laya_typed_421m \
  --snapshot /verified/checkpoint \
  --cohorts /verified/cohorts \
  --archive /verified/news.zip \
  --laya-source /pinned/laya-checkout \
  --rows-per-split 8 \
  --operator-accepted-terms \
  --output /fresh/location/full-policy.json
~~~

For Arctic/Harrier omit --laya-source. Use --rows-per-split 0 to run
all source-cohort rows (subject to measured capacity); choose the budget
*before* inspecting scores. Running --rows-per-split 8 is a diagnostic,
not an adequate final sample size. The output deliberately does not
pretend to satisfy P38's final six-stage evidence schema.

## Six-stage acceptance ledger

| Stage | P39 source capability | Must still be produced independently |
| --- | --- | --- |
| 1 Baselines | Actual full-policy forward, physical hash, bounded original predictions | Full preregistered independent decision tasks and adequate heldout data |
| 2 Multilingual | Actual pinned multilingual complete policy on English titles | Authenticated multilingual cohorts and per-language outcomes |
| 3 New Encoders | Arctic/Harrier physical feature extraction and equal-step task Heads | Matched candidate training quality, trained Head reload and real nDCG/MRR relevance sets |
| 4 Safety | Per-row NLL, Brier, ECE and OOD publisher partition | Precommitted abstain threshold, class imbalance/negative transfer, independent future/outcome and safety owner |
| 5 Resources | CPU process RSS, load time, original per-row timings | Real 64/256/1024/4096 simultaneously configured Cells, target hardware GPU/CPU/RSS, >=100 per-scale samples, GPU/energy, p95/p99 |
| 6 Lifecycle | No privileged lifecycle actions | Real Artifact CAS, migrated checkpoints, CNS cutover, supervisor generation fence, crash/rollback, independently signed Final-use denial |

Per-output "authority" remains DENY_ALL. Even if all five physical-probe
jobs complete successfully, no release, Cell Split or runtime promotion
follows without existing NDU, independent observer, signing,
operator-acceptance and exact-head production gates.
