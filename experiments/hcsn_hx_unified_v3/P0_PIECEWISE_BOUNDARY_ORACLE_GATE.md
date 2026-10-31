# HCSN P0/P2: two-segment moving-boundary first-passage oracle

**DRAFT / RESEARCH ONLY / DENY_ALL.** `all_blockers_closed=false`; `production_activation_allowed=false`. Exact parent: `11bff8ddae1d05ade93cc07c78f04982f110fdb5` (PR #4475). Additive files only. No finance HX, QVI, training, authority, Rust/GPU, CI or production mutation.

## Mathematical scope

For frozen `X(t)=x+mu*t+sigma*W(t)` and a continuous lower boundary,

```
b(t) = b0 + c1*t                                   , 0 <= t <= s
     = b0 + c1*s + c2*(t-s)                      , s < t <= T
```

require `sigma>0`, `0<=s<=T`, `q>=0`, finite real inputs. An initial contact is a time-zero event. If `s=0`, `s=T` or `c1=c2`, reduce exactly to the parent linear oracle.

Let `a=x-b0>0`, `nu1=mu-c1`. The **absorbed** surviving-gap transition density at the switch is

```
k_s(a,y) = exp(nu1*(y-a)/sigma^2 - nu1^2*s/(2*sigma^2))
           * exp(-(y-a)^2/(2*sigma^2*s))
           * [-expm1(-2*a*y/(sigma^2*s))] / (sigma*sqrt(2*pi*s)), y>0.
```

The positive `-expm1` term preserves the absorbing reflection subtraction close to `y=0`; a free Gaussian would wrongly count already-fired and returned paths. By strong Markov conditioning (first event only), write `F1,G1` for the first segment and `F2(y),G2(y)` for the second segment begun at gap `y`:

```
F = F1(s) + integral_0^inf k_s(a,y) F2(y,T-s) dy
G = G1(s) + exp(-q*s) integral_0^inf k_s(a,y) G2(y,T-s) dy.
```

Quadrature retains the infinite upper limit; knots are placed near surviving Gaussian mass. Local quadrature nodes may have an under-resolved `F/G` ordering close to `y=0`; **no local clamping occurs**. Final `0<=G<=F<=1` and global slope-envelope constraints are strictly checked. This is a numerical reference, **not a certified directed-rounding interval**. Quadrature error has not been proven over all parameter scales.

## Reproduction, evidence and a real negative control

Python 3.13.5, mpmath 1.3.0, Linux CPU:

```
python -m unittest -v experiments.hcsn_hx_unified_v3.test_piecewise_boundary_oracle
python -m compileall -q experiments/hcsn_hx_unified_v3
```

**8/8 unittests PASS, zero skipped.** Test process wall ~6.29 seconds, maximum RSS 109584 KiB (not a native-neuron speed result). Checks: independent spatial killed-density survival normalization, switch endpoints/equal slopes, two opposed slope orders, zero discount, immediate event/zero window, strict invalid-input rejection, 50-vs-80-digit agreement and a frozen-average negative control.

| Frozen example | Exact two-segment F | G | Incorrect constant-average F |
|---|---:|---:|---:|
| `x=1,b0=0,mu=0,sigma=.4,c1=.8,c2=0,s=.5,T=1,q=.2` | .13034319097200746 | .11371219839348145 | .10133241778764334 |
| `x=1,b0=0,mu=0,sigma=.6,c1=-.2,c2=.7,s=.6,T=1.3,q=.3` | .24746785649216003 | .18520079098892171 | .28844690251302707 |

The first wrong-frozen/averaged approximation differs by ~0.02901 **absolute probability**, and the second by ~0.04098. Both are deterministic witness inputs; no claim about trained neural superiority.

A relevant mathematical comparison is Tamborrino (2016), *Approximation of the first passage time density of a Wiener process to an exponentially decaying boundary by two-piecewise linear threshold*, DOI 10.3934/mbe.2016011; these independently implemented tests do not claim to reproduce its experiments.

## Still blocked

Not a full HX endogenous financial smooth-fit/obstacle proof; no globally certified all-parameter FP32/FP16/bfloat16 intervals or gradients; no validated learned-boundary derivative certificate, multi-firing regenerative events or arbitrary curved boundary; no preregistered matched P1 ablation, P2 memory improvement, real P3 four-modal training, P4 64–4096 Cell Rust/GPU/energy/recovery or fixed-budget P5 wins. Main remains unchanged, and no full repository CI is claimed.
