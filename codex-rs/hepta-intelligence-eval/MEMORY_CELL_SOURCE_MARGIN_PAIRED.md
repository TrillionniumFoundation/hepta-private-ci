# MemoryCell paired source-value binding experiment (development only)

This preregistration adds a **same-source, same-reader, same-query** development
comparison of two source-only writer losses. It starts from original source
cohort ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`,
original test plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`,
and pinned Qwen2.5-3B reader revision
`82f42baa094a9600e39ccd80d34058aeeb3abbc1`.
The dataset comprises previously exposed authored controlled events, **not**
a prospective population, human semantic oracle, or production review.

## Hypothesis

The completed prior source-only cross-entropy run (generator
`2c6dae45782b1ba07ba9af237f01bdecc0c5640b`, original artifact
`11689893524`) executed 128 actual updates, but its knowledge adapter had
**zero same-evidence task wins** against the organized frozen reader; the
parameter-only arm scored **0/8**, as did the empty control. The deterministic
organizer already scored **8/8**, hence has no additional strict-success
headroom in that cohort. A lower training loss is not a task improvement.

The new `source_margin` objective uses only admitted original source
facts and explicitly superseded or distinct-relation/entity values as
same-scope hard negatives. The matched `completion_ce` writer is trained
again in the **same Git commit and execution matrix**, avoiding comparisons
between different runtime code revisions. Both use the same pinned corpus,
frozen model, LoRA parameterization, seed, seven task arms, shared read
protocol, maximum **128 optimizer steps**, maximum **65,536 charged input
tokens**, and opt-in source-position vocabulary projection. The Qwen
full-versus-sparse parity receipt must pass before **either** writer trains.

This is a *different loss*. `source_margin` charges both positive and
negative forwards and may use a different subset/order of source examples.
Training FLOPs and optimizer exposure need not be equal: they must be
**measured and reported**, not attributed to the adapter or hidden as free
work. A successful comparison is a **mechanism development experiment**;
it is not a cost-equivalent algorithm superiority trial.

## Same-source paired controls and acceptance

The separate comparison downloads both objective artifacts from the same
workflow run and rechecks their immutable `SHA256SUMS`, exact generating
commit, original source/model identity, read-plan identity, full 56-attempt
seven-arm census, and original raw-answer hashes. The frozen `hybrid`,
`organized`, `empty`, `policy_initial`, and `policy` arms must
remain identical. In `knowledge` and `parameter_only`, actual
selected evidence, prompt input hashes, delivered evidence and derived
expansions must match before task-success deltas can be compared. Changed
answers are not wins. Failed tasks stay in the planned denominator with
explicit missing-outcome bounds, **not 95% intervals**.

A meaningful development signal requires more successful **parameter-only
tasks versus the empty-context control** without corresponding loss on
previously successful tasks. For `knowledge`, the deterministic organizer
is already saturated and a tie provides no evidence of parameter value.
If the margin arm does not improve task success, **reject the candidate**;
do not compensate by cherry-picking examples, prompt changes, extra steps,
lowering abstention thresholds or tightening the scoring denominator.

Both objectives are tested on old controlled tasks and cannot establish
independent generalization, effective N>=200, 99% human citation entailment,
older-task retention, long-term parameter amortization, production rollback
or cross-host recovery. A successful model run does **not** promote an
adapter. No selected-LoRA production default or owner is touched.

## Execution

The only new execution entry is
`.github/workflows/hepta-memory-source-margin-paired.yml`.
It runs a read-only scoped-source contract job, a separate unchanged PR
format check, a two-objective Qwen matrix, and a same-run analysis job.
Output names encode the objective; raw generations, original source
hashes, training charges, failures and frozen-control drift remain available
for review.

No result is assumed until all **exact source-commit** jobs reach terminal
states. Only cite the generating commit, source artifacts and their measured
task outcomes. An unsigned, format-valid citation is not semantic entailment.
