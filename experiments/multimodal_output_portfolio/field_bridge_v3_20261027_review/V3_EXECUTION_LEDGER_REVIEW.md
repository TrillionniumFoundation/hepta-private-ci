# V3 terminal execution-accounting review

**Accounting PASS. The registered execution is terminal with negative qualification outcomes.** The immutable index covers exactly 21 completed scientific jobs, 42 jobs skipped because their bound qualification field is false, and 18 actual independent verification receipts. The ledger verified 1,181 bound files. There are no unresolved registered stages, no scientific execution retries and no unknown failed-work attempts. This is execution/accounting closure; it does not establish any scientific efficacy claim.

## Scientific work, charged once

| Phase | Completed jobs | Scheduled gradient microsteps | Linear/head fits | Native ticks | Recorded cumulative worker wall seconds |
|---|---:|---:|---:|---:|---:|
| training:reference | 3 | 3,456 | 0 | 0 | 157.633703 |
| training:bank | 3 | 51,840 | 0 | 0 | 2,854.349643 |
| training:fit | 3 | 0 | 180 | 0 | Unmeasured |
| training:development | 3 | 27,648 | 0 | 0 | 1,766.971323 |
| runtime:bank | 3 | 0 | 0 | 0 | 822.505798 |
| runtime:fit | 3 | 0 | 432 | 774,144 | 101.311367 |
| runtime:audit | 3 | 0 | 0 | 54,330 | 478.580743 |

The scientific training total is **82,944 scheduled microsteps / 7,962,624 gradient examples**, plus **648 measured objective directions / 62,208 examples** and **1,944 response/clean probe reverse calls / 829,440 proxy examples**. These are separate counters; the probe work is not hidden inside the scheduled-step total.

All **23,040 discarded microsteps** from 480 rejected guard blocks remain charged. The scheduled budget also retains zero-action gradient computation. There were 70,848 attempted optimizer advances; neither this number nor accepted-state changes replace the scheduled compute denominator.

There are **612 scientific linear/head fits**: 180 training-controller solves and 432 runtime stage heads. Runtime fitting and selected execution used **828,474 native ticks** altogether. Runtime counterfactual banks generated 195,840 terminal targets; selected execution generated 80,870 deliveries. Parent/child completion copies and per-branch records were not added again.

Observer work in training is **27,840 actual CNN batch calls / 3,563,520 digit examples**. Runtime bank plus selected execution adds **752,124 digit examples**, each evaluated with the frozen one-example observer batching rule. Together these are **4,315,644 scientific digit classifications**; batch-call counts must preserve the different batch sizes.

## Additional independent verification

The 18 receipts are six reference/bank metadata audits, three training-fit audits, the single prespecified full-tail replay, and eight runtime/development/metadata verification reports. They are charged separately from the scientific jobs they recheck.

| Verification work | Actual additional amount |
|---|---:|
| Prespecified replay gradient microsteps / examples | 1,200 / 115,200 |
| Replay objective-direction measurement / examples | 1 / 96 |
| Replay response/clean probe reverse calls / proxy examples | 3 / 1,280 |
| Independent training least-squares solves | 180 |
| Independent runtime ridge-head reconstructions | 432 |
| Runtime fitting native replay ticks | 774,144 |
| Selected-session native replay ticks | 54,330 |
| All actual observer CNN batch calls | 368,032 |
| All actual observer digit examples | 773,416 |

The hard-score verifier's actual work is 3,040 observer batch calls / 389,120 digit examples. Its logical coverage is 7,920 batch calls / 1,013,760 digit examples, with 2,440 exact ordered-batch cache hits. Only actual calls/examples enter the cost totals. Runtime media verification adds 364,840 single-digit forwards. The prespecified training replay adds 152 observer batch calls / 19,456 digit examples.

Metadata/statistics reports and the existing development audit join add zero generator/observer calls. The join has no measured duration. Its input-auditor source and receipt identities are bound without asserting that a new verifier or a standalone join producer ran.

## Timing and scope limits

Scientific recorded component wall durations sum to **6,181.352578 seconds**; verification recorded wall durations sum to **663.038097 seconds**. These are cumulative worker durations, not end-to-end elapsed time. Processes ran concurrently; inner native/selection timers overlap parent durations. Three scientific training-fit wall timers, training/replay/metadata CPU timers and the metadata join's wall/CPU timers are absent and remain unmeasured. A zero recorded CPU subtotal where all component CPU timers are null is an empty subtotal, not a claim of zero CPU work. No common operational start/finish receipt exists, so `operational_elapsed` is null.

The accounting scope excludes synthetic implementation contracts, source-allocation preflight contracts, dependency/environment restoration and native compilation, whose separate receipts remain preserved. No resource count was estimated. The accounting-only schema preflight and its approved alias/timer compatibility fix are preserved; terminal aggregation then passed on its first execution. No scientific source, frozen phase inventory or original scientific/verification receipt changed.

All skipped learning audit/final and non-frozen runtime jobs bind `TRAINING_QUALIFICATION.passed=false`; the six frozen primary/retention confirmation jobs bind `CONFIRMATION_QUALIFICATION.passed=false`. No reserved confirmation output was generated. Native authority remains **DENY_ALL** with no owner integration.

## Immutable identities

- `V3_EXECUTION_INDEX.json`: `8e673464820552f2969251bba8f561cd8f13cbed356ef5da0459201f9bd29253`.
- `V3_EXECUTION_LEDGER.json`: `88975c19e09e3c82254e1c41fa0a71c17bd1bb0cf7dc9a231a9b4da7d5d34722`.
- Published ledger helper commit: `19d51b8218816f62c13b28f66e22430e4b5ee20a`; source SHA256 `d76ef7c6c98d4bf50098e2c5163c6ddee46a1b116cf9996232219fb329b186eb`.
- Preserved schema preflight: `d583ecbd49bc8f2aad8cd6077b75c2c2fee769baa12266eabf5d168054a430d4`.
- Compatibility contract: `1b223fb69383c5dfab9df624066757f9f65e50ec10f881bf045c2d149481bf4c`.

All detailed counters, per-attempt statuses, skipped-decision field bindings, producer hashes and verified input hashes remain in the full ledger/index.
