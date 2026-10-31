# HCSN P0 actual CPU first-hit precision screen — 2026-10-31

Research only, **DENY_ALL / NO_GO**, stacked exactly on draft #4530 HEAD `81b944aa019801e51abf1211b6aa02108479776a`. This narrowly tests a *first-hit probability primitive*, not the HX financial equilibrium, bond price, financial PDE, or an admitted FP32/BF16 neuron kernel.

## Experiment
For log distance y>0, drift mu, diffusion sigma>0 and horizon T>0, independently integrate the Brownian downward first-hit time density using `mpmath` (70 decimal digits), and compare against a reflected-CDF expression evaluated with real `torch.float32` or `torch.bfloat16` CPU tensors (not just input quantization). An explicit requested tolerance returns `MEASURED_ONLY` on the bounded sampled cases or `REFUSE` for finite error exceeding the tolerance, nonfinite/out-of-probability results, unsupported dtype or invalid inputs. This is an **empirical** guard; the declared tolerance is not a certified roundoff or all-domain interval bound.

## Local execution and limits
`python -m unittest -v experiments.hcsn_hx_unified_v3.test_firsthit_precision_guard` — the three test methods passed locally on Python 3.13, NumPy 2.3.5, SciPy 1.17.0, mpmath 1.3.0 and CPU PyTorch 2.10.0. This check was first executed from a standalone local module with logically equivalent imports before remote publishing, not from a complete repository checkout. 8 dtype/regime comparisons plus an intentionally strict BF16 refusal and invalid input tests. No all-domain scan, CUDA, BF16 financial model, interval arithmetic, compiler instrumentation, energy or full-repo CI.

## Interpretation
A successful comparison in a small selected set **does not** close P0. Cross-regime stability, extreme near-default cancellation, actual debt/equity propagation, rigorous error budget, end-to-end implicit gradient and globally admissible coupled HX obstacle remain open. P1 signed-slope/cost matched causal superiority remains disproven/unestablished in preceding controlled studies. P2–P5 admission gates unchanged. Retain all negative results and `production_activation=false`, `all_scientific_blockers_closed=false`.
