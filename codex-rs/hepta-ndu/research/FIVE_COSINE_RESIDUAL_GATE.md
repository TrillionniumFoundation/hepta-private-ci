# Cosine-preserving residual gate on the shared frozen Encoder

2026-10-14. Fixed next DEVELOPMENT experiment following the completed crossed
Head and saved-feature cosine analyses. No Reader, new donor choice, SELECT fit,
production owner change, or pretrained parameter update.

## Hypothesis

Direct cosine on the saved frozen vectors preserved both question and evidence
rankings on all three scoreable SELECT rectangles. The from-zero 6,921-parameter
gate fit all 13 TRAIN pairs but preserved neither joint ranking on SELECT. The
next experiment therefore keeps the validated relation score and learns only an
increment:

```
s(q,e) = cosine(q,e) - t_TRAIN + r_theta(q,e)
```

The scalar `t_TRAIN=0.393732527116822` is loaded from the exact completed
TRAIN-only similarity result and is never refit here. The residual is

```
r_theta(q,e) = w · [tanh(Pq) ⊙ tanh(Re)]
```

with rank 8 and zero-initialized `w`. Initial predictions are therefore exactly
the frozen cosine baseline. No additive question-only or evidence-only term is
available to the residual. At width 384 the residual has 6,152 parameters and
24,608 FP32 parameter bytes.

## Fixed arms and budget

The registered arms are:

1. `cosine_frozen`: no neural fitting;
2. `one_way_residual`: repeat the old `BB=1, AB=0` comparison to four scored
   rows per pair, matching the other arms' row count without inventing corners;
3. `rectangle_residual`: `AA=1, AB=0, BA=0, BB=1`;
4. `rectangle_reversed`: the same four inputs with labels reversed.

Three fixed seeds, 256 full-batch AdamW steps and learning rate 0.003 are reused.
No seed, threshold or checkpoint is selected from SELECT. The one-way arm is a
training-geometry control, not a different compute-free baseline. The reversed
arm checks whether any apparent benefit depends on the intended weak direction.

## Exact data and feature ownership

The study accepts only these completed authenticated origins:

- shared Head source/run `592b5b64... / 38526481788`;
- crossed cache source/run `9da09082... / 38526874475`;
- similarity source/run `5ad9270b... / 38529721933`.

It verifies whole archives, run identities, raw seals, all Head/seed entries,
replayed crossed results, the feature tensor census and the saved TRAIN threshold.
Queued, failed, expired, duplicate or contract-only results are explicit blockers,
not zero scores or permission to use the latest branch output.

The crossed artifact contains all original saved features plus SELECT own-source
features. TRAIN own-source vectors were not previously exported. The runner
therefore reconstructs the complete 14-question dated TRAIN cohort from the
original pinned benchmark, checks that the saved relevance plan is reproduced,
and encodes only missing TRAIN own-evidence components with the same strict
22.7M-parameter archived Encoder. This extra load/forward work is explicitly
measured. Existing cached question/donor/SELECT vectors are not recomputed.
No answer target, label, arm or reviewer field enters the Encoder text.

The original 14 TRAIN and four SELECT recipients remain. Unavailable donor or
reference slots are retained. Cross-family negatives are weak development labels,
not independently certified insufficiency. TEST material never enters the study.

## Readout and falsification

For every four-corner row, report the existing crossed interaction, both question
rankings, both evidence rankings and all four fixed-zero signs. Also report the
threshold-free separability gap

```
G = min(s_AA,s_BB) - max(s_AB,s_BA).
```

`G>0` means some common threshold exists for that pair. A positive interaction
does not imply `G>0`. Across all observed pairs, the common interval

```
max(max(s_AB,s_BA)) < min(min(s_AA,s_BB))
```

is reported without fitting to SELECT. The fixed saved threshold remains the
actual registered decision point.

Candidate results are compared to the frozen cosine baseline using paired binary
criteria, never raw-score subtraction across incompatible models. Missing rows
stay in the denominator. No confidence interval is manufactured from three
reused development pairs or repeated seeds.

The residual hypothesis is falsified for this cohort if balanced rectangle
training does not preserve or improve the cosine baseline's two joint rankings,
if reversed labels behave similarly, or if any gain exists only on TRAIN. Even a
successful weak-pair result would not establish semantic answer correctness,
calibrated utility, Reader-call skipping, Group/NDU gains, an optimal Stem or
quality-matched superiority over replicated 421M models.

## Publication status

Files submitted:

- `shared_gate_cosine_residual.py`;
- `shared_gate_cosine_residual_trial.py`;
- `test_shared_gate_cosine_residual.py`;
- `hepta-cosine-residual-gate.yml`.

The current local Python/container runtime was unavailable. New tests and model
execution are submitted, not claimed passing. `reader_adequacy_established=false`,
`production_accepted=false`, and `five_experiments_completed=false` remain.
