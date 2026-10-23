# Content-control TRAIN result, 2026-10-23

The new residual refiner **failed its TRAIN hypothesis**. Retain the original
dense additive method as the stronger observed content method. No formal test
was constructed, opened, read or rerun. CORE c1 remains a failed, consumed
confirmation; r2's formal test remains shut. These results do not qualify NDU,
dynamic control, AV generation or an open-world multimodal model.

Work is isolated on `research/content-control-budget-20261023`, starting exactly
at `0aca16714390ca045a53cece9644992b7990fc9c` from PR3451. The initial configured
checkout was `f8c9419df6ddeb36ff8b522a50219981fb8d9345` on `work`; it was not
treated as research progress. Actual repository/cwd is
`/workspace/hepta-private-ci`, origin `TrillionniumFoundation/hepta-private-ci`.
Execution hostname `aa01407f34e9`, Python3.12.14, NumPy2.3.5, Pillow12.3.0;
BLAS/OMP/MKL thread counts explicitly1. Root AGENTS.md was read; `.agents/skills`
does not exist. The supplied main-task ID identifies the parent's task, not a
verified ID for this independent workspace. No user-computer tool was used.

## Evidence and mechanism

The old CORE **TRAIN-only** diagnostic reads explicit base/selected model files,
the H/A build receipts and plan. It never reads old test inputs, results or
marker contents. For old selected seeds11/23/47, H had533/459/388 updates and A
462/432/249. On easy rows the additive contribution's logit-gradient norm was
about8.5 times the fixed0.2-CE contribution; on rare low-probability errors it
was small, and sometimes opposed CE. The reward penalizes disagreement even
when one head is correct, creating a possible wrong-consensus mechanism. This
is a diagnostic hypothesis, not a causal explanation of the formal CI failure.
See [the saved diagnosis](../runs/content-control-train-diag-20261023/diagnosis.json).

The new experiment reconstructed only the old CORE TRAIN generator once per
build. Source index modulo4 forms144 fit/48 inner-validation physical sources;
all instructions/variants stay together (2304/768 rows). Fresh bases saw only
fit sources. Every arm used the same three bases and LR set0.001/0.003/0.01.
The refiner adds1080 trainable parameters, holds h fixed, and actually updates
text/image logits through T/I/J residual corrections. It trains the mean of the
five joint categorical path losses TT/TI/IT/II/J, backpropagating through cross
head softmax feedback. There is no learned schedule, early exit, NDU search,
changed reward, label-based serving or marginal-mixture approximation.

All numbers below are selected **TRAIN inner-validation** diagnostics. Every
system searched three LRs; refiners additionally searched all five fixed paths,
paying for that larger search. Selection used the same rows summarized below.
Descriptive intervals therefore cannot be used as confirmation p-values.

| Arm | Selected LR/path | Utility | Joint success | Complete CPU seconds | Declared units, billions | Selected updates, seeds11/23/47 |
|---|---|---:|---:|---:|---:|---|
| Full CE S | .01/full | .973357 | .971883 | 5.043679 | 11.664350 | 396/396/396 |
| Same-anchor H | .01/full | .973357 | .971884 | 5.023574 | 11.664350 | 396/396/396 |
| Additive A | .01/full | .975998 | .974624 | 5.409933 | 11.664059 | 387/387/387 |
| Refiner H_R | .01/TI | .969441 | .967641 | 8.127060 | 11.658602 | 445/445/445 |
| Refiner A_R | .01/TI | .968619 | .966800 | 8.345217 | 10.621075 | 359/363/370 |

Dense A-H utility was +.00264133 (descriptive crossed seed/source95% interval
[+.00107229,+.00412074]); joint success +.00274035
[+.00105271,+.00431421]. Utility gains were+.00302731/+.00233187/+.00256481
for all three seeds, despite A receiving fewer updates. Greedy joint success
was unchanged. This is useful prospective TRAIN evidence for the original
content contribution, with no change to the failed formal result.

A_R-H_R utility was -.00082200 [-.00196960,+.00025399], negative for all three
seeds. A_R-A was -.00737952 [-.01180580,-.00325826], and A_R-S was-.00473780.
The new architecture neither improved content contribution nor beat effective
static generation here. S and H were nearly identical: under Adam a constant
positive gradient rescaling largely cancels between first/second moments,
apart from epsilon/clipping effects. The anchor coefficient alone is not
evidence of a materially different supervised optimization trajectory.

## Why no policy was trained

At the selected A_R checkpoint, the label-known source-oracle headroom across
all five paths was .00024059/.00007102/.00008706 (mean **.00013289**).
Per-row oracle headroom averaged .00025070. All48 sources/seed are retained;
TI and IT cross, but their value differences are tiny. Even an unimplementable,
free per-row oracle would still trail dense A in raw utility by .00712882.
This upper bound is conditional on these frozen selected states, not a theorem
about every refiner. The preregistered source-oracle threshold was .002, so the
initial-state gate branch was not executed and gate fit work was zero. No larger
or feedback policy was trained. Deterministic state updates reveal no fresh
external information; sequence feedback needs comparison with an initial gate.

## Complete budget and retained failures

All five complete builds stayed under the unchanged10 CPU-second/12B-unit
limits; the caps are ceilings, not equal measured consumption. Common preparation
2.075925876 CPU seconds/3,486,924,537 units includes dataset generation,
three decoder300/base500 trainings, imports, actual C compilation
(.382784261 CPU seconds), observers and base exports/calibration. It is
attributed in full to every arm. Refiner-only feature preparation/export adds
.212571458 seconds/138,037,248 units to each refiner. Each arm also pays all nine
candidate trainings, search/validation, gradient evidence, model exports,
selected PNG/hash/JSON service, external reload checks and decoder corruption.
Actual scheduler/setup CPU .004935890 is charged in full to each arm. No unused
critic, repeated formal look, padding, reserved estimate or unexecuted kernel
is charged. Native Adam is used for the effective dense controls; refiners use
the original NumPy Adam with smaller parameter arrays.

The physical combined five-arm execution consumed23.479634726 CPU seconds;
attributed per-arm totals exceed physical work because common work is charged
in full to each. There were45 completed candidates, all retained (nine/arm).
All15 selected decoder-corruption drops were positive; per-request declared
work remained below two full equivalents. Service is the shared Python batch
path and actual learned12-code PNG output, not a native serving-speed claim.
Complete CPU-net utility at price.02/H100000 was S .96155248, H .96182069,
A .96391759, H_R .95652793, A_R .95613350. The frozen denominator is one actual
pre-adaptation base11/64-fit-row calibration,173939.703125 ns/request. These
CPU values are conditional on one timing wave and have no cross-wave CI claim.

The first construction at `512b0182a7` exited1 **before content training or any
candidate score**, because the counted model's clone retained instrumentation.
Its trace, partial ledger, native binary, input data and original exit remain in
`runs/content-control-train-r1-20261023*`:1.554477821 CPU seconds and37,616,283
units including300 real decoder updates. The explicit plain-clone repair and
scheduler attribution fix were committed/frozen before the replacement build,
with data/objectives/caps/candidate counts unchanged. No score-based retry occurred.
The replacement source freeze is `fbaac5b926`, committed receipt at
`d986d4c64b`; its train command exited0. This exit means execution/budget success,
not that the new scientific hypothesis passed.

A preliminary git-add command used paths relative to the wrong cwd and failed.
Its unexecuted freeze is retained as `frozen-uncommitted-attempt.json`; it is
not the authoritative source freeze. The formatter's initial uv invocation
could not write outside the workspace; temporary uv tools/cache were moved
under `/tmp`, and `just fmt` completed with no applicable formatting group.
No permission escalation, auto-review denial, permission change or credential
creation occurred.

Instrumented additional development CPU was: historical TRAIN diagnosis
.308614404; failed construction1.554477821; successful combined build23.479634726;
descriptive analysis .739706073; saved-evidence audit .389470153. Their subtotal
is26.471903177 seconds. It excludes uninstrumented source authoring, repository
fetch/format setup, test-process startup and final administrative archival;
it is not an equal cumulative research-cost claim. Failures are not budget
credits. Both builds' identical3,022,821-byte input tensors have SHA256
`4675ef4516e35aad449d68f9e2e7393ae8a1ad2399383fab45d93e8c3f341580` and share
one Git blob. All new retained outputs total about24.1 MB before the report.

## Reviewable commands and artifacts

From `qualification/joint-generation`, actual commands included:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m content_control.diagnose runs/content-control-train-diag-20261023
python3 -m content_control.run freeze --out content_control/frozen-train-v2.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m content_control.run train --out runs/content-control-train-r2-20261023 --freeze content_control/frozen-train-v2.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python3 -m content_control.analyze runs/content-control-train-r2-20261023
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. python3 runs/content-control-train-r2-20261023/audit_saved.py
```

Do not repeat these experimental commands to seek a different result. Original
argv, source commit, stdout/stderr and exit are saved beside each build.
All5 initial refiner tests plus10 existing learning tests passed; after the
plain-clone repair the6 affected refiner tests passed, including finite
differences for H/A across all five paths and an accounting-wrapper regression.
`just fmt` and `git diff --check` completed; no Rust code changed.

The [source/protocol freeze](frozen-train-v2.json),
[budget/candidate/source receipts](../runs/content-control-train-r2-20261023/build.json),
[TRAIN outputs](../runs/content-control-train-r2-20261023/train-result.json),
[analysis](../runs/content-control-train-r2-20261023/analysis.json),
[evidence audit](../runs/content-control-train-r2-20261023/evidence-audit.json) and
[unit log](../runs/content-control-unit-v2-20261023.txt) are reviewable. All45
gradient/update NPZs and every model remain in their candidate subdirectories.
The audit verifies first Adam parameter deltas from actual gradients (error
<1e-12), all six final content-array movements, frozen decoders and all loss
counts. For15 selected external hand inputs it independently opens real PNGs,
checks hash/base64, classifies decoded pixels against templates and parses the
caption; all15 were red-square-right as requested. One hand input is a smoke
test, not generalization evidence. Inference files do not export optimizer state
or claim resumable training.

The [confirmation draft](PROTOCOL.md) and [complete retained-report index](HISTORY_AND_CONFIRMATION.md) remain nonexecutable.
No further model/policy tuning or independent confirmation is recommended for
this failed refiner. Any later confirmation needs the parent's review of the
complete history index, new physical provenance, once-only opening authority
and a valid forward error budget. There is no runtime/access blocker.

A later [parent-reported exact-reference note](MATHEMATICAL_REFERENCE_NOTE.md)
records positive/zero/negative mathematical controls and the distinction between
two refinement units and complete control cost. Those toy numbers were not
rerun here or used as project benefit evidence; the frozen experiment is unchanged.

The later [group-wide budget clarification and next TRAIN proposal](BUDGET_REVIEW_AND_NEXT_TRAIN_PROPOSAL.md)
points directly to all nine candidates' complete accounts and proposes one
fixed dense block-update design. That proposal has not been implemented or run.
