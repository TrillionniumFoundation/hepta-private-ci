# P0 independent fixed-barrier put dual witness — 2026-10-31

**RESEARCH ONLY / DENY_ALL / NO_GO.** Precise observed protected main: `732e934ba496d90fbe042b8d41d479ef901643e5`. Stacked parent: Draft PR #4518, immutable HEAD `ee06b987eb408821cd8b7aba4c7969aa18e5e77f`. The three new implementation/test/replay files are isolated and do not change HX source, existing certificates, prior negative examples, Rust, GPU, CI or deployment admission.

## The narrow theorem established

For a fixed positive financial default barrier `b`, GBM `dA=(r-delta)A dt+sigma A dW`, starting `A=b exp(L)`, and **constant debt proxy** `B_inf=c/q + exp(-qT)(P/T-c/q)`, let `K=max(0,(C-B_inf)/r)`. The discounted first hit of any strictly feasible level `b<z<=A` is an admissible stopping time and supplies an *attainable* lower bound on the **isolated constant-bond perpetual-put optional-stopping premium**:

`(K-z)^+ exp[-gamma (L-log(z/b))]`,

where `gamma>0` is the positive r-harmonic downward-hit exponent. An independent upper bound uses the r-harmonic inequality with outward-rational `k=gamma_upper` and the explicit supremum over all `z>=b`. The source encloses square roots, logarithms, positive and negative exponentials with exact rational bracketing and 12-place outward final endpoints. The upper need not be attainable from the starting state; this can create a **large upper/lower gap** in adversarial regimes.

These are **not** certificates for the state-dependent original HX debt `B(A;b,T)`, true equity, global endogenous financial smooth-pasting, coupled obstacle decisions, any implicit neural gradient, or production.

## Independently executed CPU results

Python 3.13.5, mpmath 120 digits, local reconstructed field-compatible `HX` dataclass (not complete repository checkout). `python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_put_lower_witness`: **6/6 PASS, zero skips**, 7.358 seconds. Tests check two parameterized local scenarios, 120 stress-case feasible hits against independently evaluated 120-digit first-hit values, 120 analytic upper references, exact Taylor/atanh/sqrt brackets, refusal of invalid inputs and explicit `certify_p0()` failure. Reproducible runner generated a **122-row** canonical raw JSON panel.

| Case | Independent put lower | Independent put upper | Prior #4518 upper |
| --- | ---: | ---: | ---: |
| Standard, sale_fraction 0.015, barrier 64.62517667527493, L=3.6 | 0 | 0 | 0 |
| High liquidity, sale_fraction 0.2, barrier 101.32402860907811, L=3.6 | 2.619402148447 | 2.619402148455 | 2.619570396928 |

Both published fixed-barrier cases are now tight **for this isolated constant-bond premium only**. The 120 adversarial cases vary rate {0.03,0.05,0.09}, payout {0.015,0.06}, volatility {0.15,0.35}, barrier {30,55,80,105,130}, L {0.7,3.6}: **121 positive-premium rows, 1 zero row** over all 122; **largest unresolved dual gap = 3019.630905361584**, median dual gap approximately 1.45e-10. Keep this enormous negative witness; no universal tightness claim.

Raw lossless JSON SHA-256: `dff4d8450325520947d65b9145f93134270bf057248d9e0acdbf164f0569e172` (35,071 bytes). Source remote Git blob `0e4b348d262f10fa8ddbeb458a410b219af40909` and independent test blob `7ee3645888e1152b478afdebd17497d8b983c580` were read back from GitHub and matched local byte identities. Test log and raw panel are preserved in the accompanying run evidence archive; replay script is committed and creates outputs with `xb` to avoid silent overwrites.

Reproduction from repo root:

```bash
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_put_lower_witness
python -m experiments.hcsn_hx_unified_v3.run_hx_put_dual_panel --output /tmp/hcsn_unique_put_dual_122.json
sha256sum /tmp/hcsn_unique_put_dual_122.json
```

Local development had an early giant-rational **timeout** and an exponential-range refusal, corrected through explicitly outward rational quantization/segmentation; neither is counted as a pass. The above recorded targeted test is the successful rerun, **not** full repository/CI or independent remote reproduction.

## Still blocking strict HCSN admission

- **P0 OPEN:** the state-dependent finite-maturity debt PDE's global verified error (space/time/truncation/roundoff), financial free-boundary coupling, full continuum obstacle active set, low-precision and implicit-gradient error remain unproved. This result is not a substitute.
- **P1 OPEN:** independent equal-cost Call/Risk/Margin causal gain lacks acceptance; negative 12-seed #4517 is retained.
- **P2 OPEN:** true OOD Selective Copy/MQAR/overwrite and authentic host crash/recovery.
- **P3 OPEN:** robust four-modality real pretrained encoder and actor-disjoint generalization.
- **P4 OPEN:** Rust/GPU 64–4096 Cell throughput/p95/p99/RSS/joules and recovery.
- **P5 BLOCKED:** require all prior scientific gates before equal-budget scaling.

No thresholds relaxed; no production toggle; leave the PR Draft.