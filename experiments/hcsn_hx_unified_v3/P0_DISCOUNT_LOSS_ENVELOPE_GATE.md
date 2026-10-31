# HCSN P0: stopped first-hit discount-loss physical envelope

**Draft / research only / DENY_ALL.** `all_blockers_closed=false`; `production_activation_allowed=false`. Strict parent: PR #4478, commit `dd0449834da8e354088d35752bc1d3946801d5f4`. Only research files in `experiments/hcsn_hx_unified_v3/` change; no main, trained model, Rust authority/runtime, GPU, CI/workflow or production change.

## Necessary physical relation

For `X(t)=x+mu*t+sigma*W(t)`, an initially positive distance `a=x-b>0`, `sigma>0`, `0<T<infinity`, finite deterministic lower barrier and `q>0`, let `tau` be the first hit. Then

```
F = P(tau <= T)
G = E[exp(-q*tau) * 1(tau <= T)]
D = F-G = E[(1-exp(-q*tau)) * 1(tau <= T)]
0 < D <= F * [-expm1(-q*T)]
```

The upper bound follows from `0<=tau<=T` on the hitting event. A strictly positive discount makes the stopped discount loss strictly positive in real arithmetic, provided the Brownian process starts off the barrier and T>0. An immediate time-zero hit `a<=0`, no time `T=0`, and `q=0` are legitimate equality cases and retain their prior behavior.

The original P0 linear and two-segment numerical oracles checked only `0<=G<=F<=1`. That accepts `D=0` for arbitrarily small positive q and may accept a spurious D far exceeding the maximum possible discount loss. Both numerical oracles now **reject** those unresolved cases with ArithmeticError. They do not clip, pretend to compute the missing loss, or loosen the real-number bound.

## Reproduced negative witnesses

On exact parent source at frozen Python 3.13.5 / mpmath 1.3.0:

- Linear: `x=1,b=0,mu=0,sigma=.6,c=0,T=1.3,q=1e-200,dps=65`. Old accepted `F=G`, although the strictly positive stopped discount loss is mandatory.
- Linear: identical physics, `q=1e-90,dps=65`. Old accepted an apparent `D~2.97e-67`, versus the strict upper bound of order `1e-90`; this is numerical significance loss, not physical amplification.
- Two-segment: `x=1,b=0,mu=0,sigma=.6,c1=-.2,c2=.7,s=.6,T=1.3,q=1e-90` or `1e-200,dps=50`. Old accepted `F=G` despite q>0. New path may fail at the linear first leg before the piecewise final check; both checks are conservative.

The new 7-method focused tests against **unchanged, exact-parent source blobs** gave **5 failing assertions/subtests**, as intended. Patched local exact-source tests: **26/26 pass, zero skipped** (11 existing linear, 8 existing two-segment, 7 new discount-loss methods), Python unittest process approximately 9.734 seconds on local CPU. The new direct piecewise regression injects paired quadrature outputs with F=G=0.25, satisfying the old physical ordering and global slope bracket; the patched final guard independently refuses it. Prior standalone 6/6 new-method pass preceded this seventh method. Existing test sources were reconstructed byte-for-byte, confirmed by their Git blob hashes.

### Executed source identities

- Original linear source blob: `f2f2f864188f6563d0033af998d7cdec7ab95b6d`; patched: `5c026d1626b97a0c06ad5fe86fa20628651e2cb8`.
- Original two-segment source blob: `2b8f117fb445b431ad4c027b1b71866c51fa3653`; patched: `65443676d823c25ef9d4cb352cba5cd1677989d7`.
- New test blob: `5faadd275f8dbe204996e9ae7be6c90c645042e8`.
- Existing unchanged linear test blob: `50fa3d457f368d449eaa6b187a43dfc9a87a80e9`, two-segment test blob `60ef6896eb673b31ef20731b7408b64fbdd027e9`.

Reproduce (at branch HEAD with `mpmath` installed):

```bash
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_moving_boundary_enclosure \
  experiments.hcsn_hx_unified_v3.test_piecewise_boundary_oracle \
  experiments.hcsn_hx_unified_v3.test_piecewise_discount_loss_gate
```

## Explicit unclosed blockers

This is a **necessary physical envelope**, not a certified interval enclosure for all floating-point inputs. The finite-precision calculation of F or G can still be inaccurate **inside** the admitted envelope; mpmath quadrature at extreme scales can fail independently. No full repository CI, self-consistent financial He–Xiong obstacle/QVI, global boundary gradient, FP32/BF16/GPU, P1 matched Call/Risk/Margin causal gains, P2 long-memory quality, P3 paired four-modal training, P4 64–4096 real native Cells/joules/recovery or P5 equal-compute backbone advantage was established by this change. Keep Draft / DENY_ALL.
