# Exploratory Belief repair and exact finite-box certificates

This is a **separate exploratory follow-up** to the frozen continuation-head study. Its protocol was written before new test outputs, with an immutable new seed and no new candidate or hyperparameter search after evaluation. It does not modify the original study's protocol, results or success gates. This is not an externally registered experiment.

The study uses only the already-public joint-model sources in `TrillionniumFoundation/hepta-private-ci` at commit `5b69a046d886cf4c2a73c50e58197360ea15d8f5`. No newly private HeptaTrader data are included. It has two outcomes:

1. Existing fit71 numerical infeasibility witnesses are now exact proofs for explicitly serialized IEEE coefficient systems and their declared closed box.
2. A minimum-L1 Belief edit corrects all six identified terminal sign contradictions on TRAIN, while preserving 451 already-correct terminal decisions. **It does not establish a useful task-value improvement. Every Belief-only candidate fails the original validation acceptance threshold.**

## Predeclared targeted intervention

`PROTOCOL_BEFORE_RESULTS.json`, SHA256 `7e01e54d0824f0ef7a4fa7bb119cba99986a96b8b77c454a27a2dbb0d238c8a6`, declares:

- Same five original fits: 11,23,37,53,71.
- One LP per fit, minimizing the L1 change in the 49 Belief coefficients.
- All original TRAIN states with a unique oracle-best SUBMIT0 or SUBMIT1 choice are constrained, including already-correct signs. Oracle ties within `1e-10` are excluded.
- Signed logit margin `1e-4`.
- Hard budget `||delta||1 <= .5*||original Belief row||2`. This is a conservative subset of that L2 ball. No infeasibility relaxation is allowed.
- Representation, CTMC transitions and continuation parameters stay fixed, apart from reusing the old already-frozen continuation candidate in the factorial arms.
- One signed permutation of the proposed Belief delta is the random control. It preserves the exact requested absolute-value multiset and hence L1/L2 norms. Actual F64 parameter realization differs by at most `1.04e-17` in the measured norms. There is no random search.
- Original validation mean-utility gain of at least `.005` accepts each candidate; otherwise its gated arm reverts to the original base. Raw arms are retained separately. The gate compares each candidate with the original base, not with its component intervention.
- New seed **870140000**, 32 IID and 32 OOD public worlds per fit: 320 fresh worlds. No fresh test outputs participate in selection.

Original TRAIN and validation data are reused. The follow-up is motivated by the prior diagnosis, so neither its design nor the validation data are independent of the earlier research. Its fresh public test schedules are independently generated using the new fixed seed. The task is exact expected utility under the original finite declared law and TRAIN-fitted decoder confusion; no new FullHX packets are decoded, and no trading returns are measured.

## Actual parameter and mechanism results

All five LPs were feasible. Only the Belief bias, feature index48 of the 49-vector, changed:

| Fit | Unique oracle-terminal TRAIN states | Wrong before → after | Requested bias change | L1 budget |
| --- | ---: | ---: | ---: | ---: |
| 11 | 92 | 0 → 0 | 0 | .60043298 |
| 23 | 69 | 1 → 0 | +.000599608925 | .55492827 |
| 37 | 77 | 4 → 0 | −.066502722591 | .54396405 |
| 53 | 119 | 1 → 0 | +.018557187760 | .60365617 |
| 71 | 100 | 0 → 0 | 0 | .65406606 |

All 457 terminal constraints pass. The 451 already-correct signs remain correct. Maximum numerical constraint violation is `1.1018204577883939e-17`; every realized L1 edit was checked against the stated radius using exact `Fraction` arithmetic. A linear program over49 coefficients happened to return only bias shifts; this is not evidence of discovering a general hidden circuit.

The original mathematical obstruction is resolved locally: changing Belief can alter terminal-to-terminal rankings that the continuation coefficients cannot alter. This does not imply that all training policy actions, all posterior probabilities or full task value have been repaired. Mean TRAIN Belief Brier changes slightly from `.00026824758` to `.00026879845`; enforcing selected sign decisions is not the same objective as calibrating all probabilities.

## Fresh test results: raw 2×2 and control

C is the previously selected continuation edit; B is the new TRAIN-only Belief edit.

| Raw policy | IID mean utility | IID change from base | OOD mean utility | OOD change from base |
| --- | ---: | ---: | ---: | ---: |
| Base | .2324801536 | 0 | .1367879503 | 0 |
| C only | .2477224666 | +.0152423130 | .1494547395 | +.0126667892 |
| B only | .2322933594 | −.0001867941 | .1333546504 | −.0034332999 |
| C+B | .2471603563 | +.0146802027 | .1465451308 | +.0097571805 |
| One norm-matched random B | .2324803417 | +.0000001881 | .1322657826 | −.0045221677 |

Five-fit descriptive paired 95% intervals:

| Contrast | IID mean and interval | OOD mean and interval |
| --- | --- | --- |
| B − base | −.0001867941; [−.0007085116, +.0003349233] | −.0034332999; [−.0153555699, +.0084889700] |
| (C+B) − C | −.0005621103; [−.0016752528, +.0005510323] | −.0029096086; [−.0166720440, +.0108528267] |
| B − random B | −.0001869822; [−.0007092220, +.0003352575] | +.0010888677; [−.0008210348, +.0029987703] |
| Raw factorial interaction | −.0003753162; [−.0010324156, +.0002817833] | +.0005236913; [−.0020803824, +.0031277650] |

All these intervals include zero. Only three fits require a nonzero B intervention, and only two produce different B-only fresh-world utility values. The full five-fit population is retained, including no-op interventions; the sample was not narrowed to favorable fits.

For B-only, fit37 contributes IID −.00093842/OOD −.02042334, while fit53 contributes IID +.000004449/OOD +.00325684. The other three fits have zero B-only utility change. Mean fresh-state Brier worsens from `.0005820610` to `.0006142919` IID and from `.0040290926` to `.0042108319` OOD. These observations do not establish that correcting the six signs improves general calibration or task value.

### Validation and gated results

B-only validation gains are `0, 0, −.00041552384, 0, 0`. Both B-only and random-B are rejected in all five fits. Their gated outputs are exactly the base parameters, so their gated IID/OOD utilities are `.2324801536/.1367879503` and their gains are zero.

C and C+B pass the base-relative validation threshold in all five fits. Their gated results therefore equal their raw results. This does **not** establish benefit from adding B: the average (C+B)−C change is negative in both domains. The old C improvement can carry a harmful component through a gate that only compares the combined candidate with the original base. The raw factorial contrasts make that distinction visible; the gate has not been changed after seeing these results.

### Later incumbent-comparison diagnostic (not a new policy result)

After the frozen test was complete, the existing validation numbers were inspected relative to C, the current incumbent for a proposed B addition:

| Fit | Existing validation (C+B)−C | Would a fixed +.005 gate against C accept? |
| --- | ---: | --- |
| 11 | 0 | No |
| 23 | 0 | No |
| 37 | −.000890717411 | No |
| 53 | +.000014500000 | No |
| 71 | 0 | No |

This later diagnostic creates no candidates, does not change the frozen base-relative gate, and is not used to claim a newly validated holdout policy. It shows why a future composition protocol should compare incremental value with the actual incumbent and bind source checkpoint identity to that incumbent. A combined candidate can pass against an older base even if its added component has no incremental qualification. Full records are in `records/INCUMBENT_VALIDATION_DIAGNOSTIC.json`.

The new C-only IID interval happens to exclude zero on this sample, but its OOD interval includes zero and the original frozen study's intervals remain unchanged. This exploratory second test seed is not used to rewrite the earlier study's success status or claim training superiority.

## Exact fit71 certificate

The existing stored sparse witnesses are used without refitting or renormalizing them. Missing weights are exactly zero. Let `r=A_box^T y` and `c=b_box^T y`. For any potential solution with `||delta||infinity <= rho`, feasibility would imply

`c + rho*||r||1 >= 0`.

The exact finite-IEEE calculations instead give these **upward-rounded upper bounds**:

| Original margin | `c + rho*||r||1`, upper bound |
| --- | ---: |
| 0 | **−.0005149002502248292241130588** |
| .001 | **−.001487468919277903441097118** |

Every coefficient, sparse weight and radius is interpreted as its exact binary rational. `Fraction.from_float` products are independently crosschecked with aligned integer arithmetic. The stationarity residual need not be exactly zero because it is explicitly bounded. Each certificate has 147 unknowns, 1,479 inequalities and 99 positive weights.

The original archive did not separately store A,b. The hash-pinned original constructor was rerun on the pinned original geometry; those resulting IEEE matrices are now frozen in `exact_certificate/fit71_ieee_box_evidence.npz`. The proof is exact for those serialized coefficients and the binary64 box radius. It makes no claim about an unrounded Euclidean radius, changed Belief, continuous laws, unrestricted heads, holdout returns or a global NDU optimum. See the certificate subdirectory for complete rational numerators/denominators and standalone verification.

## Compute and numerical accounting

The five LP calls used `.031984736` CPU seconds in total; complete local proposal construction took `.070686887` seconds. The full raw/gated validation and fresh test process used **31.622371 CPU seconds**, **31.728065 wall seconds**. Costs for the prior original training, prior continuation search, source acquisition and this exploratory diagnosis remain separate; they are not silently made free.

Inference and metrics used the strict explicit-reference path inherited from the original study. **933,777 matrix products** were compared, maximum difference `8.881784197001252e-16`, no nonfinite values, and stderr was empty. Strict overflow/invalid/divide exceptions were enabled. Different arms share feature caches and identical policies reuse exact evaluation results; per-arm timings are not a fair inference performance comparison.

No new full-model training, energy measurement, GPU comparison or equality-of-search claim is made. Reversion here means selection of the exact base parameter array for a rejected offline candidate, verified by array equality; no live checkpoint was written, and no filesystem rollback is claimed.

## Reproduce and inspect

Place this directory under the original study as `exploratory_belief/`, or keep it separate and pass explicit paths. The original study folder and its manifest remain unchanged.

```sh
python verify_followup.py --study-root /absolute/path/to/original-study
python exact_certificate/exact_box_certificate.py verify
```

To regenerate the proposals in a new file:

```sh
python solve_belief_lp.py --study-root /absolute/path/to/original-study --output /absolute/path/to/new-proposals.json
```

The evaluator intentionally reads the frozen packaged `BELIEF_PROPOSALS.json`; compare regenerated proposals numerically and inspect environment metadata before substituting any new proposal in a new study. Recover the original source models/data using the original study's `acquire_inputs.py`, then restore the exact prior continuation candidates from the small published head excerpts:

```sh
python prepare_frozen_continuation.py \
  --study-root /absolute/path/to/original-study \
  --inputs /absolute/path/to/original-inputs \
  --output /absolute/path/to/new-frozen-old-results
python evaluate_followup.py \
  --study-root /absolute/path/to/original-study \
  --inputs /absolute/path/to/original-inputs \
  --old-results /absolute/path/to/new-frozen-old-results \
  --output /absolute/path/to/new-followup-results
```

`OLD_CONTINUATION_HEADS.json.gz` records the five old 4×49 last layers, derived from the already-public original model family. The restoration helper combines them with the original source checkpoints, verifies all candidate hashes, and preserves the old recorded result bytes as source evidence. It performs no optimization or evaluation. Fresh timing measurements belong in fresh results and are not substituted into that source identity. This restoration was actually checked against all five recorded candidate SHA256 values.

Outputs must be new. `EXECUTION_MANIFEST_BEFORE_TEST` binds source/proposal hashes, and the per-fit `BEFORE_TEST_RECEIPTS` preserve validation decisions before fresh-world evaluation. Protocol timestamps were checked against the clock tool; `CLOCK_SCOPE_NOTE.json` corrects a prior scratch status message's local-time label without changing frozen protocol bytes.

`FOLLOWUP_MANIFEST.json` enumerates the publishable files. `records/ACCEPTANCE.json` records training-mechanism qualification separately from the failed utility/superiority qualification. The complete raw/gated numbers, per-world utility vectors and all contrasts remain in `records/results.json.gz`.
