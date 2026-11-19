# Fixed D-only temperature calibration

## Frozen scope

This namespace prepares the original confirmation-E candidate's 21 D temperature parameters using the immutable roster in Draft #6757, head `2c170f64ec1788f45b1b5fe5d6caadbd2bdf507e`. It does not admit or launch E. The original controller remains UNKNOWN, independent original C2 full training replay remains 0/6, and scientific admission remains HOLD.

The existing formal protocol says to fit temperature on D after model selection and prohibits test access during tuning, debugging, calibration design and early stopping. The 2026-11-10 E candidate explicitly requires 21 independently verified D temperature results before any E read and lists the complete D-calibration manifest among work before its separate decision. The current remaining-blockers request and root's explicit D-only instruction allocate this one separate 600-second stage. The old candidate's `execution_authorized=false`, unallocated E7200 proposal and all original training budgets remain unchanged. Exact source documents and the prior ledger are preserved as `ORIGINAL_FORMAL_PROTOCOL.json`, `ORIGINAL_E_PLAN.json` and `INPUT_LEDGER.json`.

All seven families retain the common LR .003 chosen from the original D three-seed means. The 21 checkpoint/configuration/source identities come from the fixed ledger; calibration opens only the 21 identified saved D-logit files. It constructs no model, calls no neural forward/backward and constructs/restores/steps no neural optimizer. Scalar temperature optimization is real parameter fitting and is counted separately, including every attempted evaluation, bisection update and independent arithmetic evaluation. Synthetic preparation work has its own counters and receipt.

## Original numerical rule

For inverse temperature beta in [.01,100], minimize unweighted mean D multiclass NLL with stable per-event maximum-logit centering. T=1/beta. The gradient is the mean softmax-weighted logit minus the true-class logit, and the Hessian is the mean softmax-weighted logit variance.

Only if every row has exactly equal values across all 11 classes, use the flat exception beta=1. Otherwise take the lower endpoint when its derivative is nonnegative, or the upper endpoint when its derivative is nonpositive. For an interior optimum, bisect derivative signs at most 100 times and stop when bracket width is at most 1e-12 times max(1,abs(midpoint)), or no representable strict interior point exists. Choose the final midpoint. There are no changed bounds, restarts, alternative models/seeds or post-E recalibrations. Raw and calibrated argmax must agree on every event.

These solver details were newly specified by the original 2026-11-10 candidate; they are not represented as retrospective preregistration of the earlier formal study.

## Independent arithmetic and controls

`solver.py` uses float64 whole-array centered arithmetic. `reference.py` separately uses blockwise long-double scaled-logit centering and true-class logit differences. It checks NLL, gradient and Hessian at raw temperature, both endpoints and the selected solution, plus the final bracket, bisection structure, endpoint KKT conditions and every argmax. Intermediate recorded gradients are not all independently recomputed.

The newly declared implementation-consistency tolerance is 1e-10 times max(1,abs(reference)), with 1e-10 slack for numerical KKT/bracket signs and raw-versus-calibrated NLL. It is frozen before D calibration, does not change the original 1e-12 bracket stopping rule, and is not called a rigorous error bound. Strict long-double KKT/bracket signs are also reported separately. Long double is not an outward-rounded enclosure.

Fourteen analytic/synthetic controls passed before the production D stage. They cover flat and both endpoint solutions, the known interior beta=log(40) solution, per-row additive shifts, nonfinite/empty/wrong-class logits, invalid label types/ranges, and altered final beta, bisection move or NLL. The control receipt counts 11 attempted synthetic scalar optimizations (including invalid-input cases), 107 objective/derivative/Hessian evaluations, 90 bisection updates and 33 independent reference evaluations. No production D logits or E payload were used in those fixtures.

## Bounded execution and accounting

One persistent native key, one worker, one numerical thread, 600 seconds for the D-only phase, 30 seconds of internal finalization reserve, 2 GiB RSS/cgroup memory and 8 GiB address space. Current hardware observations are evidence of availability, not a reservation. The child verifies runtime identity, frozen program/selection bytes and each entire D artifact before fitting; named runtime files are hashed before the first fit and afterward. The selected old model source and old compiled runtime are not reconstructed or executed.

The supervisor measures the complete child wall/CPU/RSS using `wait4`, including child startup, imports, verification, fits, independent checks and child output finalization. Per-fit and reference timers are nested inside that child cost. Native service startup, controller transport and publication remain separately scoped or unmeasured. The stage includes supervisor archive and transport-file creation. Every failed attempt and partial journal is preserved, with zero automatic retries. The first failure stops the fixed-roster stage; completed prefixes never stand in for all 21 outcomes.

`TEMPERATURE_MANIFEST.json` will bind all completed parameter receipts, source freeze, fixed input ledger, event counts and costs. Its E execution authority always remains false. Even a complete calibration manifest does not resolve the original controller, independent full-training replay, numerical/causal qualification, isolated E payload custody, 21 E predictions or the original separate E admission decision.

The source-freeze commit precedes the sole native dispatch. Final results are appended as evidence without changing the dispatched source. This prepared README makes no claim that the 21 production calibrations have already run.
