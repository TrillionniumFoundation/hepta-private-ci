# Exact logical zero-age propagation

This change removes two unnecessary matrix exponentials from the complete-state
kernel. At an exactly equal rational release clock, `alpha @ exp(0 * G)` is
`alpha`; the derivative through `G` is zero. Returning the original `alpha`
retains its gradient and avoids constructing the identity action and its
backward graph. Positive ages still execute their full exponential. The kernel
keeps the same deterministic delay, event-time reset snapshot and complete
pending-state representation.

The parent is the completed network result commit
`298fae004356f4adb5b58f2bc4d61fdde5bdab75` from Draft #6754. The old PenDigits
protocol, selections, results and 831 original files are unchanged. This study
does not read the dataset or execute an optimizer.

## Numerical equivalence and work

The frozen four-case synthetic comparison completed eight fresh CPU children,
with the same actual saved weights and inputs in each pair. A separate reader
checks the entire child roster, terminal results, raw hashes, finite arrays,
complete state/schedule, logits and input/parameter gradients before calculating
the table. All **260 tensor comparisons and 186,036 coordinates** were exactly
equal in the saved numerical values; maximum absolute difference was **0**.

Each timing is the median of three complete forward/backward repetitions after
one warm-up. The separate complete-state probe is retained and charged. These
are one-model/one-input performance observations on a shared CPU, not a training
or accuracy comparison. The saved-AD column sums hook payloads with repeats; it
is not peak live memory. Full-process RSS is recorded per child.

| Case | Actual forward exponentials, old → new | Saved AD payload bytes, old → new | Retained state bytes | Wall median ratio, old/new |
| --- | ---: | ---: | ---: | ---: |
| Batch 1, 10 steps | 52 → 40 | 651,225 → 631,065 | 20,384 | 1.124 |
| Batch 1, 40 steps | 232 → 160 | 20,271,225 → 18,773,625 | 193,984 | 0.789 |
| Batch 1, 80 steps | 472 → 320 | 141,889,465 → 129,486,265 | 705,984 | 1.343 |
| Batch 64, 10 steps | 52 → 40 | 17,367,897 → 17,025,177 | 521,360 | 0.993 |

The reduction in executed exponentials and saved AD payload is directly
observed. The 40-step case became slower, and the batch-64 case was essentially
unchanged. These data do not establish a uniform speedup. The complete retained
state has the same size, including its history growth. All repetitions and
outliers remain in `benchmark-attempt002` and `REVIEW.json`.

## Validation and retained strict numerical failure

The focused final suite passed **28 tests**: complete-state DDE/gamma references,
first derivatives, event-time reset snapshots after parameter updates, network
content/causality, cold full-state continuation, actual task-boundary gradients,
Erlang comparisons and scalar second derivatives. The new zero-age tests also
check that an actual one-exponential budget suffices at zero age while a
positive-age release still needs two actual actions.

A separate stricter scalar probe remains a **negative result**. With rate 1.7,
delay 0.2, zero upper escape/rewards/discount and horizon **0.61**, both the
original and optimized Torch kernels have a maximum absolute error of about
**6.68765e-12** against the independent gamma-renewal expression. The proposed
`atol=3e-13, rtol=3e-12` check fails. At horizons 0.63 and 1.07 the observed value
error is about 1e-16. The initial strict source and entire failing 28-test log
are retained as `initial_strict_probe.py` and `initial-suite-attempt001.log`.
The 0.63 Hessian test supplements that retained 0.61 failure. The failure is
not repaired by zero-age elimination, is not excluded from the final numerical
record, and does not acquire a global numerical pass from the equivalence test.

## All attempts and cost

`benchmark-attempt001` contains eight terminal import failures before model
construction: direct script execution did not put the repository root on the
child import path. Its original runner, plan, stderr and costs are preserved.
The runner was corrected, then a distinct plan was frozen before attempt002.
No training or dataset evaluation was repeated.

| Attempt | Successful children | Controller elapsed seconds | Sum of child wall seconds | Sum of child CPU seconds |
| --- | ---: | ---: | ---: | ---: |
| 001, import failure | 0/8 | 22.064949 | 22.039338 | 21.561576 |
| 002, complete comparison | 8/8 | 57.783466 | 57.766248 | 55.850797 |

Attempt002 plan SHA256 is
`b80b513851731cd7d31147daca4ac18089ce31eb1c17ee01a01fb97df5e86748`.
The plan fixes one logical CPU, one numeric thread, a 4-GiB address-space bound,
120-second child timeout, all cases/seeds and tolerances. Physical-core
exclusivity and power were not measured. The first candidate child took longer
than its peer including setup; its full costs remain visible.

`review.py` rechecks the saved outputs without constructing a model, taking a
gradient or executing an optimizer. To reproduce measurements elsewhere, make
a new plan with the current absolute source paths and the same checked hashes;
keep the old plans and outputs immutable and write to a new absent directory.

This closes a redundant-work defect while preserving complete operator
semantics. The shared 0.61 numerical failure, growing exact state, original
N256 bitwise negative result, C2 full replay and genuine task benefit remain
separate qualification questions.
