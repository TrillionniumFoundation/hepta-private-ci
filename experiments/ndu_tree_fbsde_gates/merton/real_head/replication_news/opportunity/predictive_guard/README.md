# Predictive falsification before shared-policy reuse

Research-only / DENY_ALL. Parent `e605e7aea52b1727cd2c49ef8d23510300c45552`.
No original source, training rule, compiled asset, native NDU/Neuron/Reader owner,
selected weights, previous observation or production permission is modified.

## Why this increment

Exact agreement with a solver does not make the learned opportunity distribution
correct. The prior's smoothed four curves give strictly positive probability to
every count, so a merely positive likelihood never detects practical model failure.
A lookup table can repeat a confident but misspecified model extremely cheaply.
The new wrapper tests the fixed conditional model after actual calibration and
before its next lookup. It does not invent new data when no compatible new-source
artifact is available. This remains the already examined 64/32/32 AG News panel.

## Declared null, alternative and limited guarantee

Under the inherited NULL model, a single equal-mass latent curve is selected;
conditional on it, disjoint calibration counts at checkpoints are binomial with
probabilities (correct+1)/18. The latent curve is shared across checkpoints, so
unconditional counts are NOT independent. For observed count k_t, let p_t be the
mixture's posterior predictive count probability. Set q_t=1/(n_t+1) for all counts.
Both p and q are strictly positive normalized conditional distributions.

Starting from E_0=1, E_t=E_(t-1)*q_t(k_t)/p_t(k_t). Conditional expectation under
this exact null is E[E_t|past]=E_(t-1)*sum_k q_t(k)=E_(t-1). Stop using the model
if any E_t>=20. The maximal probability of crossing is at most 1/20 UNDER THIS
NULL. The separate joint-law implementation enumerates all 1,377 terminal count
histories, verifies all 91 conditional identities and computes the actual exact
crossing probability. A policy that stops observing earlier only truncates these
paths. There is no Monte Carlo error in this finite-law calculation.

This is NOT a statistical validation that the real task follows this null. It
is not an accuracy/safety guarantee, a power guarantee against every alternative,
a fleet-wide error budget, or evidence that failure to reject confirms a model.
The overlapping prior-training folds and 48-to64-row learning-curve transfer
remain unverified assumptions. Repeated use of the same original count stream
is correlated and must not be exponentiated as independent evidence. The test
level is distinct from the NDU soft-preference risk coefficient.

## Execution and fallback

Monitor records bind the original ordered32 calibration IDs and immutable scope.
Duplicate, skipped, rewritten or reordered observations and mismatched optimizer
progress are rejected. The current source owner reconstructs each new count from
actual fixed8/32/128 Head predictions. No future checkpoint is observed by the
guard. A repeated lookup of an identical history is idempotent, not fresh evidence.
Predictive values are copied into the next durable decision record before any
further training begins. After rejection the wrapper does not query the old policy. It stops and returns
the ALREADY EXECUTED eight-step Head; this is a cheap baseline, NOT certified safe
or correct. It does not refund sunk updates. A failure leaves no success seal.

The exact null test includes deliberately constructed low-count histories. Those
are labeled mechanism/counterfactual controls, not new human outcomes. The formal
experiment computes every calibration count from original data, and does not
inject fake observations. Under the actual archived panel the guard may remain
inactive; report that rather than tune the threshold to create an apparent win.

## Measurement, lineage and reproduction

Six arms, four inherited cost/budget scenarios and three rotated timing repetitions
are 72 lifecycles over the SAME32 historical holdout items, not72 independent
panels. Every arm owns a fresh1540-parameter Head; no free cross-arm trained weights.
One prior is physically fitted (512 updates), one shared policy compiled/loaded,
and setup charges are kept separate. Monitor computation is inside the decision
and lifecycle CPU/wall measurements, including synchronous execution journals.
Fees remain declared utility tariffs, not dollars or measured hardware prices.
Offline exhaustive/scalar audits are separate work, not executed online training.

The new scalar/model audit reuses the established independent source/SGD reviewer
and adds a separately implemented joint-likelihood calculation (not the monitor's
incremental posterior code). Same author/separate implementation and process;
no independent organization, signer or authenticated target hardware.

Use Python3.13/NumPy2.3.5, one BLAS thread and original NEWS_ARCHIVE SHA256
`195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7`:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head/replication_news
python "$D/material_news.py" --archive "$NEWS_ARCHIVE" --output /tmp/guard-material
python -m unittest discover -s "$D/opportunity/predictive_guard" -p test_guard.py -v
python -O -m unittest discover -s "$D/opportunity/predictive_guard" -p test_guard.py -v
python "$D/opportunity/predictive_guard/trial_guard.py" --material /tmp/guard-material --output /tmp/guard-run
python "$D/opportunity/predictive_guard/audit_guard.py" --archive "$NEWS_ARCHIVE" --material /tmp/guard-material --run /tmp/guard-run --output /tmp/guard-audit.json
```

All output paths must be new. No new Encoder/Reader call, neural preference fit,
world-model training, general FBSDE, new source, prospective calendar window or
production admission is established. Original heldout-source evaluation remains
a separate unfinished requirement. Existing blocking checks must still run.

Cross-interpreter behavior comparisons exclude guard_scope: it binds the entire
run-specific prior receipt, including measured timing. Each scope is independently
checked against that run's source/prior before comparison; scopes are not forced
to equal or recomputed from reduced, timing-stripped receipts. The first naive
comparison failure is retained as an accounting diagnostic, not a model mismatch.
