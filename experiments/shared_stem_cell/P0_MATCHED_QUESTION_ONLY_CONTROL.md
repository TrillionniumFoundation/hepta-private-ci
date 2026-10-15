# P0 matched Question-only learning versus Evidence learning (v3)

**Research / Shadow / DENY_ALL.** This increment continues the exact v2 original-human
MultiRC Reader audit without replacing the original experiment, evidence records,
source owners or model selection. It answers a *narrower, falsifiable* question:

> Does a genuinely trained Evidence Head predict original human MultiRC labels
> better than a separately trained Question-only Head given exactly the same
> original training examples, Head initialization, parameter count and SGD steps?

This matters because comparing a Head trained on full evidence against **that
same Head** evaluated on an empty passage confounds useful evidence with an
unfamiliar input distribution. A separately trained prior is the required
stronger, matched-model control.

## Fixed scientific treatment and controls

The original source remains `aps/super_glue@4e14482c58d790d467ecfb29b6790e1917bf8756`, using
existing label-independent source selection: 12 train, 4 calibration, 8 original
human-labeled heldout **passages**, two questions per passage, genuine candidate
alternatives. No score-driven cohort selection, no new date windows, no invented
human label of edited evidence, no new data acquisition code. Use the existing
`p0_multirc_semantic_material.py` without changing any source, ID or label.

For each of Granite 97M R2, mmBERT-small and EmbeddingGemma2-text:

| Dimension | Original Evidence Head | Question-only Head |
|---|---|---|
| Frozen Stem | Same real loaded pretrained checkpoint and Q24 feature bank | Same object and same resident weights |
| Task | Original question + candidate + source evidence | Original question + candidate, **no passage** |
| Supervision | Original human TRAIN candidate labels | **Same** original TRAIN candidate labels |
| Head | Linear, FP32, exactly `2*width+2` full parameters | Identical geometry and **identical initial tensor bytes** |
| Optimizer | `torch.optim.SGD`, seed `20261015`, learning rate `.1`, 40 full-batch steps | Same, independent real 40 optimizer steps |
| Calibration | Original validation source; fixed temperature grid | Matching validation questions without evidence; same grid and original labels |
| Heldout | Original paragraph questions | Same questions and candidates without paragraph |
| Scored target | **Original** human label | **Original** human label, not an artificial no-evidence entailment label |

Both heads have frozen-initialization negative controls. All three compared
architectures have different feature widths, so equal parameter count is
**within each Stem**; this design does NOT equate Granite/mmBERT/Gemma with Laya.
Laya421 remains an independently reported native **frozen no-change** baseline
with no counterpart pretending to be a trained equal-parameter Head.

The encoder already computes both full-evidence and no-evidence vectors in the
original physical experiment; the new Head never reloads it and charges **zero
additional encoder forwards**. It does train additional real parameters and
execute additional Head inferences; these incremental costs are measured, not
hidden. The independent reviewer requires real per-case Encoder durations for
all feature vectors, actual Stem load, both Head SGD runs, all original and
matched-prior prediction request durations, and physical model process wall/RSS.
A claimed physical forward, hashed JSON or a successful unit test is **not** a
signed hardware receipt or independent energy measurement.

## Independent predeclared outcome

Compute per original human-labeled candidate the Brier difference

```
(prediction_question_only - human_original_label)**2
- (prediction_evidence - human_original_label)**2
```

Average first **within each original passage**, then equally across eight held
passages. Positive value favors evidence; negative favors independently trained
question-only. Report per-passage values, negative and zero outcomes, both
original frozen controls, hard exact-answer-present same-question positive /
negative rankings, actual training/inference cost, and deterministic 512
passage-resamples purely as exploratory description. Eight source groups are
**underpowered**: no p-value-driven promotion, model winner or 95% superiority
claim. The original independent reviewer and original label-only rescorer are
rerun in full before accepting a v3 matched result.

## Implementation

- `p0_question_only_head.py`: compile no new model; use original frozen Q24
  features, train an actual additional question-only FP32 Head, preserve complete
  initial/final tensor digests, train/cal material identities and work counters.
- `p0_multirc_semantic_execute.py`: one additive integration after original
  physical Stem and Head, without changing dataset or model loader.
- `p0_question_only_review.py`: independent source- and target-replayed validation,
  all-four-model admission, strict matched training cohort and optimizer parity,
  full prediction census, per-source original-label effects and metered costs.
- `test_p0_question_only_matched.py`: source-only adversarial defects and **real
  CPU Torch SGD** on *synthetic* features; explicitly NOT a pretrained outcome.
- Existing workflow `hepta-p0-multirc-semantic-four.yml`: the same four-stage
  owner pipeline, with source checks plus model-lifetime matched prior and
  independent score step. The original independent score is retained separately;
  no extra original source or historical artifact is rewritten. Restore an
  explicit `numpy==2.2.6` dependency for the source CPU `.numpy()` tests.

Run the focused source checks:

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p test_p0_question_only_matched.py -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_p0_question_only_matched.py -v
```

The full inherited test lanes must also remain green at the **new exact HEAD**.
The model runner gets `fit.json` (train/calibration labels only) and `blind.json`
(no heldout label file). Only the independent score job obtains source-replayed
original validation labels. A missing model, Laya masquerading as an equal Head,
any source/parameter/optimizer drift, incomplete logits, missing actual charges,
unknown outcomes, or irreconcilable observer results fail closed.

## Explicit exclusions

This pilot does not prove image/audio/video generation, general reasoning,
Reader sufficient-evidence entailment, bilingual/code transfer, longitudinal
retention, the superiority of NDU System 2, a generic FBSDE optimality theorem,
4,096-Cell physical learning, a faster compiled Skill Cell or replacing MCP.
Unlike a longitudinal experiment, these MultiRC held sources are still a tiny
English retrospective panel. Provenance hashes alone do not authenticate the
publisher, human reviewer independence, model weights on another device, or
hardware energy. Full production remains under independent original
`blocking-ci`, Source/Worker, Artifact CAS, original Evidence WAL, FinalUse,
rollback and security review. Always **Draft / DENY_ALL / no selection**.
