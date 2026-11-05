# Post-hoc fixed-world diagnosis

This diagnostic follows an already failed and independently replayed scientific result. It does not qualify a model or supply new holdout evidence. Root approved one bounded read-only pass over all 16 fit 23 OOD validation worlds and 32 fit 23 OOD TEST worlds, with no new seed, sample, weight, gate or retry.

The diagnostic source and input identities were frozen before its execution in `PROTOCOL_FROZEN.json`, SHA256 `e5b50784baa48bee8e598ae99ef77216a5f8dc055eaf5718484bec44a81bfce6`. The source SHA256 is `819d6e2eb812baba5f0f66670bbcec71f4f2071a3b2366d07b4c282347e575db`. The worker had a 60 CPU-second / 120 wall-second limit and completed in 3.130104 child CPU seconds / 3.270629 wall seconds, peak RSS 30,871,552 bytes. The separate freeze used 0.165077 child CPU seconds.

## What is checked

For the checkpoint's own law and the fixed evaluator law separately, `PolicyValue` computes the frozen C and E policies' future incremental utility. Each state's fee is charged once as `after.charges - state.charges`. The diagnostic verifies the performance-difference identity using the unnormalized E reach at every visited state:

\[
V_E(s_0)-V_C(s_0)=\sum_s d_E(s)A_C(s,\pi_E(s)).
\]

It separately traverses the common C/E prefix, stops at each first action difference, and sums prefix reach times the complete edited-policy suffix difference. A local one-step change followed by C is recorded as a separate counterfactual and is never treated as the entire E policy.

At each changed-action state, the source records both head score vectors, both law-specific one-step Q vectors, the anchored teacher, full suffix values, original state, hidden features and all 49 linear margin contributions. The contribution formula is the change in the margin coefficient times the fixed hidden coordinate. It is not an independent intervention on that coefficient, and learned hidden coordinates are not assigned unverified semantic roles.

The changed-state records are a union of states reached under the two laws and common-prefix traversal. Some union states may have zero evaluator reach. Global contributions use evaluator E reach; raw state counts are not probabilities or independent samples.

## Complete population results

| Split | Worlds | Own-law E minus C | Evaluator E minus C |
| --- | ---: | ---: | ---: |
| Existing OOD validation | 16 | +0.0434261663 | +0.0389743957 |
| Existing OOD TEST | 32 | -0.0139610269 | -0.0124189593 |

In TEST, changed states where E violates the checkpoint's own one-step C policy-improvement target contribute -0.0463161318 to evaluator utility. The other category contributes +0.0338971724, totaling -0.0124189593. Across all 43 changed-state records in the 48-world diagnostic (16 validation records and 27 TEST records), there is no detected case, at the frozen 1e-12 sign tolerance, of positive own one-step C advantage reversing to negative evaluator advantage. This is limited to these states and this counterfactual; it does not prove an absence of model-law errors elsewhere.

The maximum discrepancy from stored scientific utilities is 0. Global identity residuals are at most 1.11e-16 and linear-head margin residuals at most 2.43e-16, within the separately frozen 2e-13 F64 tolerance. These are numerical executed checks, not outward-error optimization certificates.

The separate scalar record audit in `../review/POSTHOC_RECORD_AUDIT.json` independently checks every world/state sum, stored-weight/hidden contribution and illustration rule. Its maximum linear-accounting residual is 2.57e-16. It reuses stored hidden vectors without a new model or teacher execution and does not supply additional confirmation.

## Illustration rule

The illustration rule was frozen before the diagnostic: select the smallest-index TEST world attaining the minimum already-frozen E-minus-C utility across all 32 existing TEST worlds. This selects `test_006.json.gz`, loss -0.4217498820.

Its first different action occurs at tick 5, with budget 3, no pending observation and no previous read. C's READ score 0.2336972805 exceeds WAIT 0.2199535594; E instead scores WAIT 0.2477313258 above READ 0.2441127457. Own-law one-step values favor READ 0.5586208473 over WAIT 0.0870621138; evaluator values also favor READ 0.5681082476 over WAIT 0.1463583656. The head reverses the action despite both value calculations favoring the final reading opportunity. Complete 49-coordinate contributions and all 48 worlds remain available; the worst example is not selected as a new model or a representative population estimate.

## Replay

Run from the parent `value_edit` directory. Reuse the existing diagnostic protocol; do not call the freezer again to alter identities.

```bash
python measure_process.py --output posthoc_replay --wall-limit 150 -- \
  python posthoc/diagnose.py --protocol posthoc/PROTOCOL_FROZEN.json --output posthoc_replay/run
```

Every output is create-only. The complete result is `execution_r1/run/RESULTS.json`; all 48 per-world files are bound by its inventory. No result-driven repair or new candidate search was performed.
