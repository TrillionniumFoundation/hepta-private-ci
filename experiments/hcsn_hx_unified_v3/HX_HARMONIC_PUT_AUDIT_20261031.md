# P0: r-harmonic fixed-barrier optional-stop enclosure (2026-10-31)

**Research-only / DENY_ALL / NO_GO.** Exact parent: Draft PR #4516 HEAD be808f2a05ad6f3761e7b8d15c1792fcb958e3e6. Observed main: 732e934ba496d90fbe042b8d41d479ef901643e5. This increment adds four isolated research files only. No original HX equation, old scientific evidence, PDE, CI, Rust, GPU or deployment flag is changed.

## New mathematical scope

The old upper bound on the stockholder's optional-stopping put premium used 1/A, which required payout + volatility^2 <= 2*rate. Instead let the risk-neutral log drift be mu=rate-payout-volatility^2/2 and define gamma=mu/volatility^2+sqrt((mu/volatility^2)^2+2*rate/volatility^2). Then the stopped process exp(-rate*t)*(b/A_t)^gamma is a nonnegative martingale before absorption at fixed b. For all stopping times before absorption,

    E[exp(-rate*tau)*(K-A_tau)^+] <= exp(-gamma*L) * sup_{z>=b} (K-z)^+ * (z/b)^gamma.

Choose exact rational k >= gamma. The coefficient is upper-bounded by replacing gamma with k, and its maximizer is z*=max(b,k*K/(k+1)). The code uses exact Fractions, outward rounded 20-decimal intermediate bounds, exact integer-square-root enclosures, a rational atanh logarithm upper bound and finite positive-Taylor exponential intervals. The isolated put component also works for parameters where the old 1/A certificate correctly refuses.

The wrapper composes with #4516 without subtracting an upward-rounded put term as an exact number: if the old rounded upper is P, subtract only the rigorously lower P-1e-12, add the new outward upper, and retain the minimum with the unchanged original upper. The lower fixed-barrier equity bound is unchanged. This does not establish a coupled endogenous HX equilibrium or certify the Obstacle active set.

## Actual local execution

Python 3.13.5 CPU, NumPy/SciPy/mpmath. Newly added unit tests: **5/5 PASS, zero skips** (~14.4 sec), including independent 140-decimal mpmath analytic supremum checks for five HX parameter sets, exact log upper tests, explicit resource/domain refusals and financial feasible-policy enclosures. Two-case canonical panel regenerated exactly. A wider inherited+new test command was attempted, but it **timed out after 120 seconds** in a previously existing heavy staircase-refinement method; do not claim full combined PASS. Local reference HX source was reconstructed, not an exact complete repository checkout; no complete CI, GPU, hardware energy or formal peer verification is claimed.

Reproduction from repository root:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_harmonic_put
    python -m experiments.hcsn_hx_unified_v3.run_harmonic_put_panel
    sha256sum experiments/hcsn_hx_unified_v3/HX_HARMONIC_PUT_PANEL_20261031.json

Raw JSON SHA-256: 4337ed24b83eb1407ee529dd20eb839990fc925a4d20fc04ae866d37bcf6eb85.

| Sale fraction (L=3.6) | Old put upper | New put upper | Old equity absolute budget | New equity absolute budget |
|:--|--:|--:|--:|--:|
| 0.015 | 0 | 0 | 1.640608880050 | 1.640608880051 |
| 0.2 | 3.663960206662 | **2.619570396928** | 4.255687461278 | **3.465966337770** |

High-liquidity optional-stop premium upper bound improves by 28.50%, and final fixed-upper-bound absolute error improves by 18.56%; this is mathematical budget tightening, not predictive superiority. The high-liquidity extra-STOP financial counterexample remains negative. Nominal result is unchanged within a 1e-12 additional outward quantization.

Verified exact locally executed parent source blobs: #4516 occupation source 2f681a4ed733501f55108dd6adc83d5417aecae2; parent equity helper 69a73f2db466993df3cba0512cf1c9dffa307119. New source blob 841776eb5bd919e90421a9fdb395bf72d9326827, test blob 7fb53f77647b677a0c8f18efa3a621cc833edabb, reproducibility runner 1f9732c166185294f4db5bd2fc94d5ee5e7e17a2, JSON blob a66f260f3ed0384abf531cb83fbed633fac8d629. Validate newly uploaded blob identities before relying on this report.

## Strictly unclosed P0-P5 science gates

- **P0 OPEN**: endogenous financial liquidity/default fixed point, all-state continuum financial Obstacle, actual interior debt PDE/time/rounding error budgets, active-set/implicit gradients and physical low precision.
- **P1 OPEN**: preregistered causal Call/Risk/Margin gain versus matched ordinary control at identical full measured costs.
- **P2 OPEN**: timed trainable FIRE OOD Copy/MQAR/overwrite/long-range retrieval and real authenticated mid-action power-loss recovery.
- **P3 OPEN**: real four-modal Encoder and cross-modal independent evaluation.
- **P4 OPEN**: Rust/GPU 64/256/1024/4096 throughput, p95/p99, RSS, Joules and recovery.
- **P5 BLOCKED**: matched-budget hybrid expansion requires all previous science gates.

The fixed-barrier Dirichlet input alone does not supply the complete debt error to #4508. Preserve complete_debt_error_budget=false, global_equilibrium_certified=false, all_scientific_blockers_closed=false and production_activation=false. Keep the PR Draft, unmerged and non-production.
