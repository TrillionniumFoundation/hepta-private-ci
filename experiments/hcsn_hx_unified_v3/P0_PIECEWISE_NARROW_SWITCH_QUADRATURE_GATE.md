# P0 two-segment moving barrier: narrow-switch Gaussian precision gate

**RESEARCH ONLY / DRAFT / DENY_ALL.** This is an additive, scoped correction stacked on PR #4478 exact HEAD `dd0449834da8e354088d35752bc1d3946801d5f4`. Do not claim HX/QVI closure, deployment readiness, production activation, model quality, or native-cell performance. Keep `all_blockers_closed=false` and `production_activation_allowed=false`.

## Reproduced independent counterexample

Model: `x=1,b=0,mu=0,sigma=0.5,c1=0,c2=0.8,T=1,q=0.2,switch=1e-70,dps=100`.
The exact switch-to-zero limit is the independent closed-form `linear_boundary_first_hit(...,c=0.8,T=1,q=0.2)`. The true difference from the limit is O(1e-70); the previous unscaled physical-space killed Gaussian convolution gave **F error ~1.8625e-15** and **G error ~1.6182e-15** even though its probability ordering check admitted the answer. New standardized-coordinate integration gives **F difference ~6.8818e-71** and **G difference ~6.1938e-71**. These are differences from the zero-switch limit, not certified numerical error bars.

Additional `q=0` witness: `switch=1e-40, dps=60` made the previous kernel refuse the result despite a finite, well-defined physical solution. Standard-normal panels now resolve it. The unchanged ordinary two-segment witness `F≈0.13034319097200746, G≈0.11371219839348145` remains consistent.

## Method

Set `z=(y-(a+(mu-c1)*switch))/(sigma*sqrt(switch))` and absorb the Jacobian exactly. The killed transition becomes `phi(z) * (1-exp(-2*a*y/(sigma^2*switch)))` on `y>0`. Integrate in standardized normal coordinates with explicit finite-width normal-mass panels, retaining the +infinity tail and the existing strict physical/proved-slope acceptance checks. No clipping, probability forcing, or Monte Carlo approximation.

## Locally executed verification

Python 3.13.5, mpmath 1.3.0 on Linux CPU. **12/12 unittest methods PASS (8 upstream plus 4 new), zero skips**, `compileall` PASS. Command:

```sh
PYTHONPATH=. python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_piecewise_boundary_oracle \
  experiments.hcsn_hx_unified_v3.test_piecewise_boundary_narrow_switch_gate
python -m compileall -q experiments/hcsn_hx_unified_v3/piecewise_boundary_oracle.py \
  experiments/hcsn_hx_unified_v3/test_piecewise_boundary_narrow_switch_gate.py
```

The exact remote source blob is `9f7e85bd951a877048456a486ba429b4cdee50c6`, matching the locally tested source. Focused reference tests only; no Rust/GPU, multimodal, training, P1, P2, or production admission evidence.

## Still open

- Very small positive first-leg hitting weight with `q>0` can remain unresolved in the **upstream linear first-hit F/G** at insufficient precision; the new regression explicitly verifies strict refusal for `switch=1e-80,dps=60` and does not bypass it.
- Near-saturated probabilities may still need an independent enclosure or precision-retry policy before certification.
- Nothing here establishes full HX analytic/QVI coherence, Call/Risk/Margin causal attribution, persistent continuous-event memory, four-modal effectiveness, or 4096-Cell native benchmarks.
