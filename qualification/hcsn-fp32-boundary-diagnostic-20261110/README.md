# HCSN scalar FP32 survival-loss diagnostic — RESEARCH_ONLY / HOLD

This independent negative control is stacked on HCSN scalar reference Draft PR #5793:
https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5793
Parent source head: df977867b606933cdc6ad34b81283756e1f21c2c.
The unchanged scalar source must retain Git blob 54e9e2440eb73399a95adf04d98674df68c191b3.

Unlike the previously documented float32 barrier/asset alias witness in
HCSN Draft PR #4382, this tests a separate probability-complement failure.
A naive FP32 CDF can round to exactly 1 near an absorbing boundary.
Computing survival as (1-CDF) then falsely returns zero; log survival is
undefined although true survival is strictly positive.

## Reproduce exactly

Python 3.10+ with NumPy and SciPy, from repository root:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/hcsn python3 -m unittest discover -s scripts/hcsn -p 'test_fp32_survival_boundary_diagnostic.py' -v
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/hcsn python3 scripts/hcsn/test_fp32_survival_boundary_diagnostic.py --report

Executed on a Linux CPU with Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0.
Four tests passed. On the deterministic 630-case parameter grid, no sampled
CDF was outside [0,1], and the maximum FP32-vs-FP64 *absolute CDF* difference
was 1.1225468654618709e-07. This does NOT establish tail relative accuracy.

At zero drift, x=1e-9, horizon=1, sigma=.2, the naive FP32 CDF is 1.0,
its FP32 complement is 0.0, but survival via the analytic zero-drift erf
formula is 3.989422570072065e-09, with finite log(-19.339619335797668).
RESULT.json and tests.log retain observed results.

## Not proven

This deliberately naive FP32 implementation is only a CPU negative-control
diagnostic, not a recommended production kernel, original runtime behavior,
GPU/NPU test, tensor autograd, or arbitrary-drift closed-form stable survival
implementation. The erf formula is used only for zero drift. No event-reset,
history/refractory, network training, independent task quality, speed, energy,
signed adoption, or native Rust qualification follows from these tests.

Next gates: independently derive and verify stable general-drift log-survival;
test tail, near-boundary, short/long horizon and low-noise parameter domains,
actual device-dtype gradients, reset/multiple events and native training;
then compare against matched strong baselines at total cost.
HOLD / NoUpdate; do not merge or enable production from this evidence.
