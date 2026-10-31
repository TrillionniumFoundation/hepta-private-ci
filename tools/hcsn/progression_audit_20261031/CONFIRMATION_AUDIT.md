# Independent post-freeze confirmation audit

All three completed confirmation audits pass within their declared scope. The
teacher study fails its learned-policy admission gate. The finite value-boundary
study demonstrates gains over its fixed threshold on its eight declared
contracts. The identical-policy ordinary/analytic comparison is exactly null.
The native backend qualifies for the explicit Q24 contract, with a retained
reporting-only failed attempt and a successful repaired rerun. None of these
results enables mainline or production activation.

The candidate source and training artifacts remained frozen throughout this
audit. New audit code was added separately. The statistical code does not call
the candidate's `analyze`, `diagnose`, interval or aggregation functions.

## Teacher-policy confirmation

The auditor verified 26,967 confirmation artifacts and all 688 preparation
artifacts. It rebuilt all 3,840 rollouts, 23,046 decisions, 7,792 actual READs and
5,034,080 payload bytes, grouped by `(seed, split, session_id, policy)`.

All 2,935 distinct accessed payloads were read again and passed through the real
frozen content decoder: the maximum logit difference was zero. The auditor
independently rebuilt the finite Bellman recursion, OneRead plans, 65 public
features, Q24 transform and residual inference. Maximum score difference was
`4.44e-16`; all actions, legal masks, posterior updates, shared budgets, task
durations, resets, charged costs, terminal labels and scores matched.

The five paired training-seed estimates and all twelve declared CPU accounting
scenarios reproduce the candidate report. At the primary accounting price of
one utility unit per CPU second and 1,000-session amortization:

| Residual minus OneRead | IID | Stress |
| --- | ---: | ---: |
| Task utility difference | 0.00662734 | 0.01021563 |
| 95% paired-seed interval | [−0.04008954, 0.05334423] | [−0.03428741, 0.05471866] |
| Holm-adjusted primary p | 1 | 1 |
| Correct jobs / 2 difference | 0.00234375 | 0.00703125 |
| Correct jobs / 2 interval | [−0.01120226, 0.01588976] | [−0.00402902, 0.01809152] |
| CPU-adjusted utility difference | −0.03242075 | −0.02887079 |
| CPU-adjusted interval | [−0.08117426, 0.01633276] | [−0.07514949, 0.01740790] |

The two-percentage-point quality noninferiority gate passes; the positive task
utility and full-cost gates fail. Negative adjusted point estimates are not a
proof of universal inferiority, since their intervals still cross zero.

The enclosing confirmation process used `92.195951` CPU seconds. Its internal
timer reported `90.021008463` seconds. Policy execution (`67.791822660`), raw
persistence (`1.260774753`) and teacher diagnosis (`14.866759921`) are nested
components, and are not added again to the enclosing total. Independent audit
CPU was `30.156694314` seconds and is separate research verification overhead.

## Finite value-boundary confirmation

The auditor verified 69,172 confirmation artifacts and 112 preparation
artifacts, then rebuilt all 5,120 independent episode tapes and 25,600 policy
rollouts: 123,908 decisions and 81,836 actual READs. It independently applied
the one shared hidden deadline to READ waiting and all recovery phases,
reconstructed legal budget/quality guards and posterior evidence, and rescored
all submissions and costs from the terminal evaluator labels.

The eight finite-support content inputs were decoded again. Every accessed
payload was checked against that exact input support and its recorded digest;
all actual decoder logits matched the reexecution. The repeated nonce fields
are outside the decoder's input. This exhaustive finite-support check does not
establish natural-content accuracy.

The auditor checked 99,649 recorded first-FIRE probabilities with an independent
embedded-event/Poisson-tail reference. Maximum difference was `3.00e-15`.
All 5,120 ordinary/analytic identical-policy physical trajectories are equal.

All conditional-episode and five-fit cluster intervals, all twelve CPU scenarios,
and equal-weight finite-contract Welch aggregations match the raw rows. The
primary hard-boundary-minus-fixed result across exactly the eight contracts is:

| Quantity | Estimate | 95% fit-cluster aggregate interval |
| --- | ---: | ---: |
| Task utility | 0.14023470 | [0.11957755, 0.16089186] |
| CPU-adjusted utility, κ = 1, H = 1,000 | 0.14186113 | [0.12121459, 0.16250766] |

These are descriptive intervals for the declared finite contract set, with the
study's stated unadjusted multiplicity convention. The contracts are not draws
from a demonstrated deployment population. Each contract is replanned/refitted.

Quality must be presented alongside utility. Equal-weight differences in
correct jobs / 2, wrong jobs / 2 and completed jobs / 2 are respectively
`+0.07578125`, `+0.03466797` and `+0.11044922`. More submissions produce more
correct and more incorrect answers. In the declared all-STOP stress control,
utility increases by `0.16446617` while correct jobs / 2 decreases by `0.0359375`.
The common 0.75 posterior submission guard passes; cross-contract quality
noninferiority was not established or claimed.

Enclosing policy CPU totals `310.542710205` seconds, the complete confirmation
stage is `332.743770046` seconds, and the external process lifetime is
`333.507513` seconds. Per-policy preparation, deployment serialization and actual
loading were independently recomputed and amortized once. Independent audit
CPU was `24.649336491` seconds.

## Native qualification and preserved failure

The original native harness completed all data and wrote `REPORT.json`, then
failed at its final print because `flush=True` was passed to `json.dumps`.
The auditor inspected the actual traceback and verified the repaired source is
byte-identical except for moving that argument to `print`. The original source,
reports, process exit 1 and reporting-repair record are retained.

Both attempts contain the same five frozen models, exactly validation rows
512:1024 per model and the first 16 confirmation sessions per split/seed. Each
attempt has 2,560 numeric vectors, 160 actual paired tasks, 666 READs and 320
completed-effect restores. All native Q24 scores and actions independently
match; maximum score discrepancy is `4.44e-16`. Six original float64 pseudo-tie
action differences remain explicitly reported. The two attempts' physical
effects are identical and also match the independently audited original task
confirmation. The repeat supplies no extra independent efficacy sample.

| Measurement | Original attempt 01 | Reporting repair attempt 02 |
| --- | ---: | ---: |
| Process exit | 1 | 0 |
| Completed data qualification | Pass | Pass |
| Python mean complete CPU / task | 0.02383774 s | 0.02613452 s |
| Native mean complete CPU / task | 0.04551409 s | 0.04994223 s |
| Enclosing process CPU | 19.722267 s | 21.208040 s |

Both measured native paths are slower. They include durable journal/witness and
restart work, while the Python path uses trusted snapshots; this is not an
equal-durability comparison between programming languages. Native child CPU is
not added again to the enclosing process usage.

The auditor initially imposed an unregistered 10-microsecond equality tolerance
between successively sampled parent and complete CPU fields. One valid row had
15.423 microseconds of intervening process work. That failed audit and its source
are retained separately. The corrected auditor verifies the actual sequential
sampling relation and reports the discrepancies: maximum 15.423 microseconds in
attempt 01 and 3.926 microseconds in attempt 02. Candidate data were unchanged.

## Files and conclusion boundaries

`CONFIRMATION_AUDIT_SUMMARY.json` contains the compact consolidated results.
`TEACHER_CONFIRMATION_AUDIT_01.json`, `VALUE_CONFIRMATION_AUDIT_01.json.gz` and
`NATIVE_CONFIRMATION_AUDIT_02.json` retain the complete checks and statistics.
The compressed value report preserves its original uncompressed SHA256 in the
summary. `NATIVE_AUDIT_FAILED_01.json` and both native-auditor source versions
preserve the audit correction.

No positive independent analytic-cell gain, native cell physics, arbitrary-crash
external-effect settlement, hardware energy saving or production admission is
established. The directly supported advance is a finite task-value boundary
with real subsequent effects, reliable propagation and transparent cost,
alongside a stronger ordinary planner and a faithful native policy interface.
