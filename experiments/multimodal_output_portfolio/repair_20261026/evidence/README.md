# Joint target and unique-event evidence repair

This separately scoped implementation leaves every previous experiment and
result intact. It implements full-joint learning and connects the unique-event
filter to a real control calculation; it has not requalified a trained model.

## Interfaces

- `prior.JointPrior.fit(features, targets, groups, steps=..., learning_rate=...,
  seed=..., excluded_groups=...)` trains one NumPy neural network with 100 joint
  logits. `predict(features)` returns `[N,100]`, ordered `left*10+right`.
  Both paired encoder feature vectors should be supplied in each row. No
  target labels enter prediction. `export/load` preserve the new versioned
  schema; the old marginal-head native ABI cannot silently load it.
- `joint.PairObservation(sample_id, source_group, target, event_ids, values)`
  contains fitting-only paired outcomes. `JointObservationLaw.fit_paired`
  weights source groups equally, preserves the observed joint coupling and
  counts repeated physical evidence only once. `alpha` is an explicit
  smoothing assumption on supported cells. Targets without measured pairs
  remain unknown, including when alpha is positive.
- `JointObservationLaw.from_components(single_digit, distinct_joint=None)`
  repairs identical-event support with one single-event factor. A dictionary
  of directly specified 100-outcome couplings is required for distinct targets.
  Missing couplings remain unknown; a positive prior on any unknown column
  rejects planning rather than silently assuming independent errors.
- `law.forecast(prior)` integrates the as-yet-unobserved alias identity into
  110 possible events. Each supported event supplies `event`, `aliases`,
  `values`, `probability` and a 100-entry joint `posterior`. This connects to
  `control.execution.attach_observations` with explicit cost/owner branches.
- `law.start_filter(prior)` reuses the existing unique-event filter.
  Only actual arrival receipts may update it. Duplicate receipts are
  idempotent; contradictory arrivals fail atomically. Private paths or target
  labels are not receipt fields.
- `evidence.dynamic.plan` connects these events to the existing terminal
  emission/admission rule. Future rejection probabilities must be supplied
  explicitly. It is a stagewise reference, not a learned owner transition law.

The source protocol is explicitly `alias iff equal target digits`, as in the
audited allocator. Distinct utterances with equal target digits require a
different declared protocol and cannot be relabeled to fit this one. Alias
identity is available only on arrival in this interface. An identity-only
query would be a distinct action and information design.

## Executable data interface

Run `python -m experiments.multimodal_output_portfolio.repair_20261026.evidence.train`
with `--input`, `--expected-sha256`, `--output`, `--steps`, `--learning-rate`,
`--seed` and `--joint-count-alpha`. The pinned JSON has schema
`hepta.repair.paired-development.v1`, role `development`,
`excluded_source_groups`, `prior_training` (`features`, `targets`,
`source_groups`), and `pair_observations` (the five PairObservation fields).
`source_claim` describes the actual upstream measurements. Hash identity
binds supplied bytes, not the truth of a caller's source claim.

The executable writes `joint_prior.json` and `joint_likelihood.json`. A
training run is not an independent calibration or efficacy test. Previously
opened qualification/confirmation groups may be explicitly reassigned to old
development, but cannot also count as fresh qualification for that repair.

## Verification scope

`python -m experiments.multimodal_output_portfolio.repair_20261026.evidence.verify --output REPORT.json`
runs the source-pinned same-WAV support regression, analytic receipt/control
tests, an independent finite-difference gradient comparison, and a synthetic
joint-learning counterexample with identical marginals and different joint
dependence. It also checks the explicit owner/cost adapter integration.

The historical aggregate identifies ten single-event likelihood columns;
the other ninety target-conditioned same-speaker couplings remain unknown.
The verifier does not invent paired observations, refit a current candidate,
execute a new native owner, or declare empirical calibration/generalization.

## Real source development experiments

`REAL_V6_REPORT.md` records actual frozen V6 encoder context and independently
trained full-joint vs parameter-matched factorized priors, with source-pair
holdout and an independent scalar rescore. Its gains are task-conditional;
the frozen original head remains better on clean inputs.

`REAL_AUDIO_REPORT.md` records a separate fixed-commit FSDD experiment with
actual CNN observations, disjoint observer-fit/likelihood-fit/test speakers,
same-WAV receipt checks and measured paired likelihoods. Alias structural
repair succeeds; the one-speaker paired estimate transfers worse than the
explicit independence comparator. It preserves an audit-discovered ECE
boundary correction and all original results. Neither experiment qualifies
unknown source groups or replaces the missing original audio checkpoint.

`RAW_EVIDENCE_ARCHIVES.json` binds the complete new-model and raw-prediction
archives with byte counts, SHA256 and per-file bundle manifests. The audio
archive is included here; the larger V6 prior archive is an external persistent
evidence artifact. Original downloadable source datasets are pinned rather
than duplicated. The audio archive retains both executed and corrected scoring
source, plus the original and amended ECE results.
