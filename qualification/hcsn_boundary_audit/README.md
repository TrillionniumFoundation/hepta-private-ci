# Trained boundary gradient audit

`audit_trained_gradients.py` checks the derivative of the implemented FP64
projected-network query cross-entropy at final learned-boundary checkpoints.
It uses the first development episode for each task in the retained DATA file,
for every completed `c0_b1` and `c1_b1` seed/arm. The selection does not inspect
the case losses or gradient errors.

## Exact inputs and differentiation

The caller must pin SUMMARY.json with SHA256. The audit verifies its DATA,
PLAN, source-before/source-after identities, result records, checkpoint hashes,
model configurations, completed updates and tensor digests. It reads verified
checkpoint bytes through `BytesIO` with `torch.load(weights_only=True)`.
The completed boundary roster must equal the declared seeds crossed with the
two learned-boundary arms; matching only its size is insufficient.

Each loss evaluation starts from a fresh episode state. Automatic
differentiation is compared with central differences in the scalar
`raw_log_boundary` coordinate at steps `0.001, 0.0003, 0.0001`. No optimizer
step, gradient clipping, loss clipping or posterior repair occurs. A
`finally` block restores the boundary even when a perturbed forward fails,
then verifies the entire model tensor digest.

The original thresholds remain:

- Each absolute gradient discrepancy: `2e-6 + 2e-3 * abs(AD)`.
- Spread across finite-difference steps: `< 4e-6 + 4e-3 * abs(AD)`.

The report retains both perturbed losses, all derivative errors, physical
parameter and state ranges, tolerance-floor dominance, attempted/completed
forward/backward counts, process CPU/wall time, and input hashes before and
after the audit. Exceptions produce a failed report and nonzero exit.

## Reproduction

Use the exact retained training sources and an FP64 CPU Torch environment.
The hosted pilot recorded 23 Python source hashes; the selected import used for
the audit matched all 23, without claiming to be a complete Git checkout.

```bash
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B -m qualification.hcsn_boundary_audit.audit_trained_gradients \
  --pilot /path/to/experiment \
  --summary-sha256 c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715 \
  --output /new/path/RESULT.json

python -B -m unittest qualification.hcsn_boundary_audit.test_audit_trained_gradients
```

The focused tests cover refusing an altered checkpoint before deserialization,
rejecting same-size wrong seed/arm rosters or model labels, and restoring
parameters after an injected failure following a real AD forward/backward.

## Recorded hosted-pilot result

Training input: head `5578bd1931afcb6facbf72176cf479b902301feb`, Actions run
`43127560720`, job `130883401533`. This was a completed 12-arm, three-seed
synthetic development pilot with 32 update opportunities per arm. The six
learned-boundary checkpoints each had 32 completed Adam updates.

The subsequent audit ran locally with Python 3.12.14 and Torch 2.8.0+cpu on
host `05afa1b52275`, using audit blob
`c370de514f3861379e54784845489292a2a8a5f9`. All 18 selected cases and 54
finite-difference comparisons passed. Its 126 forward and 18 backward calls
completed; all model and input identities were unchanged.

| Quantity | Observed value |
| --- | ---: |
| Maximum absolute gradient discrepancy | 5.227647637690014e-9 |
| Maximum relative gradient discrepancy | 8.342410669444949e-6 |
| Maximum spread across FD steps | 5.171862937913829e-9 |
| Maximum posterior mass discrepancy | 4.440892098500626e-16 |
| Cases where the absolute tolerance floor dominates | 7 / 18 |
| Process wall time, including imports and input checks | 90.058638701 s |
| Process CPU time | 88.945529962 s |
| Wrapper elapsed wall time | 90.553531357 s |

The physical log-boundary range was
`[-0.008175943290435491, 0.008972971301291014]`; the selected episode gaps
were `[0.001, 0.16]`. First active-cell probability reached 0.1697666914,
tail probability reached 1.0319123915e-5, and refractory probability reached
0.1078324711. These are observed ranges, not certified error domains.

The compact receipt in `evidence/hosted-gradient-43127560720.json` binds the
original RESULT, command, wrapper receipt, source import, and logs by hash.
The complete original RESULT is retained separately as
`evidence/hosted-gradient-43127560720-raw.json`.

## What this establishes

The selected final checkpoints' task-loss boundary gradients agree with finite
differences of the same projected implementation. This is distinct from
continuum-kernel accuracy, complete visited-training-domain coverage, trained
model superiority, rare-tail relative precision, or independent-source
generalization. All numerical, continuum-domain, whole-training-trajectory and
product-adoption qualification flags remain false. The pilot does not establish
training adequacy or convergence.

