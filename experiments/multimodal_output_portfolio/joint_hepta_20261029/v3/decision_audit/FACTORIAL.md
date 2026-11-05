# Four-arm attribution and complete captured costs

This second review stage adds an independently pinned full-panel ledger
analyzer and descriptive reanalysis of the existing V3 matrix. It does not
claim new generator training or replace the original negative results.

| Arm | Controller | Generator |
| --- | --- | --- |
| 00 | Fixed | Frozen |
| 10 | Learned | Frozen |
| 01 | Fixed | Learned |
| 11 | Learned | Learned |

For either mean or gamma-2 empirical CE, report control U10-U00, generator
U01-U00, joint U11-U00 and interaction U11-U10-U01+U00. CE is calculated per
arm before taking differences. CE of paired differences is a different
quantity and is never substituted. Crossed source/seed bootstrap keeps all
arms paired; small seed counts and unadjusted exploratory intervals remain
explicit. No summary-only confidence interval is manufactured.

## Actual historical reanalysis

Inputs are fixed V3 `evidence/MATRIX_READABLE.json` (SHA-256
`bb6d5b6015006aa9b4a373d45c8f6aa930ed7eac97b496679e1f974d27f84f52`)
and `protocol.json` (SHA-256
`ab148cfa2f95b87d9100d2908d00ae671a1180e5c2cf0c34f1d1a7861b4f26f9`).
All 3 seeds x 2 widths x 2 cores x 4 arms are retained, without pooling cores
or widths. `evidence/HISTORICAL_FACTORIAL.json` contains every contrast.

For the dual core, joint-minus-baseline and interaction are each positive in
three cells and negative in three cells. Stable joint-training benefit remains
unproved. This is arithmetic on inherited summaries, not fresh raw-trajectory
revalidation, new confidence intervals, or a new holdout experiment.

The old fixed schedule was preregistered rather than validation-tuned. The old
`greedy` name means actor-logit argmax, not one-step expected VOI. Old fixed and
STOP paths still invoked `policy()` at each step. These limits stay attached
to the reanalysis; changing the new runner cannot retroactively fix old costs.

## Ledger admission

The prior design digest fixes sources, training seeds, repetitions, four arms,
failure utilities, objective and cost unit. A separate post-execution capture
digest pins all episode and physical-event IDs. The analyzer checks both.
Missing failures, whole seeds, cost events or training-arm receipts reject.
Retries of the same identical physical receipt charge once; conflicting retries
and cross-arm reuse reject. Unselected candidates and failed events remain
charged. Unknown cost is not zero. Encoder, generation, planner, critic,
verification and seal categories need explicit receipts, including explicit
not-run records. Inclusive nested envelopes cannot be summed as exclusive cost.

Setup, training, analysis and publication remain separate unamortized outer
costs. The analyzer does not authenticate the capture owner, prove online
information legality, enforce physical resource caps or verify model updates.
Same total training budget and same component training dose are separate
estimands; equal update counts alone establish neither.

## Reproduce

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_factorial -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.factorial --historical-matrix experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/MATRIX_READABLE.json --matrix-sha256 bb6d5b6015006aa9b4a373d45c8f6aa930ed7eac97b496679e1f974d27f84f52 --protocol experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/protocol.json --protocol-sha256 ab148cfa2f95b87d9100d2908d00ae671a1180e5c2cf0c34f1d1a7861b4f26f9
```

For new complete ledgers use `--bundle INPUT.json --design-sha256 HASH
--capture-sha256 HASH`; `test_factorial.fixture()` is an executable synthetic
format example. Thirteen behavioral tests include a failed unselected
candidate whose real cost reverses the apparent control gain. Removing that
cost is detected even when the episode seal is altered to agree.
