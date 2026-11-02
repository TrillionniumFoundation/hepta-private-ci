# Missing-information follow-up of PR #4548

This additive experiment continues `a793d55c23a7742378b081b162252da428a9fdb2`.
It preserves the two typed addressed architectures and their shared initialization.
It changes training coverage: exactly 300 of 600 steps use a removed raw write;
the other 300 use complete observations. Every fit starts fresh and retains the
final checkpoint. A model receives only `x`, `dt`, and `observed`. Labels enter
the supervised loss; availability enters only evaluation.

The 18 historical base-only final checkpoints are restored from the original
hash-bound evidence by the sibling video follow-up. Their identities are in
`../hcsn_video_followup_20261101/SHARED_CHECKPOINT_IDENTITY.json`.
The old and new models are evaluated on identical fresh confirmation arrays.
The new training stream differs from the historical training stream, and the
runtime is PyTorch 2.6 rather than the original 2.9. This is a comparison of the
new candidate revision with its historical baseline, not a pure causal estimate
of changing missingness supervision.

`results/run001/PROTOCOL.json` fixes training, dev calibration, confirmation,
and gates. `ALL_CHECKPOINTS.json` freezes all final fits. The separate
`evaluation.py` calibrates all models before any confirmation, writes
`ALL_CALIBRATIONS.json`, and requires its exact SHA and a publication commit
before opening the new confirmation stream.

Calibration selects a positive temperature by dev NLL and an abstention
threshold by dev coverage and a Wilson lower-bound heuristic. The four queries
within one episode are correlated, and thresholds are scanned using the same
dev labels. The resulting dev bound is **not a 95% reliability certificate**.
Confirmation accuracy and coverage are scored separately. Seed ranges are
descriptive; no episode-level confidence interval is offered as independent
training evidence.

Run from the repository root with one BLAS/OpenMP thread per worker and CPU
PyTorch, NumPy, and SciPy:

```sh
python -m experiments.hcsn_missing_answers_20261101.campaign freeze --out NEW_RUN
python -m experiments.hcsn_missing_answers_20261101.campaign train --out NEW_RUN --workers 3
python -m experiments.hcsn_missing_answers_20261101.evaluation calibrate \
  --out NEW_RUN --baseline HISTORICAL_RETENTION_RUN
# Publish and read back all source, protocol, checkpoints and calibration digests.
python -m experiments.hcsn_missing_answers_20261101.evaluation confirm \
  --out NEW_RUN --baseline HISTORICAL_RETENTION_RUN \
  --calibration-sha EXACT_SHA --publication EXACT_COMMIT
python -m experiments.hcsn_missing_answers_20261101.audit --run NEW_RUN
```

The historical and candidate model call interfaces carry no hidden target,
availability flag, dependency index, or teacher posterior. Missing answers can
still be partially predictable through observed task constraints. This study
does not label uniform guessing as Bayes optimal, infer recoverability from an
evaluation mask, or claim open-domain memory. The explicit WRITE/BRIDGE prior,
four keys, eight values, and symbolic alias relations remain.

Training phase CPU sums parent and waited descendants after parent imports;
fit timers are nested and must not be added again. Calibration and confirmation
CPU timers start after imports and identity checks. Historical preparation,
development, source publication, and package-management costs are not included.
Energy remains unknown; CPU seconds are not converted into joules.
