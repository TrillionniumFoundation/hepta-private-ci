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

## Partial consolidation with retained specialist Heads

`--partial` on either existing study adds a calibration-only comparison without
changing the original five arms or fitting another model. For each shared
candidate, assign a Cell to it only if that Cell has calibration coverage and its
correct count is at least the bank's. Keep that Cell's original teacher otherwise.
Count ONE shared Head plus EVERY retained teacher, including the existing one-hot
input parameters. A candidate is eligible only if it uses strictly fewer Head
parameters than the bank. Rank by calibration correct count, parameters, NLL and
name; the unchanged bank is always an option. This is a fixed Cell assignment,
not per-request confidence gating, a new NDU subject or a deployment decision.

The two-Cell case illustrates the cost boundary: a 6,224-parameter shared Head
plus one retained 6,192-parameter Head is larger than the original 12,384-parameter
bank. It is rejected, not advertised as a compression. These are the actual gated
Head shapes in the public 384-dimensional feature trial, not process RSS numbers.

The selected policy is sealed before holdout inference. Each row executes only
its assigned Head; the shared Head receives only its assigned rows, and retained
teachers receive only their own rows. Full original controls remain separately
executed and billed. The offline `partial-bundle` contains only the selected
components using the existing Head format. External bundle SHA256, exact files,
component identities and total allocation preflight are checked before reload.
No Encoder/tokenizer is loaded. Original teachers and CURRENT are not modified.
The comparison process still holds all candidates, so candidate parameter savings
are NOT measured process peak-memory, energy or latency savings.

```sh
python -m experiments.shared_stem_cell.consolidation_digits --partial --output /new/partial-digits
python -m experiments.shared_stem_cell.consolidation_study --partial \
  --manifest /staged/manifest.json --producer /staged/producer \
  --report-sha256 <externally-verified-sha256> --output /new/partial
```

Per-Cell calibration nonregression is an empirical selection rule, not a promise
of future retention. All per-Cell heldout scores remain reported, even when total
accuracy improves. These reused public/digit cohorts remain development evidence;
no new independent task window or product acceptance is created by this option.
