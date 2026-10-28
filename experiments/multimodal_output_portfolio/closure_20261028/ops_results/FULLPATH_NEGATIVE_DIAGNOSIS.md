# Sealed full-path negative-result diagnosis

**The matched-mean capability gate remains failed.** The negative contrast comes almost entirely from seed 17's same-stage actual-output comparison. Retention filtering and the fixed deployment tariff do not explain it.

## Exact selected-model decomposition

| Seed | Risk selection | Mean selection | Risk CE | Mean CE | Risk − mean | Contribution to total signed gap |
|---|---|---|---:|---:|---:|---:|
| 17 | encoder | encoder | 0.800977500569 | 0.817589430945 | -0.016611930376 | 99.834477% |
| 29 | prior_greedy | prior_greedy | 0.850042672064 | 0.850042672064 | +0.000000000000 | -0.000000% |
| 43 | prior_greedy | adapter | 0.811665391498 | 0.811692933714 | -0.000027542216 | 0.165523% |

The preregistered average is **-0.005546490864**, below the unchanged admission threshold of 0. It is the arithmetic mean of three within-seed CE contrasts, not a pooled-seed CE or three independent datasets.

Seed 17 selects the encoder checkpoint in both arms, and both satisfy retention. Risk retention CE is 0.907735182569 versus mean 0.887349460720, while its quality CE is lower by 0.016611930376. Under gamma 2, the empirical negative-exponential moment ratio is exp(−2 × difference) = **1.033781936542**. This proves a worse empirical moment for this comparison; it does not identify a particular tail quantile or failure type.

## What the selector and cost checks establish

Recomputing the unconstrained quality-CE maximum over every saved candidate gives exactly the same selected stage for all six seed × arm combinations. Some intermediate candidates fail retention, but none is the unconstrained winner. Consequently, relaxing retention would change neither the chosen models nor the failed matched-mean gate.

Seed 29 has lower-quality learned candidates and both selectors retain the same greedy prior. For seed 43 all risk checkpoints already pass retention; its best learned checkpoint still falls below its prior. That fallback accounts for only 0.165523% of the total signed selected gap. The mean arm's adapter beats that prior by just 0.000027542216 on these development observations.

The unchanged actual cost constructor assigns **0.00134 utility units per bundle** to every candidate: two encoders, one gate, two transitions, one image emission, seven token emissions, two writes, two reads and one observer call. With constant c, CE(U − c) = CE(U) − c. It cancels exactly from relative CE; differences in separately recorded physical CPU cannot cause this objective's gap. This conclusion applies only to the declared work tariff and supplies no physical CPU or failure-tail certificate.

## Same-stage evidence

| Seed | Transition ΔCE | Adapter ΔCE | Emission ΔCE | Encoder ΔCE |
|---|---:|---:|---:|---:|
| 17 | -0.000000466 | +0.001821380 | -0.011385615 | -0.016611930 |
| 29 | -0.000001014 | +0.000915392 | +0.007641834 | +0.030452371 |
| 43 | +0.000001242 | -0.002987648 | +0.001172865 | +0.013648146 |

Seed 17's disadvantage appears after opening emission parameters and grows in the encoder stage. The other two seeds have positive late-stage risk-minus-mean differences, yet their learned risk candidates still do not exceed the prior. These are descriptive stage observations; they do not establish which optimizer mechanism caused them.

## What remains unidentified and open

CE alone cannot separate mean output utility from the entropic risk premium, identify which corruption condition or loss component changed, or estimate a rare-failure probability. The exact identity is ΔCE = ΔE[R] − Δ(E[R] − CE); the missing means and event-level distributions are not recoverable from one CE number. Archived evaluation rows could support that descriptive decomposition, with original-source pairing and selection limitations retained. No archived rows or media were downloaded for this diagnosis.

Nonzero gradients through all opened modules and an exact gradient oracle establish implementation properties. They do not establish gradient signal-to-noise, convergence, a gain over mean training, broad learned-model retention or population optimality. Development-selected scores also cannot substitute for independent qualification.

The remaining capability task is an actual training/optimization improvement that satisfies the unchanged matched-mean and retention requirements under a newly frozen protocol. Dropping the mean comparator, selecting a convenient seed or relaxing a threshold would not establish that capability. **All 384 reserved qualification sources still have zero model predictions.** No new training, generation, scoring or qualification was performed for this diagnosis.

## Reproduction and custody

Run the accompanying `fullpath_negative_diagnosis.py` with `--repo REPOSITORY --output-dir REVIEW_DIRECTORY`. It uses only the standard library, checks all 66 frozen publication-file hashes, reads the named compact summaries, and evaluates only the sealed cost constructor with inert dictionary fixtures. The JSON sidecar contains exact input SHA-256 values, formulas, full candidate checks and numerical comparisons. The original reports, profile, gates and 66-file publication manifest remain unchanged.
