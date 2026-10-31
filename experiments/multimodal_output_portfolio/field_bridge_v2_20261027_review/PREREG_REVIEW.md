# V2 development gates and independent review

This review preserves the completed V1 experiment at commit `e8ce0f538857f8bd869e275aa7fd258aa7989113`. It defines evidence needed before a new primary experiment, without editing V1 sources, rows, acceptance rules or conclusions. The machine-readable [blocker ledger](BLOCKERS.json) separates implementation checks from empirical benefit and theorem-level claims.

## Sequence and access boundary

1. A bounded development pilot identifies an actuator and panel on which actual decoded hard outputs can respond. It records all candidates, complete optimizer state, effective parameter movement and no-update controls. The parent protocol fixes the sensitivity and ordinary-learning pilot rules.
2. Freeze a fitting design, representation, predictors, action set, value panel and all thresholds. Use eight fitting trajectories for each of the three original models. Counterfactual branches may be evaluated on this declared development data, with complete parameter **and momentum** restoration and a common future minibatch/noise schedule.
3. Hash the exact fitting records and frozen predictor artifacts before collecting eight separate audit trajectories for each model. At each audit boundary predict every action's value before executing/scoring its independent branch. The supplied controller hashes must match the pre-audit freeze.
4. Apply the development audit rules below. A failed audit remains visible. If its outcomes influence a later model revision, that audit becomes development information and cannot certify the revised model; a new untouched trajectory audit is required.
5. Only a frozen candidate passing the development gates may proceed to a new primary six-arm comparison, plus attribution controls and independent retention. New test and retention outcomes cannot select the candidate, runtime readout or thresholds.

The development gates test empirical identification and decision skill. They do not establish reduced-state sufficiency, Markov closure, the paper's FBSDE assumptions or production readiness.

## Independent trajectory auditor

`gate_audit.py` consumes one record per complete optimizer snapshot. A record contains original `seed`, `trajectory`, `step`, `partition`, hashes for the full model state, optimizer state and future schedule, `current_value`, and four `action_values` in the fixed protocol order. Audit records also contain absolute next-value `predictions` for `field`, `generic` and `richer`, and the corresponding frozen controller hashes.

The auditor does not fit a model, select hyperparameters, run a generator or load a primary test/retention file. It checks that the no-update branch equals the current fixed-panel value to 1e-12, the complete trajectory grid, disjoint fit/audit trajectory identities, finite arrays and identity consistency. The fitting-data digest excludes predictions and sorts fitting records by seed, trajectory and step. Exact required freeze keys are:

```json
{
  "decision_steps": [0, 12, 24],
  "fit_rows_sha256": "SHA256_OF_CANONICAL_FITTING_RECORDS",
  "controller_sha256": {
    "17": {"field": "SHA256", "generic": "SHA256", "richer": "SHA256"},
    "29": {"field": "SHA256", "generic": "SHA256", "richer": "SHA256"},
    "43": {"field": "SHA256", "generic": "SHA256", "richer": "SHA256"}
  }
}
```

The illustrative `decision_steps` above must be replaced with the complete grid fixed by the actual registered block/trajectory design. The auditor rejects omissions even if the same boundary is absent in every trajectory.

Use the exported `fitting_rows_digest(records)` to calculate the exact canonical record identity. A matching file hash establishes internal consistency; the chronological claim also requires separately committed source, freeze and execution receipts.

### Audit response gate

For **every** original model seed, the mean within-snapshot four-action hard-value spread must be at least **0.001**, and at least **25%** of snapshots must have spread at least **0.001**. The maximal spread is reported but cannot alone pass this gate. This prevents one isolated threshold crossing from being mistaken for generally identifiable action effects.

### Predictive skill gate

Predict the next absolute value, or equivalently its difference from the snapshot's current value. Compare field MSE on every available audit action with three predetermined baselines:

- No change: predict the current value for every action.
- Global fitting mean delta: add the mean fitting delta across all actions and snapshots.
- Action-specific fitting mean delta: add the fitting mean delta for that action.

No baseline fits audit labels. The gate compares with the **best observed MSE among these already-fixed baseline predictions**, which is a conservative diagnostic and does not deploy a baseline selected on audit labels.

The equal-model-weight pooled field MSE must be at most **0.9** times the best baseline MSE. Each original model's field MSE must also be no worse than its best baseline. Generic and richer predictors receive identical scoring and remain visible; beating weak constants alone cannot establish feature uniqueness.

### Decision skill gate

Choose the fixed-action comparator from the mean action deltas in the fitting data only. For an audit snapshot, the empirical branch oracle is the maximum actual action value; it is used only to calculate development regret and is unavailable to a deployed policy.

The field policy must satisfy all of:

- Equal-model-weight average regret at most **80%** of the fitting-selected fixed-action regret.
- Mean actual value improvement over that fixed action at least **0.001**.
- Lower endpoint of the paired **95%** trajectory-bootstrap improvement interval strictly above zero.

The bootstrap resamples the eight complete audit trajectories **within each fixed model seed**, with equal weight for the three models, 4,000 replicates and seed 271028. It does not treat sequential boundaries or four action branches as independent experiments. These development intervals are descriptive screening intervals, not a new-model-population or primary-test claim. Per-model improvements and all candidate/constant errors are reported even when the combined gate fails.

### Behavioral validation

Ten auditor tests check a truly useful predictor, a constant predictor with superficially small errors, a flat response, a drifting no-update branch, fit/audit trajectory contamination, fitting-outcome tampering, changed predictor identity, an incomplete trajectory, a boundary omitted from every trajectory and duplicate-row sample inflation. They verify gate behavior and integrity, not scientific effectiveness.

```bash
python -m experiments.multimodal_output_portfolio.field_bridge_v2_20261027_review.gate_audit_tests

python -m experiments.multimodal_output_portfolio.field_bridge_v2_20261027_review.gate_audit \
  --bank /path/to/complete-development-bank.json \
  --freeze /path/to/pre-audit-freeze.json \
  --out /path/to/new-independent-audit.json
```

## New source identities and sample size

The old `load_corpus` ordering is train 10,000, validation 2,000, evaluator 10,000, retention 1,000, and official-test 2,000 unique pixel identities. Keeping train, validation, evaluator sizes and split seed fixed while extending **only** retention and test retains the old prefixes. Source-pair offsets are in pairs, not image counts.

A new primary test beginning at pair offset 1,000 therefore uses test images beyond the original 2,000-image prefix; a new retention set beginning at pair offset 500 uses retention images beyond its original 1,000-image prefix. The executed [source-allocation check](SOURCE_ALLOCATION.json) verifies all five unchanged prefixes and zero intersections with the entire 25,000-image original registry. The expanded corpus contains 29,000 unique images; both reserved panels contain 512 pairs / 1,024 images, and their mutual intersection is zero. The complete identity manifest is preserved separately with SHA-256 `c574b21f216deabe1dc3f90ab9d57276c9e54aea75dcc781d317435ebcdeb1ef`. No model or observer was loaded and no new-role outputs were scored by that allocation helper. This identifies freshness relative to the recorded historical pool, not global data secrecy, unseen writers or unknown pretraining corpora.

V1 pair-averaged contrast standard deviations ranged from approximately 0.012 to 0.025. A normal-approximation planning calculation with six-contrast Bonferroni correction and 80% power suggests that detecting an absolute effect of 0.005 would require about 76–306 independent source pairs, depending on contrast and observer. Detecting 0.003 could require about 848 pairs for the noisiest comparison. These are planning approximations from the prior study, not guarantees or observed effects for V2. A 512-pair primary panel supports the 0.005 scale more credibly than the prior 128-pair panel, but it does not repair model-seed uncertainty or manufacture a positive effect.

## Conditions for later acceptance

The six user-specified arms remain identifiable through B−A, C−B, D−A, E−C, E−G and E−F, retaining the ordinary/native attribution arm G. Both independent scoring roles, registered multiplicity correction, per-model directions and final retention must be retained. A successful response/prediction gate only permits this evaluation; it does not pre-approve its outcome.

Native optimization must preserve actual original `sparse_tick` state transitions and all authority constraints. A faster bridge can close an overhead implementation issue after parity and benchmark evidence; it cannot establish native-state value over a same-information history controller. The latter still requires E−F on a frozen, new evaluation.

## Native engineering check already executed

[Independent arithmetic](NATIVE_INDEPENDENT_ARITHMETIC.json) reconstructs all 120 randomized benchmark blocks (24 repeated five-path blocks) and 16 fresh-process records. Original native feature/action hashes match across the four transport paths; all timing summaries and paired ratios reproduce exactly. The full-record FFI improvement supports closing the transport-overhead implementation issue only. Model generation and final output delivery were outside this timing boundary, and a history-only path remains substantially cheaper. See the native implementation report for exact parity coverage and authority invariants.
