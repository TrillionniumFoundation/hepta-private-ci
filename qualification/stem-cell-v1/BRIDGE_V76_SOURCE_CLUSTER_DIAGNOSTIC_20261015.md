# V7.6 — Original V6/V7 continual-learning failure analysis, source-cluster paired

**Research only · SHADOW_ONLY · DENY_ALL · 2026-10-15.** Additive to the existing
[Hepta Shared-Stem draft #2383](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2383).
This stage is **actual independent reanalysis of saved output from real trained
checkpoints**. It does not rerun the 97M pretrained Encoder, recalculate original
TokenBank features, fit a new model, score held-out future material, admit NDU,
or authorize Cell Split or a production commit.

## Evidence and exact observations

The user-held **original** archived V6 and V7 ZIPs were read as regular held
file-descriptor snapshots and checked against their frozen full SHA256 digests.
All 211 V6 and 178 V7 manifest-listed member bytes/sizes were independently
verified. The original V5 natural TRAIN-source internal-tune case file and V6
design have identical bytes in both archives. Reopened the original panel
probabilities and **recomputed all reported binary accuracy, F1a, F1m and
whole-question exact match** using a separately implemented standard-library
scorer. No scorer/prerequisite is imported from the original training runtime.

For the natural internal panel: **827 complete candidate rows / 194 questions /
16 original independent paragraph/source groups**. All three training seeds
41/47/53 saw these SAME sixteen previously exposed groups. A total of 36
seed/arm panel observations across the two archives does **not** create 36
independent data populations. Primary figure is the mean of three seed-specific
F1a values, not a pooled row-level pseudo-replicate.

### Historical real V6 observations (original 3 frozen + 9 continued weights)

| Arm | Mean F1a on already-exposed Natural internal | 3-seed old Binding TRAIN gate |
|:--|--:|:--|
| Frozen Bridge warmup | **0.538529** | 3 / 3 |
| Natural-only | 0.475970 | 0 / 3 |
| Ordinary replay | 0.461500 | 2 / 3 |
| Contrastive | 0.431199 | 2 / 3 |
| All-positive cheap control | **0.622814** | not an old Binding model |

V6 contrastive minus frozen warmup: **−0.107330 F1a** (exploratory
16-source cluster paired bootstrap 95% interval **[−0.15795, −0.06614]**).
Contrastive minus natural-only: **−0.044771**
([−0.08153, −0.01384]). The original warmup was **not** trained on the
Natural continuation objective, and these already-seen internal numbers cannot
certify new-task learning or cross-distribution generalization.

### Historical real V7 continuation follow-up (12 additional model outputs)

| Arm | Mean F1a on same sixteen exposed Natural sources | Difference vs frozen V6 warmup | Exploratory paired 95% interval |
|:--|--:|--:|:--|
| Repeat | 0.473343 | −0.065186 | [−0.11688, −0.01592] |
| Diverse | 0.424402 | −0.114126 | [−0.15894, −0.06797] |
| Anchored | 0.423281 | −0.115248 | [−0.15458, −0.07615] |
| Low learning rate | 0.368853 | −0.169676 | [−0.21232, −0.13002] |

All four V7 arms fail the **historical original overall qualification gate**
in all seeds, even though some individual arms retain the original Binding
TRAIN fit. The V7 gate also requires other elements of the real experimental
protocol, e.g. previously exposed relation-internal controls. The overall
rejection must not be rewritten as an independent future failure.

These observations show a consistent **negative on internal Natural F1a**
for every one of the seven historical continued families relative to their
own original frozen Bridge warmup. A few arms increase Natural whole-question
EM versus the mostly low-EM frozen model; **the F1a comparison is not a
Pareto dominance theorem across EM, accuracy, latency or cost**. Training
costs/parameter counts differ; no equal-lifecycle causal efficiency result is
established. The all-positive reference is intentionally a strong F1a cheap
control (and has zero EM).

## Uncertainty treatment and limits

Both tools recompute saved original candidate predictions with strict
`p_positive > 0.5` and complete original question membership. Source-cluster
bootstrap uses **2,048 deterministic resamples of the sixteen sources**,
resampling the SAME group draw for every seed/arm in each iteration, with
nearest-rank percentile endpoints. This preserves source correlation and
avoids treating repeated seed executions as independent original examples.
These are exploratory, development-exposed intervals, not a statistical
certificate of future superiority/inferiority or randomization-based causal
confidence. Neither retrospective V6 nor V7 original evaluation was designed
as an independent prospective trial.

Cost receipts are cited as **original historical self-reported CPU work**.
No model-load/Encoder generation, optimizer replay, GPU energy, target-host
p99, external model-issuer signature, privacy authority, or new scientific
success can be inferred from a completed archive manifest check.

## Reproduce from exact user-held ZIPs

```bash
cd qualification/stem-cell-v1
python -S bridge_original_effect_v76.py \
  --original-v6 /private/hepta_bridge_learning_v6_20261015.zip \
  --output /sealed/V76_ORIGINAL_V6_CLUSTER_EFFECTS_NEW.json
python -S bridge_retention_v76.py \
  --v6 /private/hepta_bridge_learning_v6_20261015.zip \
  --v7 /private/hepta_retention_transfer_v7_20261015.zip \
  --output /sealed/V76_ORIGINAL_V7_CLUSTER_EFFECTS_NEW.json
python -m unittest -v test_bridge_original_effect_v76 test_bridge_retention_v76
python -O -m unittest -v test_bridge_original_effect_v76 test_bridge_retention_v76
```

The scripts import only Python's standard library and never fetch model weights
or read labels from an official validation/test/future split. JSON output is
write-once and excludes all original passage text, weights, full probabilities,
source case IDs and per-case targets. The result files in this research PR are
**sanitized historical evidence**; archived private/raw originals stay outside
Git and remain immutable.

## Mandatory next meaningful train/effect experiment

1. Obtain exact original public Granite97 weights and byte-pinned tokenizer,
   regenerate or recover the original TokenBank with independent Torch/NumPy
   parity before fitting any new candidate. Until that physically runs, stop
   labeling simulated inputs as a genuine trained Stem result.
2. Register before training an old/new task objective with **old held-source
   retention AND new independent natural question-level F1a/EM**, plus matched
   trainable parameter, data exposure, actual Encoder forwards and complete
   update/optimization costs. Retain frozen/no-change, simple-Head, replay,
   cross-fact and per-Cell split baselines. Train only from original independent
   past sources; reserve genuinely later separated source windows.
3. Track corrected/damaged whole questions, cross-fact evidence dependency,
   nontrivial causal inference depth, adverse tradeoffs and new-old net NDU
   utility from **external** scored outcomes. Deny split/fusion/model selection
   when any required future evidence or ledger remains absent.

**Disposition:** `SHADOW_ONLY / DENY_ALL / NO_MAIN_MERGE / NO_CELL_SPLIT /
NO_NDU_SELECTION / NO_10T_OR_100T_EQUIVALENCE_CLAIM`. This is a concrete
negative learned-task diagnostic, not a final verdict that continual learning
or split Cell systems cannot ever work.
