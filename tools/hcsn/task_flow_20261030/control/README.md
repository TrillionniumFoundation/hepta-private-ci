# Task values and actual local execution: completed negative control

**Execution and causal checks passed. The learned task-value policy failed the
predeclared superiority test.** Its primary mean utility is **0.26085**, versus
**0.68655** for the matched ordinary action-boundary readout. The paired
difference is **−0.42570**, with the family-adjusted 95% interval
**[−0.61008, −0.24132]**. All original outcomes and all three price conditions
are retained. This experiment does not establish a financial-operator advantage.

## What actually ran

The source baseline is `b1934022821f3fdafd509b43cf0c4d7d45852e6e`.
`freeze.json` fixed protocol and source identities before new packet/session
generation. No frozen scientific source was modified after that freeze.

The content adapter executes the existing learned FullHX NumPy recurrence and
mass-consistent associative read from `third/memory/reference.py`. Its 6,217
parameters come from the preselected `memory_full_mass_seed29.npz`, SHA256
`4962cd6126dc5e393cf7dbe72bea5519125bfb7971a7e3665a36af908aff5fcb`.
Those content weights remain **frozen**. A READ does not decode the answer from
a packet field: it constructs the inherited 16-coordinate sequence, executes
the learned recurrent content model, and obtains four logits. The binary task
uses the declared classes 0 and 1; all four logits are preserved in each trace.

Five new seeds each create 60 train, 24 validation and 40 heldout sessions.
Each session contains two independent hidden-label jobs, noisy content packets,
public quality/price schedules, a deadline and a shared read budget. All policies
can access the same public metadata. Hidden job labels are opened by the scorer
only after the owner has terminated and persisted its execution trace.

The seven policies and three public read-price multipliers produce **4,200
heldout policy sessions**, with **6,464 actual packet reads and content
invocations**. The separate TRAIN-only decoder-error calibration uses 640 actual
content invocations. These are not 4,200 neural training runs: the new learned
components are 15 small readout fits, with 45 retained ridge candidates. Each
readout has 160 coefficients, the same feature map, three ridge choices and the
same generated training states. The content backbone was not retrained here.

## Task values, reset and refractory continuation

Actions are `READ`, `SKIP`, `FIRE` and `STOP`. READ invokes the actual local
file/content backend and incurs the public read charge. SKIP advances time
before constructing a payload path or invoking the content model. FIRE emits
an answer, resets the task belief to 0.5 for the next job, and consumes a firing
tick plus one refractory tick. STOP is terminal and forfeits remaining jobs.
There is no automatic successful answer at the deadline.

Correct FIRE answers earn +1; incorrect answers earn −1. The primary utility is
the sum of those rewards minus charged read costs. The maximum uncharged reward
is 2 per session. Answer accuracy is reported together with completed jobs, so
answering fewer jobs cannot be hidden behind an accuracy-only statistic.

The small reference oracle performs finite Bellman recursion using the
TRAIN-calibrated decoder confusion matrix. It integrates possible future
observations; it never receives realized future packet contents or labels.
Its FIRE value contains the next-job continuation after reset. An independent
one-read calculation gives 0.43 and agrees with the recursion. In the recorded
two-job mathematical fixture, full FIRE value is 1.583024, versus 0.8 when
post-FIRE continuation is deliberately removed.

This oracle is exact **for its fitted finite observation model**. The fitted
error law need not equal every deployment distribution; there is no claim of
globally optimal native Hepta control or a solved coupled-neuron QVI.

## Heldout quality and real runtime

The primary multiplier is 1.5. Rows average 200 paired heldout sessions.
Wall time includes metadata I/O, policy computation, packet I/O, feature
construction, the inherited content model, dispatch and trace serialization.

| Policy | Utility | Correct / all available jobs | Completed jobs / session | READ / session | Mean complete wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Learned full task values | 0.26085 | 48.25% | 1.570 | 1.065 | 10.493 ms |
| Ordinary learned action boundary | 0.68655 | 51.50% | 1.280 | 1.275 | 12.875 ms |
| Learned first-event values | 0.27560 | 55.75% | 1.850 | 1.065 | 10.738 ms |
| Same-information myopic control | 0.87415 | 65.50% | 1.515 | 2.470 | 23.289 ms |
| Fixed two-read policy | 0.71170 | 75.00% | 2.000 | 2.910 | 27.465 ms |
| Fitted-model exact DP | 1.18345 | 82.50% | 1.955 | 2.035 | 23.675 ms |
| Immediate STOP | 0 | 0% | 0 | 0 | 0.399 ms |

The learned-value readout runs faster here because it reads less, but it loses
substantial task utility. This is not an equal-quality speedup. The exact DP
reference is useful on this small task, but its behavior is not reproduced by
the cheap learned value readout.

| Read-price multiplier | Learned value minus ordinary boundary | Family-adjusted 95% interval |
| --- | ---: | ---: |
| 0.5 | −0.43735 | [−0.67169, −0.20301] |
| 1.5, primary | −0.42570 | [−0.61008, −0.24132] |
| 3.0 | −0.38780 | [−0.59351, −0.18209] |

Intervals describe five paired independently generated cohort/controller-fit
means under a small-sample Student-t assumption. They are not an architecture
scaling law or a statement about all possible value-boundary models.

## Approximation failure and the retained diagnosis

The selected learned-value regressors already disagree with their DP teacher
on roughly 53–57% of validation states; ordinary action readouts disagree on
roughly 14–17%. Thus implementing the correct task-value target is insufficient
to obtain a good learned policy.

The original fit also regresses an arbitrary −4 sentinel on infeasible actions.
`diagnose_validation.py` is a **post-hoc TRAIN/validation-only** investigation,
written after the original test results were exposed. It changes only that
fitting convention for analysis; it does not recompute any heldout prediction.
Masking those targets reduces value-readout validation disagreement only to
43–49%, versus approximately 12–14% for the ordinary control. The problem is
therefore not resolved by that patch. The compact value features summarize the
current job's future schedule and omit the next job's reliability/price schedule
entirely. Full FIRE value depends on that omitted public information, creating
representational aliasing before optimization. The matched learned readouts use
the same compressed features; the DP reference can use the full public schedule.
A better
representation or value-to-action training design needs a new prospective
protocol and fresh evaluation; the present failed gate remains failed.

## Costs and amortization

The complete study runner used 93.045 wall seconds and 84.503 CPU seconds on
the recorded shared CPU environment. It includes data preparation, calibration,
oracle-label construction, all candidate fits, evaluation and result writes.
Imports before entering the runner are separately recorded (2.163 seconds).
Data construction took 6.001 seconds. The independent audit took 6.055 seconds;
it is not counted as model training or runtime savings.

`analysis.json` includes every policy's measured quality/cost point and a
runtime-penalty sensitivity grid: 0, 0.1, 1 and 10 utility units per second,
with setup amortized over 1, 100 or 10,000 sessions. It explicitly includes
content loading/calibration, source import, data construction, oracle target
preparation and candidate fitting. These are sensitivity assumptions, not
measured energy prices. For example, at penalty 1 and 100-session amortization,
primary learned-value utility becomes −0.01479, ordinary-boundary utility
0.40859, and exact-DP utility 1.01668. Deployment setup allocations are not
added together to estimate the actual total study cost.

No GPU, energy measurement, native Rust owner, production rollout, or equal-
quality large-model advantage is claimed.

## Actual execution and evidence checks

`audit.json` verifies all 4,200 traces, 6,464 test backend invocations and 11,793
dataset files. It independently recomputes rewards and action counts. The
causality fixture removes all packet files before SKIP/STOP, demonstrates that
STOP rejects further READ calls, changes a read payload and observes an 11.079
maximum logit change, and serializes/restores an owner before executing the
second job. Recovered task state, actions, answers and backend counters match
the uninterrupted run. Metadata loading for a new owner is initialization work;
the checkpoint counters represent the logical resumed session.

Raw data and traces are delivered losslessly as `raw_data.zip` and
`raw_traces.zip`, covering 15,993 original per-file SHA256 identities. A first
whole-ZIP write encountered shared-filesystem ENOSPC. The recovery compacted
only this package's own duplicates, removing each unpacked copy only after a
closed ZIP chunk was independently hash-verified, then consolidating and
reverifying the two final archives. Scientific source and result hashes remained
unchanged. `packaging_receipt.json` preserves this operational failure and fix.

`restoration_validation.json` records an actual separate-directory restoration
of all 15,993 members; all hashes passed. The local originals were also restored
and verified. Unpacked copies are excluded from Git to avoid thousands of tiny
duplicate files. The standard-library restoration script rejects unknown
members, path traversal, archive mismatches and conflicting existing files.

Restore and replay the audit from this directory with the recorded dependencies:

```bash
python restore_evidence.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python audit.py
```

The runner refuses to overwrite existing outcomes. For a literal rerun, preserve
the delivered directory and execute the frozen source in a separate copy with
fresh output paths. Do not reinterpret such a replay as a new confirmation.

Machine-readable evidence: `protocol.json`, `freeze.json`, `data_manifest.json`,
`results.json`, `analysis.json`, `audit.json`, all `fits/` candidates and source
provenance, all `traces/`, the original raw `data/`, and the explicitly exploratory
`validation_diagnosis.json`.
