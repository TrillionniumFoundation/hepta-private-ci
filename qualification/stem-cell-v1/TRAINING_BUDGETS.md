# Independently budgeted Cell training and source-specific BGE evidence

Parent source: `28626b8e055e49df124c305fe1f5f05183856999`. This continues the
existing grouped SGD fitter and learning consumer; no new optimizer, persistent
Cell owner, authority, live selection or learned resource allocator is introduced.
Earlier fixed-budget baselines, tests and negative outcomes remain unchanged.

## Per-Cell steps are a frozen plan, not a holdout-selected policy

`fit_linear_cells` and `fit_gated_cells` accept optional `step_counts`, one exact
integer per Cell in `[0, steps]`. Omission keeps the original uniform schedule.
Every Head, label, row and aggregate resource bound is checked even at zero
steps. Zero-step Cells return unchanged private candidate copies and never enter
an optimizer. Finished Cells leave the actual matrix batch; a gradient mask over
still-computed idle Cells is not substituted for compaction. Each remaining Cell
keeps its original minibatch generator, per-Cell mean loss and independent norm-1
clipping. Partial failures return no candidate collection and never retry.

Compaction preserves only the existing stateless SGD profile: momentum and
weight decay are explicitly zero. There is no unobserved momentum/scheduler
state to drop or reset. Stateful optimizers need a separate state-migration
implementation and validation; this code must not be reused for them unchanged.

The existing `run_shared_learning` accepts `training_steps_by_cell`, an exact
Cell-keyed mapping snapshotted before Encoder work. The real-weight CLI accepts
`--training-plan /path/plan.json --training-plan-sha256 HASH`; supply both or
neither. Example for exactly two Cells: `{"a": 0, "b": 4}` with `--steps 4`.
Plan bytes are rechecked before publishing predictions. This hash is integrity,
not production authorization. Gold heldout labels do not enter planning or fitting.
The caller chooses the plan; neither its quality nor NDU optimality is established.

The scalar consumer previously applied the 4,194,304-total-parameter bound only
to grouped fitting. Both paths now enforce it before any Head construction.
A 64-Cell/512-input/128-class regression requests 4,202,496 parameters: the old
scalar code entered Head construction, the new scalar and grouped paths reject.
Encoder execution can still precede this width-dependent check. Zero training
steps do not mean zero Encoder cost, no inference, physical memory release,
persistent dormancy or permission to ignore invalid source data.

## Matched execution experiment

`development_training_plan_study.py` fixes seeds 1919/2929/3939 before training,
uses both original scalar `fit_candidate` and grouped fitting independently,
and saves all output bytes before scoring. The per-Cell pattern is 0/1/4/8 steps
(single-Head control: eight steps). Both arms receive the SAME plan, samples,
initializations and random minibatches. A fixed eight-step run is not used as an
equal-quality speed comparator. Each arm receives eight warmup example updates
on separate data; framework cold start and warmup time remain separately charged.

Three fresh-process CPU measurements (one thread; synthetic features):

| Heads / input / hidden / classes | Scalar / grouped complete-fit wall ratio |
| --- | --- |
| 1 / 16 / 8 / 2 | 0.757..0.858; grouping is slower |
| 64 / 384 / 8 / 4 | 2.145..2.324 |
| 256 / 384 / 8 / 4 | 2.255..2.389 |
| 4096 / 64 / 4 / 2 | 2.336..2.840 |

The largest profile has 1,024 zero-step Cells and 425,984 useful example updates
in EACH arm. Optimizer calls are 13,312 scalar versus 1,024 grouped. Actual matrix
lanes and active segments are recorded, including padded lanes. Across 212,016
correlated prediction positions, class choices agree; maximum parameter/logit
errors are 2.981e-8 / 1.789e-7. Parameters are not bitwise equal. Only 16 heldout
source inputs and four synthetic task definitions exist per profile. Few-step
training is not convergence: two largest-profile seeds lose accuracy against
their own frozen Heads, and these results are retained. No p95/p99, energy, RSS,
learned allocation or real-task quality advantage is established.

An initial run exposed cold optimizer initialization bias in the single-Head
comparison. Its original source, outputs and times are retained but are not
accepted as steady-state performance evidence. All three final studies use the
same corrected, predeclared equal-warmup protocol; no seed or score is discarded.

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v development_training_plan_checks
PYTHONPATH=qualification/stem-cell-v1 python \
  qualification/stem-cell-v1/development_training_plan_study.py --synthetic \
  --seed 1919 --output /new/external-training-plan-study
```

## Parent BGE evidence is real, but not evidence for a later SHA

Parent run 38343044956, real-BGE job 115118105135, completed successfully with
41 stock-Torch/safetensors/BERT tests and all three unchanged four-arm studies.
Artifact 11787534845 SHA-256:
`d4698d73490325eb7febba991ad88ee565ce82b99266cbb151362bdaf5605439`.
Every saved prediction hash, identity, score, numerical comparison and call-count
arithmetic was independently recomputed without running the trainer. This is
reproducibility checking, not an independent outcome evaluator's signature.

The actual frozen BGE has 23,953,920 parameters. There are 40 authored diagnostic
sentences (24 train, 16 heldout), eight randomly initialized SwiGLU Heads, four
binary task definitions and two replicas per task. Frozen-random-Head correct
counts are 56/58/64 of 128; trained counts are 122/118/112 for seeds
1414/2525/3636. All four paths agree in class choices within the registered
numerical tolerance. These are not eight independent tasks or 128 independent
heldout source observations, nor a pretrained typed-Head zero-shot benchmark.

Encoder calls: singleton 320, batch 10, cache/grouped 2. Actual encoded input
rows: 320, 320, 40, 40. Complete learning-call wall times are approximately
4.43..4.49 s, 2.34..2.37 s, 0.68..0.69 s, 0.397..0.402 s, respectively.
Singleton/grouped ratio is 11.06..11.29 on this diagnostic corpus. Acquisition
and one shared physical model load are outside these call times and reported
separately. No cloned-421M comparison, production latency or best-Stem selection
is implied. The 71 state tensors plus one ordinal position buffer are checked
before and after execution, without modifying the checkpoint.

The SAME parent workflow's generic head and merge jobs FAILED at importing
`safetensors.torch`: `packaging` was missing. This continuation explicitly installs
`packaging==25.0` in that environment and checks the import before the unchanged
test suite. It does not skip tests or change the verifier. New-source hosted
results, including another real-BGE run, remain mandatory. Local sparse-source
execution: 152 tests pass, zero failures/skips (134 retained + 18 new); this is
not all repository tests or the 41 HF tests. The default profile, real loader,
64-Cell/4096-row consumer envelope, global security gates and Draft status remain.
