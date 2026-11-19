# He–Xiong / HCSN free-boundary numerical reference

Source: ChatGPT Library `hepta_free_boundary_reference.py`, preserved byte-exact (SHA-256 `df6edc547fede8122167f6615db958a5e172eeba8b73c4d67042b09212cb0fc9`, Git blob `54e9e2440eb73399a95adf04d98674df68c191b3`).

Run from repository root: `python3 scripts/hcsn/hepta_free_boundary_reference.py` with Python 3.10+, NumPy and SciPy.

Executed in an independent Python environment on 2026-11-10 (NumPy 2.3.5 / SciPy 1.17.0): the script completed and returned `all_checks_pass=true` (72 finite-horizon quadrature cases and 24 infinite-horizon cases). Examples of absolute discrepancies: first-passage CDF versus integral `3.55e-14`, discounted CDF versus integral `3.53e-14`, HX equity ODE residual `6.23e-07`, debt PDE residual `8.33e-06`, all within their declared tolerances.

**Research-only/HOLD.** Scalar stationary FP64 first-passage and financial boundary reference, not trained neural behavior, not reset-neuron differentiation, not moving-boundary gradient proof, not HCSN network adoption, and not a speed or energy benchmark. No claims of universal numerical stability outside specified parameter ranges. Use independent extended-domain, FP32/autodiff, reset, recurrent and task-level tests before any neuronal runtime integration.
