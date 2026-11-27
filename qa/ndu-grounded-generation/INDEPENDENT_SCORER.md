# Independent v1 observable-grounding audit (supplemental; 2026-10-23 UTC)

This post-hoc second implementation audits the completed COCO grounded-generation pilot in PR #3213. It is **not** a newly trained or sampled model and must not alter the frozen v1 protocol, 768 records, outcomes, or dev-selected risk weight.

The evidence archive is hepta-ndu-evidence-v1-20261022.zip (103,482,273 bytes; SHA256 2ac7d46df01fb3e24cd1004cef75ad0efd4076b5f1c9556b560e97546ffaceb5). The original archive passes independent file integrity and portable replay (831 verified files, 768 episodes).

## Second implementation

After extracting the original evidence archive, run:

    python qa/ndu-grounded-generation/independent_v1_audit.py --bundle-root /absolute/path/hepta-ndu-evidence-v1-20261022 --output /absolute/path/new-audit.json
    python -m unittest discover -s qa/ndu-grounded-generation -p 'test_independent_v1_audit.py' -v

The supplemental scorer does not import the original evaluator, policy or generator. It computes maximum-cardinality reference-box matching with subset-mask dynamic programming rather than augmenting paths; independently validates PNG SHA256 and dimensions, output count/side/label/text consistency, complete measured costs, wall budget, severe flags, and original 64-source by 12-arm aggregate scores and CVaR. The alternate metric described below is post-hoc and not preregistered.

Verified locally: **768/768 individual episode records agree**, **12/12 method aggregates agree**, 273 unique PNG digests accounted for, and **11 portable mutation/positive-control tests passed**. This is a second scoring implementation, not proof of independent image recognition or generated pixels.

## Structural-score confounding

All **768/768** output descriptions match the deterministic count/side template; all 768 output labels match the requested input category. Thus the registered v1 quality includes up to 0.2 points of structurally granted label/text credit. This credit is not proof of independently learned language generation.

For **exploration only**: grounding-only = (0.5*boxF1 + 0.2*count_correct + 0.1*largest_side_correct)/0.8 on valid episodes, else zero. Do not retroactively substitute this into the original frozen v1 experiment.

| Method | Original quality | Post-hoc grounding-only |
| --- | ---: | ---: |
| best_of_n | 0.869010 | 0.836263 |
| mean_only | 0.859115 | 0.823893 |
| ndu | 0.833594 | 0.799805 |
| ablate_missing_modality | 0.452604 | 0.319661 |
| ablate_shuffled_pair | 0.403646 | 0.258464 |

The original negative NDU finding stands. Independent learned text/pixels, 8–16 actual decisions, terminal covariance benefit, per-Cell attribution, cost/coverage matching, a new heldout cohort, multi-seed confirmation and continuous FBSDE are **NOT CLOSED**. CI successes cannot replace missing scientific outcomes.
