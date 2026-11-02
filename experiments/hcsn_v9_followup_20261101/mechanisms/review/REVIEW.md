# Independent mechanism review

The raw auditor passes **114,577 checks** over 24 worlds, 2,040 runs and 8,160 mandatory outputs. It independently reconstructs service successes/failures from the shared world uniforms, every observed-state update, request/arrival chronology, failed and successful READ charges, prediction classes, event-count mass, content propagation by explicit transition sums, and paired fixed-D schedules. Across the main execution there are 5,019 READ requests: 3,057 successful and 1,962 failed. All failures are still charged. The original campaign is never imported by this auditor.

The separate exact-arithmetic audit reconstructs rewards as `correct_count/4 - READ_count/25` before averaging over fits within each world. It uses integer world-block resampling and exact quantile interpolation. This avoids mistaking a floating-point residual near zero for a positive acceptance bound.

| Condition | Same-risk D−B | Exact-arithmetic descriptive 95% world-block interval |
| --- | --- | --- |
| Matched | +0.02083333 | [0, +0.04166667] |
| Hidden refractory mismatch | −0.02833333 | [−0.09227778, +0.0485] |

The lower bound in the original floating summary was `1.85e-17` in the matched case. Exact reward arithmetic gives **zero**, so it is not evidence of a strictly positive lower bound. These are 12 independent worlds per condition, not 2,040 independent repetitions or independent fit-world observations.

The original-model service-risk forecast changes actions in 31/36 matched and 36/36 mismatched world-fit pairs. Risk-aware minus risk-omitted net reward is −0.02527778 [−0.14394444, +0.07916667] in matched worlds and +0.04833333 [−0.0625, +0.15916667] in mismatch worlds. Both descriptive intervals include zero. Risk is used, but net superiority is not established.

The separately frozen risk replay produces 72 additional original-model records under exactly the risk-aware D action schedules while omitting the risk forecast. The independent exact auditor checks **362 conditions**, including raw hashes, record inventory, unique identities, prediction arrays, access records, actions, and rational rewards. All 72 match exactly. This verifies that the declared risk intervention acts through control; it does not establish that risk-aware control is better.

Fixed-D shape replays show content changes: mean-two-point changes predicted classes in 16 matched and 8 mismatched output comparisons; single-transition changes classes in 17 and 4, respectively. The separately refitted shape-minus-full closed-loop reward intervals all include zero. The mean-two-point fixed-D effect in matched worlds is −0.07638889 [−0.14583333, −0.00694444], but the mismatch effect includes zero. This bounded diagnostic does not establish complete-mechanism task necessity.

The refit review is in `FITS_REVIEW.md`. Simplified count laws assign exactly zero mass to some real sampled counts, with the fixed `1e-12` loss floor retaining finite NLL. Their count-likelihood weakness survives single-parameter refitting. All 189 grid losses and 9 validation losses agree with a separate inverse-Gaussian distribution implementation.

Training budgets and structural priors differ between the historical ordinary GRU/SSM models and the newly calibrated analytic models. The fitted drift changes core count forecasts, while shared planner simulations retain the original common estimated physical law. This is a finite model-family refit and controller diagnostic, not a unified analytic-neural retraining or strict matched-training-information architecture qualification. Physical service outcomes are synthetic Bernoulli outcomes under a declared law; this is not an external network-service or financial Put-risk experiment.

Formal enclosing audit CPU receipts are 2.022015 s for the fit audit, 1.579508 s for the raw/statistical audit, and 0.919899 s for the exact reward/fixed-risk audit. These are separate audit workers, not candidate inference costs. The first unmetered development fit audit and review-writing work have unknown additional cost, so their sum is a lower bound rather than complete project economics.
