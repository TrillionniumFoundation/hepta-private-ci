# Fixed-update companion

The 20-CPU-second `risk001` study and the `risk128` companion answer different
questions. The first compares quality under a common training CPU allowance.
The companion compares the same seven arms after exactly the same 128 seeded
minibatches and optimizer updates. Neither establishes convergence.

The companion is registered before any `risk001` heldout evaluation. It keeps
all 55 source hashes of the equal-CPU model/training family unchanged and binds
the original protocol hash. It adds only a separate runner, analyzer, this
document, a new protocol and new result directories. Both studies use the same
two copy/MQAR datasets, eight paired seeds, learning rate 0.001, width 32,
batch 32 and optimizer settings. The companion has 112 candidates and 14,336
optimizer updates.

Only the update-128 checkpoint is retained as the selected model. No earlier
checkpoint, learning-rate search or validation choice is available. Validation
is first loaded after that checkpoint identity is durably locked and serves
only as a descriptive evaluation. Heldout access follows the same lock.

Each candidate has a predeclared 900-second **training process-CPU** cap.
The cap is checked after whole updates, and every endpoint overrun is charged.
Exceeding it is a retained failure, including if the crossing occurs at the
128th update. Failed candidates receive no heldout evaluation and cannot be
rerun or replaced to fill the matrix. Setup, hashing, checkpoint writes and
evaluation are outside this training cap but included in complete-worker
`wait4` CPU. The cap is not a fixed full-worker timeout or a claim that every
candidate will spend 900 seconds. The registered timing forecast is derived
from training-only batch-32 preflight, separate from observed costs.

Four primary contrasts and three descriptive comparisons are identical to
`risk001`. Each seed first contributes the average of its two task accuracy
differences; eight independent paired values enter the sign-flip test. Each
study applies Holm correction within its four-primary family. An advantage
claim without an equal-CPU/equal-updates qualification requires the
corresponding gate to pass in **both** families. A pass in only one family must
be reported under that specific regime. The analyst cannot choose the better
family, pool tasks as extra independent replicates or choose a checkpoint
after seeing results. Family-specific positives do not carry a claim of
global family-wise error control over the union of both study families.

```bash
python -m experiments.hcsn_risk_ablation_v1.equal_updates register \
  --output experiments/hcsn_risk_ablation_v1/results/risk128

python -m experiments.hcsn_risk_ablation_v1.equal_updates run \
  --output experiments/hcsn_risk_ablation_v1/results/risk128

python -m experiments.hcsn_risk_ablation_v1.equal_updates_analysis \
  --study experiments/hcsn_risk_ablation_v1/results/risk128 \
  --output experiments/hcsn_risk_ablation_v1/results/risk128_analysis \
  --equal-cpu-analysis experiments/hcsn_risk_ablation_v1/results/risk001_analysis/RESULTS.json
```

Two one-thread workers run in parallel. A failure or `STOP_REQUESTED.json`
stops additional launches, drains active workers and preserves every result
and all measured costs. This is a post-baseline exploratory study on previously
observed datasets, with finite-state physics and equal-capacity engineered
feature replacement. It is not a new-test confirmation, natural audiovisual
benchmark, quality-matched deployment comparison or foundation-model study.
