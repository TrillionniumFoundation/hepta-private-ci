# Fixed D-only temperature calibration

## Completed result

All **21 selected models** now have their original-rule D temperature fitted and independently checked. The single native job `1a1f3c89f0f-ffbe-e2d` finished with exit 0, complete durable output and a confirmed terminal receipt. Every solution is interior, every long-double final-bracket sign check is strictly satisfied, and every event retains its original argmax. Calibration decreased D NLL for all 21 models. D remains the development set used for model and temperature selection; these results are not confirmation-E scores.

| Family | Mean raw D NLL, three seeds | Mean calibrated D NLL, three seeds |
|---|---:|---:|
| GRU | 0.952863405814 | 0.918674704779 |
| CfC | 1.177879344459 | 1.157678641261 |
| PLIF | 1.909886874100 | 1.693413904518 |
| Event-time LIF | 1.230211799214 | 1.196745410142 |
| S4D | 1.332453731606 | 1.298978278153 |
| Attention | 1.072262180062 | 1.069139091274 |
| HCSN | 1.101994439951 | 1.079613489821 |

The fixed roster generated exactly 21 scalar optimizations, **1,064** objective/gradient/Hessian evaluations, **980** bisection updates and **126** independent long-double evaluations. The largest float64-versus-long-double discrepancy across the checked quantities is **1.4210854715202004e-14**, within the predeclared 1e-10 implementation-consistency threshold. No neural model forward, backward, optimizer construction, restore or update ran. No E payload or label was accessed.

HCSN temperatures for seeds 101 / 211 / 307 are **0.9589969639163112 / 0.7097894492128152 / 1.2391356744310171**. All 21 exact values, input/model bindings, final brackets, objective evaluations and independent arithmetic results are retained in the original individual receipts.

The supervisor measured the complete numerical child, including startup, imports, input and runtime verification, all fits, independent arithmetic and output finalization: **33.64987031597411 s wall / 32.927284 s CPU / 231,584 KiB peak RSS**. Stage time through archive and transport-part creation was **33.85831926204264 s**, below the existing 600-second stage limit. No numerical retry, kill, memory breach or budget overrun occurred. Controller/MCP latency, subsequent downloads, publication and unmeasured outer service startup remain outside these scientific timers.

The immutable source was published before dispatch at commit `a81f9e13cab9d27b0a59248e68dc11f32c61b652`, tree `0e68b16b22e2040e5245b81f514d7ece107b0849`, byte-identical to the already prepared local tree. Original prepared sources and requests were reused without modification. The 274,640-byte archive has SHA256 `c0bd19d9ff00dcafb7da8700d54c3febf8d48af3fe5d1ccc34c96446028560ca`; all **43** member sizes and hashes match. The complete temperature manifest has SHA256 `033c394cfc63833e090a7a08dfe942911da2ecc44ff18e426082f404b08372b4`.

`audit_archive.py` independently reconciled the downloaded archive, frozen sources, runtime, 21 selected-model receipts, all saved bisection chains, journal counts, original stopping criteria, terminal cost and durable native result. Its read-only body used 0.07005816700257128 s wall / 0.06795188899999999 s CPU and 17,644 KiB peak RSS. This archive audit does not refit temperatures or regenerate D logits; the numerical cross-check is the separately implemented long-double reference executed in the native stage.

Two MCP start/reconciliation calls timed out before returning the native identity. The same exact request and idempotency key subsequently recovered the **same successful job**, with `reused=true` and `retried_launch=false`. The original timeouts, failed registry inventory and early absent-file observations remain in `evidence/dispatch/MCP_OBSERVATIONS.json`; the confirmed native result is in `RECOVERED_JOB.json`. Create-only materialization and immutable receipts prevented overwriting or duplicate calibration. The final direct status/read calls confirm complete, untruncated durable output and empty stderr.

**Closed:** all 21 original-rule D temperature receipts and their bound complete manifest. **Still open:** the original controller terminal outcome, independent original six-fit training replay, E feature/label custody, all 21 frozen E predictions and original E admission. A fresh status query still reports that the original controller supervisor disappeared without a confirmed terminal receipt; its result remains UNKNOWN. The six-fit full replay count remains 0/6 and scientific admission remains HOLD.

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

The source-freeze commit precedes the sole native dispatch. Final results are appended as evidence without changing the dispatched source. The pre-execution README is preserved byte for byte in the native archive; the completed result above was added only after recovering the full original outputs.
