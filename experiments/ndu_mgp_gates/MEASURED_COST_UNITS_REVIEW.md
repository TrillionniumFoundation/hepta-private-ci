# P1 measured-resource cost unit admission — source-only fix

**DRAFT / RESEARCH_ONLY / DENY_ALL / HOLD_NO_GO**

This minimal additive child of #3319 addresses one separate admission defect: `protocol.cost_units` previously accepted *any nonempty string*, so estimated MACs, token budgets and arbitrary synthetic proxy counts could be mislabeled as measured resource cost and pass all six comparator cost-ratio and paired bootstrap gates. A correct statistical ratio of two proxy costs is not proof of equal actual compute or energy.

## Correction

- Require a known **unit identity**: `measured_cpu_seconds`, `measured_wall_seconds`, or `measured_device_joules`. Reject `estimated_MAC`, `proxy_token_units`, `budget_units`, `FLOPs`, empty and null.
- Echo the exact cost unit in the advisory receipt. Never assume two cohorts measuring different physical units are directly comparable.
- Test all rejected proxies and accepted names, while asserting the result still stays `HOLD_NO_GO / DENY_ALL` and cannot prove independent scientific efficacy.
- Preserve #3319's stronger **paired bootstrap upper cost-ratio** and inherited strict calibration/protected-world gates. Do **not** rewrite frozen #3055 or the existing negative heldout #3039 / original-image #3213 results.

## Scope / non-claims

This is only schema admission, **not independent measurement authentication**. A liar can still place fabricated CPU-second values in the input. A physical meter and externally signed source/runner receipts are required for production. These units are mutually exclusive; this contract remains a *single-dimensional* ratio and does not by itself guarantee CPU, GPU, wall, energy and memory fairness simultaneously. A full P1 registered study must additionally account for per-request hard budgets, simultaneous multi-resource caps, completion/failure denominator, cross-modal raw readback, source-grouped future windows and strong learned-controller baselines. Parallel #3257, #3270, #3332 have additional compatible controls; do not assume this isolated child supersedes them.

This patch changes only two research Python files, plus this note. Existing `paired-observed-shadow` exact-head tests and full blocking CI are still required; prior donor green is not transferrable. P0→P4 scientific and target-host gates remain unclosed.
