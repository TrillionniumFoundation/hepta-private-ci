# Historical risk-selection mechanism proposal (not yet executed)

## Falsifiable question and scope
Can a finite-sample-aware, calibration-only selector find any useful raw-confidence rejection threshold for each of the 20 frozen heads, or does multiplicity/sample size force abstention? Compare selected rules with the already specified raw confidence >= 0.70 rule. This is a historical internal diagnostic, NOT a new safety qualification or a prospective guarantee. All 2560 source rows and both current 640 splits have been exposed in previous work. No claim that choosing this research question was independent of historical outcomes.

## Fixed inputs and isolation
Use exactly the #3684 twenty frozen 640-example heads and its disjoint fit1280/cal640/eval640 index sets; retain all heads and seeds. No new model or optimizer, no head selection, no temperature fitting. Recompute only raw logits from the original training tensor and frozen weights, or load only the existing raw calibration logits member. Do not open the original 1600-row holdout member or its labels.

Previously fitted shared/individual temperatures used cal640 labels. Reusing those learned probabilities with an ordinary fixed-score binomial bound on that same cal640 would omit score-function adaptivity. Exclude those arms rather than silently misstate a guarantee. A future calibrated-score version would need separately held-out score fitting or a separately justified uniform method; no such extra method is part of this proposal.

## One fixed rule family
- Risk: conditional error P(wrong | accepted), not erroneous admissions / all inputs.
- Target alpha = 0.05; family failure probability delta = 0.05.
- Each head has exactly ten numerical thresholds [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90,0.95], chosen now without examining new threshold outcomes.
- Acceptance is max softmax(raw logits) >= threshold. Stable float64 computation; no calibrated scores, quantiles or interpolated thresholds.
- For every head/threshold, count n accepted cal sources and k wrong accepted. One-sided exact upper bound U = beta.ppf(1 - 0.05/200, k+1, n-k), with U=1 when n=0 or k=n. Independently validate by binomial-CDF inversion. A rule passes only if n>0 and U<=0.05.
- Bonferroni covers all 20 * 10 = 200 candidates. Head and nested-threshold dependence does not invalidate the union bound. Never pool 20 heads as 12800 independent calibration points.
- For each head choose the passing threshold with largest cal accepted count; tie choose the smallest numerical threshold. If none passes, choose explicit reject-all with null conditional risk, not an inferred zero-risk classifier. Save all 200 counts/bounds and the 20 chosen rules in a hashed freeze BEFORE evaluating any selected rule.
- No relaxed alpha, fewer tests, alternate grid, additional candidate family or more permissive tie-break after observing results. Do not invoke monotonic error versus threshold: conditional risk need not be monotone.

## Evaluation and uncertainty
Evaluate only the chosen rule and fixed raw0.70 comparator for each head on current historical eval640. Report each head's accepted, errors, coverage, wrong/all, wrong/accepted (null at zero), and ordinary one-sided exact 95% upper conditional-error bound as descriptive evaluation uncertainty, not simultaneous certification. The cal-side multiplicity-adjusted upper bound is separate and not copied as an eval estimate.

Report aggregate mean coverage and mean wrong/all, number of reject-all heads, and number of defined conditional-error estimates. Do not give a pooled-head binomial interval or select the most favorable head. For two descriptive paired contrasts (selected minus raw0.70 coverage and wrong/all), use 10000 paired source resamples, PCG64 seed 2026102600, preserving all 20 heads within each source. These conditional source-bootstrap intervals omit training/calibration sampling and adaptive historical research selection; do not call them population safety guarantees or use them for joint discovery.

## Feasibility before reading scores
With zero observed accepted errors, U=1-(delta/M)^(1/n). At alpha=5%, delta=.05 and M=200, at least 162 accepted calibration sources are necessary; positive error counts require more. With alpha=1%, at least 826 are necessary, exceeding all 640 cal sources, so that stronger target cannot pass even the best possible zero-error outcome under this family. These are necessary best-case counts, not power estimates; outcome/coverage still unknown. Choosing a single fixed head would reduce multiplicity but answering a different question post hoc is forbidden.

## Evidence basis and limitations
Geifman and El-Yaniv (NeurIPS 2017), Lemma 3.1, inverts a binomial tail to bound selective error and uses multiplicity correction when examining several rules. We use an explicitly finite, fixed numerical grid rather than reproduce its adaptive threshold binary search.
https://papers.nips.cc/paper_files/paper/2017/file/4a8423d5e91fda00bb7e46540e2b0cf1-Paper.pdf
Official authors' implementation (read only, not executed):
https://github.com/geifmany/selective_deep_learning/blob/master/risk_control.py

The mathematical interpretation needs a frozen predictor/rule family and independent identically distributed calibration source units from a stable target population. Component deduplication is not proof of event independence; deterministic historically reused AG News splits and prior exposure do not establish prospective applicability. Consequently report only whether the algorithm's nominal criterion passes in this historical diagnostic. A passing count does NOT certify deployed safety. A reject-all or insufficient-evidence outcome is valid and must not trigger a search for more flattering settings.

Resource estimate: existing local numpy/scipy, no installation/download, zero model encoding/retraining, <=512 MiB RSS, one BLAS thread, <60 seconds expected. Publication, if authorized after independent review, contains protocol, source-only drivers, hashed receipts and aggregate/per-head counts, not news, labels, raw logits, weights or features. No remote CI checks.
