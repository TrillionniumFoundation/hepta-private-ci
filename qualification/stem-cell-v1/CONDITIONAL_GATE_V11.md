# Conditional specialist preservation is not global no-forgetting

Continuation of Draft PR #1654 from `3b2f080353c64ee5565346adb5fdf4566d75ec03`.
Existing qualification directory, previous loaders, data and retention rules only.
No new runtime, persistent store, live model selector or production activation.
All six V9 and all three V10 controls remain in the paired output census.

## Hypothesis and exact boundary

V10 protects a finite old-input span, reducing available new-task directions.
This alternative freezes the old teacher's OLD-class affine rows and the new
teacher's NEW-class rows instead. They are packed into ONE eight-row readout on
one shared feature, not two complete FiLM modules or Encoder copies. Inference
receives neither true class membership nor a task ID.

Let a_o and a_n be the frozen group logits and g(x) a learned scalar gate:

    log p_old = log_softmax(a_o) + log_sigmoid(-g)
    log p_new = log_softmax(a_n) + log_sigmoid(g)

For any two OLD classes i,j, log(p_i/p_j)=a_i-a_j in exact arithmetic, for EVERY
input, not only old anchors. The same identity holds within the new group.
This is only a conditional invariant: an old input can still be routed to a new
class, and confidence/Brier can still deteriorate. It is not a global retention
or independent-distribution guarantee. The packed affine rows reproduce the
FiLM function only to floating-point tolerance. Output computation rejects
nonfinite intermediates and conditional log-probability cancellation >1e-4.

Five additional controls are explicit:

- `conditional_half`: equal old/new mass, zero gate learning. Not a learned router.
- `conditional_concat`: concatenate frozen selected rows, then ordinary softmax.
- `gate_memory`: train an affine gate on the original 32 old memory rows and 120
  new adaptation rows; frozen experts do not receive optimizer updates.
- `gate_all_old`: the same gate but all 160 old training rows, larger-memory control.
- `gate_score_memory`: use logsumexp(new)-logsumexp(old) as the gate input and
  learn only a scale and intercept, with the SAME 32-row replay. Initialize scale
  to 1 and intercept to 0: its initial probabilities equal the concatenated control.

Raw-feature gates start at zero. All three use AdamW .001/.01, 200 steps, seed
7347 and sampler seed 7349, identical 16-old/16-new sample-index schedules for
matched-memory arms. The normalizer uses only old-base data. Gate-score features
come from the frozen readouts, not gold class indicators at prediction time.

Unshifted trained gates are sealed BEFORE calibration. For each learned gate,
only calibration data chooses among fixed offsets 0,-1,-2,-4,-8,1,2,4,8. Eligible
offsets must satisfy the SAME V9 per-old-class .02 accuracy/Brier floors and
improve new-class calibration accuracy. If none qualifies, keep offset 0. Final
selection still compares ALL FOURTEEN rules using unchanged select_retained.
Offsets are fused into the deployed bias; all grid rows and costs are retained.
The grid is empirical calibration, NOT a confidence bound or significance test.

## First results and explicit exploratory extension

The initial registered four-control experiment kept 120/120 old test successes
but its selected gate_memory achieved only 6/120 new. That failure is retained.
Only THEN was the two-scalar teacher-score gate added as a separate registered
exploratory extension. Both registrations, the first source and first result are
in the delivery evidence. This is NOT independent preregistration: public test
outcomes have been inspected in prior rounds. No thresholds, seeds or offset grid
were changed after either result. No teacher or original control is retrained here.

The final local cached-real-BGE run yielded:

| Rule | Old test correct / 120 | New test correct / 120 |
| --- | ---: | ---: |
| Frozen old teacher | 120 | 0 |
| V9 distilled | 117 | 119 |
| V10 protect all old anchors | 117 | 113 |
| Conditional half | 118 | 117 |
| Concatenated frozen readouts | 119 | 118 |
| Raw-feature gate, 32-row replay | 120 | 6 |
| Raw-feature gate, all-old replay | 93 | 120 |
| Two-scalar score gate | 120 | 1 |

Calibration chooses gate_memory at offset -8. It preserves the original reminder
19/20 calibration correctness and meets the empirical floor, but new-class
calibration accuracy is only .05. The score gate also selects -8 and has .0125
new calibration accuracy. The all-old gate has no supported offset, so remains
at zero and fails retention. A rule requiring merely positive new accuracy can
select a very weak learner. This is NOT achievement of the intended old+new
capability, not statistical superiority and not production promotion. The rules
are deliberately not retuned to turn this result into a success.

The reviewer decomposes every rule's errors into old-to-new, new-to-old, and
within-group mistakes. New gates preserve old internal rankings but redistribute
mass incorrectly. Larger replay alone is not demonstrated to solve this problem.
Some old Brier improvement also comes from conditional renormalization, not new
knowledge acquisition. Strong concatenation/teacher-average controls are retained.

## Costs and replay

At width 384, constants/concat store 3,080 scalars (12,320 FP32 bytes), raw-feature
gates 3,465 (13,860 bytes), score gate 3,082 (12,328 bytes). These are whole packed
Head weights, not total Encoder storage/RSS. Gate learning touches 385/385/2
scalars and adds 600 optimizer steps / 19,200 sample presentations. Previous
teacher learning, anchor experiments, feature encoding and normalization are
retained in source lineage, not declared free. Gate calibration runs 27 candidates
on 161 rows, i.e. 4,347 extra Head rows, explicitly timed. No throughput win is
claimed. Score-gate logsumexp reductions are additional inference arithmetic.

All 5,614 paired calibration/test predictions are reconstructed from saved bytes;
local maximum error is 1.9073486328125e-6, with zero argmax reversals. They represent
240 distinct held-out inputs, not 3,360 independent tests. The reviewer validates
frozen specialist rows, the original unshifted gates, calibration offsets, final
biases, source hashes and cost census. It independently implements forward math;
metrics and offset selection are shared with the producer. It does not replay
optimizer trajectories or attest hardware/clock truth. Coherently fabricated
bundles still need external execution evidence.

The anchor reviewer gains an explicit calibration-only mode, default unchanged.
The new producer removes test labels at its reference-validation boundary. All
input datasets, IDs, meanings and conflicting original labels remain untouched.
The new stage is appended to the EXISTING physical BGE job after V9/V10; no new
runner or relaxation of existing source/merge/global/native checks. Local fitting
uses verified previously encoded BGE features, zero new Encoder calls. Exact-SHA
hosted execution must be checked separately before a fresh-inference claim.

## Reproduce

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v cell_conditional_checks
python3 qualification/stem-cell-v1/cell_conditional_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl \
  --consolidation-run /verified/consolidation --anchor-run /verified/anchor \
  --output /new/conditional
python3 qualification/stem-cell-v1/cell_conditional_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl \
  --consolidation-run /verified/consolidation --anchor-run /verified/anchor \
  --review-run /new/conditional --output /new/scores.json
```

Stable binary-logit training reference: PyTorch BCEWithLogitsLoss documentation,
https://docs.pytorch.org/docs/stable/generated/torch.nn.BCEWithLogitsLoss.html.
The probability factorization, thresholds and results above are this research
protocol, not claims supplied by the documentation. No 10T/100T equivalence.
