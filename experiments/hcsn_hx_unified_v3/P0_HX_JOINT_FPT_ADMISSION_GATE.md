# HCSN P0: joint HX F/G first-passage ordering admission

**DRAFT · RESEARCH ONLY · DENY_ALL · all_blockers_closed=false · production_activation_allowed=false.**

## Exact inherited source and boundary

Parent is Draft PR #4457 at immutable HEAD `499b168ad3b7e9fa49854640c7903261fabb38c1` (its own parent is #4456 at `b07ece86fbfd8c718b184c53629d70105c7c389f`). The inherited `hx.py` blob SHA is `5ff9595c0ae1f12b562171697212a439a7354a1a`. This isolated follow-on modifies only the HX *offline reference* and adds a source-integration regression and this gate note. No main, deployed finance, native agent, authorization, GPU, training or admission policy changes.

## Reproduced bug

The original public F(tau), G_q(tau) and finite-maturity bond independently evaluate normal-CDF tails. Since q=rate+shock_intensity*sale_fraction >0, their joint mathematical constraint is `0 <= G <= F <= 1`. For legal near-boundary asset ratios, small residual difference is lost in f64 rounding: with rate=1.3090468849180657e-7, payout=.11176379671252477, volatility=.9066753141892397, maturity=.0002461050758857373, hazard=.0009457207995848884, asset=1.0000000000032205 and boundary=1, the inspected expressions under local Python 3.13.5/SciPy 1.17.0 returned F=0.9999999998213832 and G=0.9999999998213833 (G-F=one f64 ULP). That is an *invalid returned pair*, not a physical negative discount.

## Narrow fix

Single `_first_passage_factors(p,v,tau)` calculates the unchanged F/G formulae once and validates finite scaled inputs and `0<=G<=F<=1` **before exposing either factor or the bond price**. If unresolved, raise `ArithmeticError`; no clamping, epsilon tolerance, new financial model, or assumption that the rejected point is physically invalid. Keep default, zero maturity and exact hit endpoints intact. This has additional compute cost for single-F/single-G readouts; do not claim performance improvement.

## Actually executed evidence and limitations

- Local independent focused extraction of the inspected HX normal-tail expressions: **3/3 unittest methods PASS**, 0 skips. Reproduced the original +1-ULP witness and the guard's refusal. In 10,000 deterministic log-scaled draws, **9,534 accepted / 466 explicitly rejected**, without silently returning a pair violating the ordering; this distribution is a stress diagnostic, not a representative rejection-rate estimate.
- An added four-method **repository-integrating** unittest covers exact ordinary-formula equality, forced nonfinite/out-of-order tails, the real witness, default/zero-time/extreme-ratio endpoints.
- The focused expression probe is **not a byte-exact execution of this repository module**. The newly committed integration tests have not been executed against the full repository checkout or CI; no full-source-exact pass is claimed.

From an exact checkout, execute:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_joint_fpt_contract
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
```

## Still OPEN

P0: an independently certified interval/tail-first-passage oracle, full legal numerical domain, coupled global HX obstacle and positive-equity equilibrium, boundary gradients, true fp32/bf16/fp16 and degeneracy limits. Current denial is **not** a numerical interval proof and some mathematically valid cases are deliberately refused. P1: matched causal channel effect and non-negative frozen task outcomes; P2: physical repeat-event memory tasks; P3: genuinely paired four-modal encoders; P4: measured Rust/GPU 64–4096 Cell cost, energy/recovery; P5: matched full-budget backbone advantage. No production admission.
