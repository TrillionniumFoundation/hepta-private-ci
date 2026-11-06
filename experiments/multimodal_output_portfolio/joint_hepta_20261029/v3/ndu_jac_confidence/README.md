# Learned confidence for the retained JAC banks

**Disposition: a missing confidence premise is supplied under the finite
known-support contract; the strong-baseline and paid-deployment gates remain
NO_GO.** This does not repeat the optimization-gap study or relabel its empirical
DP parity as a new algorithm. It adds a non-oracle model confidence layer and a
proof that propagates safe downstream improvements through an unchanged root.
It analyzes all 20 retained 64-per-row banks without acquiring new observations,
changing the objective, selecting favorable seeds, or changing the prior result.

**Current implementation is the corrected revision.** Independent internal
review found three acceptance bugs in the initial adapter: an empty successor
identity, an invalid proposed policy, and tolerated row-mass error amplified by
a large currency offset. The initial sources, results and counterexamples remain
in [history/initial](history/initial/ARCHIVE_MANIFEST.json). The corrected
implementation rejects the invalid inputs, normalizes both policies, and centers
value/advantage arithmetic. See [CORRECTION.md](CORRECTION.md) for the actual
repair and replay receipt; the initial implementation is superseded.

## What this work adds

The inherited `ndu_jac/policy_gate.py` requires simultaneous intervals for the
baseline policy's complete recursive Q values; its original finite study
supplied these intervals using the true model. Here, fixed-sample exact binomial
intervals for each unknown transition probability are combined with robust
entropic backups to construct those Q intervals **from the counts**. The event
covers the model and therefore all policies fitted on the same counts.
Data-dependent policy selection does not require an invented independent
holdout, although the fixed-sample iid access contract is essential.

A separate gain-propagation bound handles certified downstream changes even
when the root action distribution is unchanged. Its formula, assumptions and
complete proof are in [THEORY.md](THEORY.md). A deterministic example shows why
this extends the old root-local sufficient gate. Classical confidence sets and
robust dynamic programming are explicit predecessors; no new RL originality or
near-information-cost claim is attached.

## Frozen analysis and source identity

The local [corrected protocol](protocol.corrected.json) precedes corrected
evidence execution and binds the implementation hashes. It discloses
prior reading of historical results. These are reused development banks, not
untouched confirmation tasks or an externally preregistered experiment.

- Historical input: all rows of `../ndu_jac/evidence/gap_study.json`.
- Historical artifact SHA-256:
  `56ad5d043a2ac661b3d0155747851a67e282d7faa42e7fa463ef5b581ca765dd`.
- Original task: 52 states, 124 legal rows, 64 draws per row; 7,936 observations
  per bank. New observations: **zero**.
- All four original and sixteen additional banks are retained. `eta=2` and
  `rho=.17` remain unchanged.
- Familywise `alpha=.05` across all 20 banks and 164 non-singleton outcome
  coordinates per bank. Each two-sided marginal interval receives
  `0.05/(20*164)=0.000015243902439024392` error budget.
- Required strong baseline: original actor with probability-argmax extraction.
  Weak stochastic actor is retained only as a secondary diagnostic.
- Proposal: the already stored same-bank DP policy; no new fit is concealed.
- Declared audit charge `.01` is inherited from the finite gate example. It is
  a toy utility charge, not a dollar or calibrated hardware price.

Known full supports, rewards, durations and successor identities are provided
before estimating probabilities. The support adapter strips all probability
values. The known state construction itself remains part of this limited
reference contract. This does not solve unknown-support or arbitrary latent
state inference, or transfer the old state labels to a physical tool for free.

## Results

Every number below is computed from [result.corrected.json](result.corrected.json).

| Endpoint | Stochastic actor baseline | Strong probability-argmax actor baseline |
| --- | ---: | ---: |
| Gated policies accepted after declared `.01` audit fee | 0 / 20 | 0 / 20 |
| Old root-local gate accepted with the same learned intervals | 0 / 20 | 0 / 20 |
| Positive unpriced propagated bound before paid acceptance | 20 / 20 | 0 / 20 |
| Range of unpriced gain lower bounds | 0.0000270029–0.0001198054 | 0 |
| Mean locally certified changed rows before paid acceptance | 19.35 | 3.65 |
| Mean actual baseline utility | 0.2067906321 | 0.2525707760 |
| Mean returned-policy utility | 0.2067906321 | 0.2525707760 |
| Mean actual gain after the declared audit fee | -0.0100000000 | -0.0100000000 |
| Same-bank DP proposal truly worse than this baseline | 4 / 20 | 6 / 20 |

All 20 observed true probability vectors lie within the constructed family
sets. Across both baselines and all banks, the computed baseline-Q intervals,
risk-tilted probability lower bounds and returned net-gain bounds are respected
by separate exact true-law evaluation. These observations check the
implementation on the retained banks; the mathematical coverage guarantee
comes from the binomial argument and induction, not these 20 observed events.

The positive secondary bounds are **not accepted improvements**: all are below
the fixed audit charge. Against the mandatory strong baseline, the root gain
bound is zero in every bank, despite some locally certified changes in rows
that do not produce a positive root certificate. The method correctly leaves
the baseline deployed and charges the failed audit. There is no positive
lifecycle result and no justification for large-scale training.

The corrected replay changes none of the 40 paid acceptance decisions, source
banks, probability boxes or locally accepted row counts. Maximum reported
true-value drift is `5.551115123125783e-17`; maximum gain-bound drift is
`4.0657581468206416e-20`. These normalization/centering differences are retained
in [correction_comparison.json](correction_comparison.json). This replay is a
repair check on existing data, not new scientific confirmation.

## Computation and cost accounting

Mean probability-box construction in the corrected replay took about `0.02415 s`
per bank. Additional confidence/gate computation averaged `0.00960 s` for the
stochastic baseline and `0.01094 s` for the strong baseline. These are the new
measured timings, not a controlled speed comparison with the archived initial
execution. The same probability boxes are
shared; charging them independently to each method would be needed in a
standalone deployment comparison. The raw record contains per-bank wall and CPU
times; source hashing and JSON serialization are outside the total-run timer.

Historical acquisition and actor fitting are inherited costs, not free resources.
No new provider invocation was made. CPU timing is not converted to money and
hardware, engineering and amortization remain unpriced. The `.01` audit fee
only instantiates the old declared utility tariff. The conclusion is already
negative at that limited paid endpoint; no broader saving is asserted.

## Reproduce

From the repository root with NumPy and SciPy available:

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac_confidence.test_confidence -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac_confidence.study \
  --protocol experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac_confidence/protocol.corrected.json \
  --evidence experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac/evidence/gap_study.json \
  --output /tmp/ndu-jac-confidence-new.json
```

The runner refuses to overwrite evidence and verifies the complete historical
artifact and corrected implementation hashes. Eleven behavioral tests compare
the box optimizer with an independent
linear program, enumerate fixed-sample binomial coverage, check policy-uniform
value bounds, demonstrate delayed improvement through an unchanged root,
check stochastic/terminal-branch gain propagation on a law grid, and retain the
sunk charge after rejecting an adverse proposal. Five added regressions reject
empty state/action identities and malformed baseline/candidate policies,
preserve a large downstream continuation in risk tilts, and prevent probability
mass tolerance or a common currency offset from creating an improvement. The
real-arithmetic theorem
has not received external mathematical review; endpoint arithmetic uses ordinary
floating-point SciPy quantiles and is not a formal interval implementation.
