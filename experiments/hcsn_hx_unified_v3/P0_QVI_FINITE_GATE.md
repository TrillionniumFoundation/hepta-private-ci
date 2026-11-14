# P0 scalar regenerative QVI: finite, non-cancelling diagnostic gate

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false /
production_activation_allowed=false.** Narrow child of #4428 at exact parent
`adf8da8330bca79383c3dd80c878cf90acc9b73a`; parent `stopping.py`
Git blob `cd76744cdd67afd3fec8c71e087ceb704c23cc10`. No changes to
He–Xiong financial equations, scalar kappa, Lambert-W boundary, training,
Rust/GPU, owner authority, historical test outcomes or deployment.

## Source-exact negative witnesses

On the exact #4428 `stopping.py`, unmodified local reproduction:

1. `Stop(0,1e17,.1,0,-1,0)` and `x=0`: the computed continuation
   `obstacle` is falsely **0.0**, although the fixed-policy identity
   gives approximately **-1.0**. The returned `complementarity` is
   **0.0** despite `generator=-3.103...`, so it is not a reliable QVI
   certification. This is cancellation of values near `2.236e17`.
2. `Stop(-1,1e200,.1,0,-1,0)`: `qvi` raises `OverflowError` on
   `diffusion**2`, although the revised #4428 characteristic root and
   threshold are finite. `Stop(0,1,1e308,0,-1,0)` overflows at the
   squared kappa path.
3. `Stop(1e308,1e308,.1,0,-1,0)` returns an **infinite** renewal
   `value` rather than refusing an unrepresentable f64 amplitude.

## Minimal bounded repair

- For the **fixed-threshold** continuation region use the exact ratio
  `D*V(reset)/V(x)=exp(-rho*tau-kappa*(x-reset))` and evaluate the
  small difference using `expm1`. For the FIRE region the intervention
  residual is identically zero **by the policy definition**, not by
  an independent proof of policy optimality.
- Expose `regenerative_obstacle` independently for diagnostics, but do
  not allow it to imply a complete QVI without the generator check.
- Form the characteristic generator with `(diffusion*kappa/sqrt(2))**2`
  and `math.fsum`; explicitly **reject** continuation generators whose
  finite absolute error exceeds the predeclared `1e-9` diagnostic scale.
  No clipping, silent `nan`, or absolute-to-relative gate substitution.
- Refuse nonfinite renewal amplitude/value, nonfinite obstacle or
  generator. Retain successful ordinary scalar QVI behavior.

The absolute generator scale is appropriate only for the sampled bounded
reference QVI unit tests. A huge legitimate value with insufficient f64
absolute residual resolution is **unresolved**, not falsely certified.
No global QVI, interval error bound, all-parameter differentiation, or
neural training claim is made.

## Executed verification

Relevant parent source and existing branch-point tests were materialized
byte-exact from GitHub. SHA matches: original stopping source
`cd76744cdd67afd3fec8c71e087ceb704c23cc10`, unchanged existing
8-test file `7a0ecf72658165d14d945784d1b193f0ef21ca53`.

```
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_qvi_finite_gate
# 13/13 methods PASS, 0 skipped; Python 3.13.5, SciPy 1.17.0 CPU
```

A separate deterministic moderate-domain sweep, seed `2026103121`,
covered 512 parameter tuples with 4 states each: **512 accepted**, **0
refusals**, **0 non-arithmetic exceptions**, **0 positive QVI complementarity
violations**; maximum absolute complementarity `7.924e-16`. The
extreme finite-root cases above explicitly reject numerically unresolvable
full-QVI outcomes, while the stable obstacle accessor still returns the
expected approximately -1.0 negative sign. The unchanged #4428 independent
kappa 6-test module is not claimed as rerun here.

## Blockers still open

P0: financially coupled HX obstacle/fixed point, global interval precision,
full higher-dimensional and low-precision QVI/gradients. P1: registered
Call/Risk/Margin causal advantage under matched slopes and budgets. P2:
repeated events, long recall and irregular clocks. P3: four-modal paired
alignment and robustness. P4: Rust/GPU 64–4096 Cell/energy/recovery. P5:
net-cost matched trained-backbone superiority. No production activation.
