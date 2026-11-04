# Reproduce the archived 32-fit completion

The immutable source and archive parent is
`903946f15dd79bc53a39a479230e366df04a371f` in
`TrillionniumFoundation/hepta-private-ci`.
The two scripts in this directory only acquire existing bytes and reconstruct
records/statistics. They do not train, generate worlds, change models, refit
readout decoders, tune parameters, or select successful fits.

## Requirements and full reconstruction

Use normal Python (do not disable assertions with `-O`), NumPy, and SciPy.
Network access to `raw.githubusercontent.com` is needed for acquisition. The
published archives total 179,515,856 compressed bytes, with base64 transport
and additional space required for extraction. Run from the repository root:

```bash
python tools/hcsn/digital_feedback_20261101/audit/acquire_confirmation.py \
  --output /tmp/digital-feedback-confirmation-audit --workers 2
python tools/hcsn/digital_feedback_20261101/audit/complete_confirmation.py \
  --cache /tmp/digital-feedback-confirmation-audit \
  --output /tmp/digital-feedback-confirmation-result
```

Acquisition pins the source commit rather than a mutable branch. It fetches 32
confirmation archives, five stage control archives, and the exact frozen
protocol, statistical/quality code, seal and inherited custody evidence.
Both acquisition and collection verify archive part hashes, decoded bytes,
archive hashes, member inventories, safe regular-file paths and member hashes.
An existing corrupt cache fails verification; do not publish partial results.
No credential values are accepted or saved by these scripts.

Collection verifies all 32 fit identities and model/seal/chronology bindings,
all 16 arms per fit/domain, all 64 paired worlds, raw task-state and decision
records, resulting summary values, linked diagnostic rows, quality reports
and retained decoder MSE arithmetic. It also reconstructs the process cost
ledger from all five control archives. Its assertions and `Review` violations
must both pass before statistical finalization is permitted.

## Split collection and statistical execution

If the collection host has NumPy but not SciPy, collect without inference:

```bash
python tools/hcsn/digital_feedback_20261101/audit/complete_confirmation.py \
  --cache /tmp/digital-feedback-confirmation-audit \
  --output /tmp/digital-feedback-confirmation-result --collect-only
```

Move `CONFIRMATION_COMPLETION_INPUTS.json.gz` and the exact `frozen/` directory
to a host with NumPy/SciPy, using verified transport. Then run:

```bash
python tools/hcsn/digital_feedback_20261101/audit/complete_confirmation.py \
  --cache /tmp/digital-feedback-confirmation-audit \
  --output /tmp/digital-feedback-confirmation-result \
  --inputs /tmp/digital-feedback-confirmation-result/CONFIRMATION_COMPLETION_INPUTS.json.gz
```

The finalizer requires a passed collection record, matching immutable source,
byte-identical protocol hash, equal protocol contents and the frozen
statistics source hash. This path does not rerun raw collection: retain its
input transport hash and acquisition custody when using it. A supplied input
file is not self-authenticating merely because it contains `passed:true`.

## Outputs and expected decision

- `ANALYSIS.json`: all four primary and 34 secondary comparisons, every fit
  difference, eight-criterion quality summaries for every candidate/domain,
  descriptive decoder recovery summaries, and equal-fit arm means.
- `CONFIRMATION_COMPLETION_AUDIT.json`: archive receipts, comparison counts,
  all process receipts/cost definitions, seal/history custody, inherited
  training qualification and limits of this reconstruction.
- `CONFIRMATION_COMPLETION_INPUTS.json.gz`: derived collection checkpoint;
  it can be reproduced from the published archive and is not a new dataset.

The frozen result is `acceptance:false`, four unmet benefit gates, and zero of
256 required candidate/fit/domain quality checks passing all eight criteria.
All 32 fits must remain present. Primary `n` is 32, not the world or decision
count. No new fit or post-hoc threshold is permitted in this completion.

The 2026-11-04 record contains 65,536 primary episodes, 360,155 decisions,
4,096 cohort worlds, 4,096 separately counted probe episodes,
15,595,691 numeric comparisons and 9,911,041 equality comparisons with zero
violations. Maximum numeric residual is about `4.44e-16`; ordinary supported
numerical-library differences should be assessed against the recorded
`1e-12 + 1e-10*abs(expected)` comparison tolerance.

Expected historical CPU lower bound is `8326.229650133` seconds. Controller
self CPU is **unknown** for `development_001`, `development_002`, and
`training_001`. Never replace these nulls with zero or call this complete
historical cost. All 28 guarded `training_001` exits consumed positive CPU
(55.072509 seconds combined) despite not producing scientific fit results.
Nested candidate/content/execution/diagnostic/persistence times must not be
added again to complete worker totals. Collector CPU/wall times are new audit
measurements and will change on another execution; full output byte identity
is therefore not the reproducibility criterion.

The raw checker is pinned to SHA256
`d30a2ebfe8743ccfefbd839d68e46e82a6682aa3b8bc3f61541c934eb559915e`.
Collection uses unchanged AST function/class bodies for `Review`, `legal`,
`initial_state`, `advance`, `latent_contract`, `retained_label`,
`decision_values`, and `episode_values`, excluding unused statistics functions
and SciPy imports. This preserves the earlier author's separate formula
implementation; it is not third-party authorship. `quality.py` is the frozen
project implementation. Teacher values, logits, latent random draws and
readout coefficients are retained inputs, not re-executed models. The 480
training-receipt audit is inherited pre-seal evidence, with 32 enclosing
process-receipt hashes rechecked now; the optimizer updates are not rerun.

All report conclusions and scientific limitations are in
[`../REPORT_ZH.md`](../REPORT_ZH.md). Frozen protocol/statistics/model artifacts
are unchanged by this completion.

An additional check computes the primary sample means, scalar sample variances
and Student-t intervals directly without invoking project statistics code:

```bash
python tools/hcsn/digital_feedback_20261101/audit/verify_completion.py \
  --inputs /tmp/digital-feedback-confirmation-result/CONFIRMATION_COMPLETION_INPUTS.json.gz \
  --output /tmp/digital-feedback-confirmation-result
```

It writes `COMPLETION_FINALIZATION_CHECK.json`; this run's maximum primary
interval difference is `1.3877787807814457e-17`.
