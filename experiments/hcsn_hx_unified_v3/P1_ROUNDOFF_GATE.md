# HCSN P1 slope calibration: f64 admission roundoff guard

**Research-only / DRAFT / DENY_ALL / all_blockers_closed=false /
production_activation_allowed=false.** Independent child of #4427 at exact
head `2611d19044d5aaf61b04febea3ba82f118a339f2`. This patch changes
only local P1 calibration diagnostics and new tests/evidence. It does **not**
change HX finance equations, regenerative stopping, P1 training, authority,
Rust/GPU, pretrained weights, historical held-out results or deployment.

## Original exact-source failure

The original `matched_slope.py` Git blob
`46d0c86926c53de389c61f0c87727d90b30fb829` checks agreement of two
five-point slope estimates but never verifies that its delivered floating-
point affine mapping reproduces the desired output at the training anchor.

- For `channel(z)=1e18+z`, `ordinary(z)=0.5+0.25*z`, `anchor=0`, `step=1e6`,
  the original accepts the slopes, but `calibrated(channel(0)) == 0.0`
  instead of **0.5**: catastrophic cancellation of offset and scale times
  the channel value. The discrepancy is **not** an advantage or a small
  evaluation tolerance.
- For `channel(z)=1e12+z`, `ordinary=sigmoid`, `anchor=.125`, `step=.001`,
  the original reports internally agreeing stencils but the returned anchor
  output differs from the ordinary gate by approximately **1.01e-5**. The
  channel signal in each small finite-difference window is comparable to
  the source output ULP; agreement between two quantized stencils is not
  evidence of an accurately resolved derivative.

## Narrow correction

1. Track an explicit conservative **heuristic** roundoff floor:
   `8 * max_ulp(sampled_outputs) / step / |estimated_slope|` at each of
   `h` and `h/2`. Refuse the match if this exceeds the already declared
   `relative_tolerance`; never silently widen that tolerance.
2. After constructing the same affine operation consumers will execute,
   recompute its actual anchor output and refuse if the discrepancy exceeds
   `max(32*ulp(ordinary_value), 1e-12*max(1,|ordinary_value|))`.
3. Preserve signed matching and the existing math/finance API; expose the
   measured `roundoff_rel_floor` separately from smoothness disagreement.

The numerical floor is deliberately conservative, **not** a rigorous interval
bound or complete proof of differentiability. A rejected input is unresolved,
not proven impossible. This is still only local anchor matching, not
mechanism attribution, trajectory matching, or P1 utility evidence.

## Actual reproduction and scope

Python 3.13.5 / SciPy 1.17.0 / NumPy 2.3.5, Linux CPU:

```
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_matched_slope \
  experiments.hcsn_hx_unified_v3.test_slope_roundoff_gate
# 13 methods PASS, 0 skipped
```

The parent P1 `matched_slope.py`, `test_matched_slope.py`, and upstream `hx.py`
were materialized byte-exact from GitHub and their `git hash-object` values
matched respectively `46d0c86926c53de389c61f0c87727d90b30fb829`,
`4b97b68a9813b5125680175d31f55fc22aea804a`, and
`b6afc3c957297ed9b37b4f0177e0343ee6607f83` before any edit.
The complete 9/9 pre-existing P1 tests, including both actual upstream HX
integration methods, passed on those exact original Git blobs. The 13/13
post-edit run includes the same nine original tests and four new negative/
positive tests. No CI, GPU, broader finance domain, or held-out training
claim is made.

## Remaining blockers

P0: global coupled obstacle/fixed point, independently bounded uncertainty,
parameter-domain and real low-precision certification. P1: frozen matched-
parameter/slope/budget Call/Risk/Margin ablations and positive external
net-utility evidence; historical negative findings remain binding. P2:
Selective Copy/MQAR, overwrite, long recall, irregular time and repeated
regeneration. P3: real four-modal paired tasks, OOD robustness. P4: Rust/GPU
64–4096 Cell throughput, tail latency, measured energy/recovery. P5:
external tuned-baseline and full-cost equal-budget superiority.

**Never merge for production or flip admission based on these numeric tests.**
