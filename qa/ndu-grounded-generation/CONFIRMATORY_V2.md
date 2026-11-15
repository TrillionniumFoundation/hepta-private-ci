# NDU v2: pre-registered, source-paired confirmatory statistics

**Status: research harness only, no new model experiment or promotion.** This
module is stacked on the existing v2 [source firewall and negative-v1 capability
audit](V2_GATES.md). It does not alter the frozen v1 outcomes or protocols.

`confirmatory_v2.py` accepts a previously SHA256-anchored registration, the
candidate cohort manifest, *every* historical exclusion manifest, and a new
independently scored same-source/same-seed episode journal. It **recomputes**
the v2 cohort collision firewall from the manifests, rather than trusting a
self-reported PASS flag. The SHA of the candidate manifest must match the
registration. The new **test** source IDs must match the original-source
manifest exactly; train, dev and calibration images are not test units.

## Minimum admissible design

- At least **128 new test original images** and **three distinct decoding
  seeds**, with complete images × seeds × methods blocks.
- Exactly **12 paired arms**: `base`, `static_cells`, `learned_router`,
  `best_of_n`, `mean_only`, `risk_actor_critic`, `ndu`, `ablate_covariance`,
  and four one-Cell-at-a-time deletions (`semantic`, `horizontal`, `vertical`,
  `completion`). This minimum is **4,608 episodes** (128 × 3 × 12).
- Every *completed* NDU episode must document **8–16 actual executed**
  checkpoints; configured capacity is not an execution count. Incomplete and
  over-budget outcomes remain in the denominator with zero quality, severe=1,
  and their entire measured wall time retained.
- Every episode reports eight nonnegative exclusive wall-time components
  (`encoder`, `backbone`, `cell`, `controller`, `critic`, `verifier`, `render`,
  `communication`), with their sum no greater than measured wall seconds.
  This is an accounting consistency check, not independent hardware metering.
- Development-selected nonzero risk weight is required for the covariance
  contrast. The tool **does not independently revalidate** its dev selection
  receipt; provide that separately before accepting any causal claim.
- A pre-specified 0.05 familywise test, `CVaR_0.9`, at least 2,000 seeded
  original-image-cluster bootstrap draws, holding all seeds for each sampled
  image together. Each of **15 fixed contrasts** gets a Bonferroni-corrected
  two-sided percentile interval; no per-episode IID bootstrap.

The 15 contrasts comprise five metrics for NDU versus each of `best_of_n` and
`mean_only` (quality, loss CVaR, severe fraction, actual wall-time ratio,
coverage), one NDU versus no-covariance CVaR contrast, and four leave-one-Cell
quality contrasts. A PASS needs the registered directional margins to hold
**simultaneously**; these requirements are deliberately conservative and are
**not** a proof of causal mechanisms or a pre-study power calculation.

## Registration and journal contract

The registration is a JSON object with schema
`hepta.ndu-confirmatory-registration.v2`, exact ordered `methods`, `seeds`
(array), `test_sources` (integer), `cohort_manifest_sha256` (64 lowercase hex),
`selected_dev_risk_weight` (nonzero number), `alpha: 0.05`,
`cvar_alpha: 0.9`, `bootstrap_samples` (>=2000), `bootstrap_seed` (integer), and
seven numeric `margins`: `quality_gain`, `cvar_delta`, `severe_delta`,
`wall_ratio`, `coverage_delta`, `covariance_cvar_gain`, `cell_quality_gain`.

The post-score JSONL journal has *exactly* these fields per record:
`source_id`, `seed`, `method`, `quality`, `coverage`, `severe`, `wall_seconds`,
`control_checkpoints`, and `cost_parts` (the eight component names above).
Values of `coverage` and `severe` must be integer 0 or 1. `quality` is bounded
[0,1]; `wall_seconds` is **positive actual work**, not clipped to a nominal
budget. Each sample is verified against the registered roster. `quality`
must already have been computed by an independent, withheld-reference scorer;
this harness cannot establish that fact from numeric rows alone.

**Register first.** Write the new manifest and registration, hash both, publish
or otherwise anchor the complete registration digest *before evaluating the
new held-out cohort*, and freeze the scoring protocol and model. The program
can compare the supplied SHA256, but it cannot verify when/where that hash was
published, or whether the test data were seen during model development.

```bash
python qa/ndu-grounded-generation/confirmatory_v2.py \
  --registration /frozen/v2-registration.json \
  --registered-sha256 "$PRETEST_ANCHORED_REGISTRATION_SHA256" \
  --cohort-manifest /frozen/v2/cohort/manifest.json \
  --historical /frozen/v1/cohort/manifest.json \
  --historical qa/ndu-grounded-generation/historical_exclusions.json \
  --episodes /new/v2/heldout-independent-scores.jsonl \
  --output /new/v2/confirmatory-statistics.json
```

Exit **0** means that internally consistent, submitted scores meet *these
particular* preregistered statistical thresholds. Exit **2** means the data
are invalid/incomplete or the statistical thresholds are not met. In **both**
cases `model_promotion_authorized` is `false`.

Run the synthetic regression suite separately:

```bash
python -m unittest discover -s qa/ndu-grounded-generation \
  -p 'test_confirmatory_v2.py' -v
```

The positive synthetic test is *only* a consistency fixture. It does not add
new training data, model outputs, genuine experiment trials, or CI evidence.

## Scientific boundaries still OPEN

The evaluator deliberately does not verify independent learned natural
language or novel pixel generation, the correctness of the withheld-reference
scorer, genuine independent Cell proposal rollouts, the empirical training
of a terminal covariance estimator, the identity or provenance of model
weights, the timestamp of registration, true comparable FLOPs or energy,
or continuous FBSDE/Merton optimality. Those need independent execution,
provenance attestations, source custody and appropriate causal/experimental
tests. A statistical gate alone must never authorize runtime tools, topology
mutations, release deployment, or model promotion.
