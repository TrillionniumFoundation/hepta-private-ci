# Historical risk-selection diagnostic: no candidate supports the nominal target

All 200 prespecified raw-confidence candidates failed the nominal 5% conditional-error upper-bound criterion. All twenty heads therefore select reject-all. This is an insufficient-evidence result, not proof that every candidate's true risk exceeds 5%, and not a safety certification.

The smallest multiplicity-adjusted calibration upper bound among the frozen family was 6.9351%, above the fixed 5% target. Very high thresholds do not rescue the evidence: at 0.90 only 37–65 calibration sources are accepted per head; at 0.95 only 0–2. Even zero errors require at least 162 accepted sources for this 200-candidate, delta=.05, alpha=.05 procedure. A 1% target would require at least 826, more than the entire calibration split.

## Frozen historical evaluation

- Selected: 20/20 reject-all; coverage zero; wrong/all zero; conditional error undefined (null) for all 20 heads. Rejecting everything is not a useful classifier and does not estimate conditional accuracy.
- Fixed raw0.70: mean coverage 61.5703125%; mean wrong/all 2.1171875%; mean of twenty defined per-head conditional errors 3.4373755%.
- Selected minus fixed-raw0.70 coverage: -61.5703125 percentage points; descriptive paired-source bootstrap95 interval [-65.0080078,-58.1328125] pp.
- Selected minus fixed-raw0.70 wrong/all: -2.1171875 pp; interval [-3.25,-1.1560547] pp. This reduction is entirely due to rejecting everything, not better discrimination.

The contrast intervals preserve correlations across all twenty heads for each of 640 source units. They condition on existing heads and calibration rules, do not include training/calibration variability, and are descriptive historical summaries, not discovery or safety claims. Per-head ordinary CP95 evaluation bounds are distinct from the family-adjusted calibration criterion; no pooled-head binomial interval is used.

## Meaning

The current historical evidence cannot support nonzero coverage under this frozen nominal criterion. Point estimates below a target do not establish a finite-sample upper bound after choosing among many thresholds. A failed upper-bound test does not establish the opposite risk claim. No threshold grid, risk tolerance, confidence level or head was changed to obtain a pass.

This is a mechanism/sample-size diagnostic on an already-exposed historical pool, including previously examined cal640/eval640. The theory would require fixed scoring functions and appropriately independent, identically distributed source units. Those assumptions and prospective applicability are not established here. The current procedure deliberately uses raw frozen heads, because the previously fitted temperatures used these same calibration labels; ordinary fixed-score bounds would not account for that additional adaptation.

The original 1600 holdout was not opened. No encoder calls, new fits, downloads, or remote CI checks occurred. Runtime was 1.1212 seconds with peak RSS 117404 KiB, one BLAS thread. The original budget experiment's joint-negative result and calibration experiment's negative individual-temperature comparison remain unchanged.

## Reproduction boundaries

protocol.json and PROPOSAL.md were frozen before current threshold counts; selection-freeze.json includes all 200 counts/upper bounds and twenty chosen rules before current evaluation. run.py is the actual executed original source; it requires the sibling local research directories and their immutable features, labels, heads and split. It is not a portable public-data training pipeline. Raw text, labels, weights, features and raw logits must not be included in a publication package.

Source method: Geifman and El-Yaniv, NeurIPS 2017, Lemma 3.1 (binomial-tail inversion) and the authors' official risk-control implementation. Our finite numerical threshold family and all-head Bonferroni accounting are explicitly prespecified adaptations, not a claim of bitwise replication of the paper's adaptive search.
https://papers.nips.cc/paper_files/paper/2017/file/4a8423d5e91fda00bb7e46540e2b0cf1-Paper.pdf
https://github.com/geifmany/selective_deep_learning/blob/master/risk_control.py

Independent review reconstructed all 200 candidate counts from the original train tensor and frozen heads, inverted binomial tails using a separate log-PMF sum, checked boundary/162/826 cases, and recomputed evaluation and paired bootstrap. Maximum CP discrepancy was 2.7617e-15. Independent verification is included as evidence; its source retains local sibling-directory dependencies and is not a portable published-package replay. Run replay.py with numpy2.2.6/scipy1.18.1 for published-count/contrast arithmetic only, not proof of model inference.
