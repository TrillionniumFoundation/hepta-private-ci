# P0: narrow second-leg transition must not vanish inside standardized quadrature

**DRAFT / RESEARCH-ONLY / DENY_ALL.** This is a scoped numerical oracle repair stacked on #4485 exact HEAD `766cacb71e98ed88dc79a659fdde24e731c3315e` (itself stacked on #4478); it must not be mistaken for an all-domain FP interval certificate, all-domain HX/QVI solution, a trained neural advantage, or production admission. Leave `all_blockers_closed=false` and `production_activation_allowed=false`.

## Independent mathematical witness

Let the gap be `Y(t)=1+0.5 W(t)` for `0<=t<=1`, with absorbing lower boundary `0`. The second leg lasts `eps=1e-40` and has boundary slope `c2=(1+0.5*z0)/eps`, with `z0` in `{0.7,1.7,2.35}`. Over that last leg the deterministic crossing is at the survived gap `y*=1+0.5*z0` and the stochastic transition width is `0.5*sqrt(eps)`. The fixed standardized quadrature panels of #4485 do not split at `z0` and therefore can misintegrate this near-step despite their Gaussian tail and probability-ordering checks.

An independent stopped-event reference uses the **analytic reflected killed Gaussian** first-leg endpoint CDF integrated on `[0,y*]`, plus the first-leg reflection hit probability. For discounted weight (`q=0.2`) it independently integrates the *time-domain* inverse-Gaussian first-hit density, then adds `exp(-q*T)` times killed endpoint mass. It does not call the candidate first-hit kernel for expected outputs.

For `K=16`, reflection + the Gaussian-density upper bound give the real-physical transition discrepancy:

```
abs(F_true - F_step) <= 2*K*sqrt(eps/1)/sqrt(2*pi)
                        + 2*erfc(K/sqrt(2))
abs(G_true - G_step) <= above + q*eps
```

The time-width `eps` is too small for the ordinary quadrature panels to track the second-leg CDF, but the bounds are explicit. Numerically for `eps=1e-40`, the first expression is approximately `1.2766e-19` (not a floating-point interval enclosure).

### Negative control on exact original #4485 source

Original Git blob `37c3f53602bbc1b18735a3f1ff6ccd3ae879b33e` from #4485 was independently reconstructed and verified with `git hash-object`. With `dps=50`, the unmodified source returned seemingly admissible probabilities with these *absolute F errors* against the independent step limit:

| Crossing `z0` | Original error | After split error (approx.) |
|---|---:|---:|
| 0.7 | `2.22336782995016e-4` | `1.47e-27` |
| 1.7 | `1.70518709117487e-4` | `6.07e-28` |
| 2.35 | `3.64683636013650e-5` | `1.91e-28` |

New negative-control regression tests produced **6 failing subtests** on original #4485, then passed after the patch.

## Repair and exact local evidence

- In `piecewise_boundary_oracle.py`, add the second-leg drift-only crossing `crossing_z = (-(mu-c2)*(T-switch)-mean_gap)/scale` to the existing Gaussian quadrature breakpoints, **only** if it lies in the bounded standardized integration window. Do not alter probability values, clip results, or weaken existing slope/discount gates.
- Python 3.13.5 / mpmath 1.3.0 / Linux CPU, with byte-exact restored parent source files and inherited tests (verified SHA-1s), all **23/23 focused tests passed**, zero skips: 11 moving-boundary, 8 piecewise, and 4 new tests including 6 independent physical-bound witnesses. `compileall` passed.
- Tested source Git blob: `86329bc47362a962a0580f3f6f220aeb9a1f60b6`. Tested new regression blob: `772f9958f0c9e1488ef2178aebb2956a8ad2f221`.
- The bound constrains physical small-time approximation, **not numerical integration error for arbitrary parameters**. The split is a targeted correction rather than a proof of global integration accuracy.

## Open and explicit non-claims

No global self-consistent financial HX equilibrium; no global regenerative QVI or f32/f16 certified intervals; no P1 statistically independent Call/Risk/Margin win; no P2 long-memory admission; no P3 four-modal encoder win; no P4 4096-Cell native throughput, energy or restart evidence; no P5 matched-budget advantage. **No merge into main or production activation.**
