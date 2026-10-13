# Cell-conditioned Head consolidation

This is an offline continuation of the existing frozen-feature/Head experiment,
not shared-Stem retraining or a product model selector. It consumes the exact
producer report (externally supplied SHA256), original manifest/dataset,
`frozen-features` and saved `heads/gated` candidates. It loads no Encoder/tokenizer.
The same global class vocabulary is required across the 2–64 input Cells.

Each row gets its own Cell teacher's logits, not an average of unrelated teachers.
A single existing gated Head sees the original feature plus an exact one-hot
encoding of the observed Cell identity. That encoding is used in every student
arm and costs input/parameter storage; it is not learned routing or a hidden label.
The existing Head artifact format is reused with a distinct feature-profile hash
and logical shared-candidate identity. Original Cell weights/feature files do not
change. No CURRENT, execution privilege, NDU subject or durable owner is added.

Compare the unchanged teacher bank and shared frozen initialization with three
SAME-initialization/sampling/budget students: hard-label supervision, pure KL
teacher distillation, and a 50/50 mixture. Temperature is fixed at 2; the loss is
`(1-w) CE + w T^2 KL(q_teacher,T || p_student,T)` using `batchmean`. The original
`execution.fit` supplies AdamW, minibatch replacement and norm-1 clipping. Its
no-soft-target branch preserves existing arithmetic. This is conventional
knowledge distillation (arXiv:1503.02531), not a new NDU solver. No teacher outputs
are collected from holdout rows for training; the bank is retained as a control.

All students train to the declared ceiling. Calibration can retain a smaller
student only when every Cell's observed calibration correct count is at least
its bank count; rank by total correct, parameter count, NLL, then name. The bank
is always eligible. This empirical floor is NOT a confidence bound or guaranteed
retention. Reusing calibration for this finite comparison can overfit. Seal the
selection before holdout inference; all arms' predictions are then sealed before
scoring, with per-Cell outcomes retained. No test-best substitution or promotion.

```sh
python -m experiments.shared_stem_cell.consolidation_study \
  --manifest /staged/manifest.json --producer /staged/producer \
  --report-sha256 <externally-verified-sha256> --output /new/consolidation
```

The existing public-pretrained job stages only the small required inputs in a new
directory and runs this command in a fresh process after scalar/grouped feature
replay. Teacher target generation, original inherited teacher work, each student's
fit, calibration, input augmentation, inference, and artifact export/reopen are
reported separately. Three student updates cost three budgets, not one. Parameter
counts describe each deployment candidate, NOT this comparison process's peak
memory; teachers and all students coexist in the experiment. No matched-FLOP,
energy, latency, independent future, or multimodal-generator gain is implied.
Already exposed public data remain development data, never a new holdout claim.

`python -m experiments.shared_stem_cell.consolidation_digits --output /new/digits`
also runs the fixed three-seed, eight-Cell bundled real-image development trial.
It uses raw 8x8 pixels/16, no pretrained Encoder, and seals ALL seeds' predictions
before reading holdout labels. The already used dataset is not independent future
evidence; input content, fold and route assignments are saved without relabeling.
