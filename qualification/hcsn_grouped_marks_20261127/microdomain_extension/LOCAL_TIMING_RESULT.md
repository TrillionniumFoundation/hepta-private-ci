# Equal-accuracy timing of local probability edits

All three solvers achieved the frozen probability-change target on every included row. The measured task inverts a **known local target** in a fixed, zero-drift, independent two-path law, then applies a minimum-covariance-cost update to that row of weights. Each row has one independent key and 64 weights. The diagonal covariance and all key directions were prepared once for all solvers. The clock includes target inversion, the common row update and a final error calculation.

| Independent rows | Solver | Median ms | 10th–90th percentile ms | Solver observations | Max probability error |
|---:|---|---:|---|---:|---:|
| 1 | autodiff_newton | 5.9783 | 1.8353–6.5348 | 10 | 6.98e-15 |
| 1 | bisection | 1.4363 | 1.2441–5.8112 | 33 | 5.54e-12 |
| 1 | closed | 0.1307 | 0.1138–0.2501 | 1 | 0.00e+00 |
| 1,024 | autodiff_newton | 8.0427 | 3.8010–14.4118 | 13 | 9.81e-12 |
| 1,024 | bisection | 7.1825 | 2.7680–10.7800 | 41 | 1.00e-11 |
| 1,024 | closed | 0.4320 | 0.3624–0.5788 | 1 | 3.00e-15 |

The machine reported INTEL(R) XEON(R) PLATINUM 8573C and PyTorch 2.8.0+cpu. Each method used one CPU thread, three warmups and 31 randomized-order observations. Other jobs could share the machine; the empirical timing spread is reported. Each iterative solver checked the same 1e−11 probability tolerance and stopped at its first qualifying full-batch observation. With one row the matched median cost ratios of bisection and autodiff Newton to the closed expression were 10.99 and 45.75. With 1,024 independent rows they were 16.62 and 18.62. The ratios use the quotient of observed medians. Batch timing measures an entire vectorized batch.

The saving shown here comes from an analytic inverse on a specified local task. These measurements exclude representation training, obtaining target probabilities from semantic supervision, constructing empirical covariances, shared-key conflicts and evaluation on new data. They supply no whole-network training-time measurement. A nonzero-drift unit requires a different inverse or a numerical solve. The prior registration and both vectorized implementations are at db895c43013359f5131df03df5a6883b3a6a16d9. Raw observations and cost and residual checks are in `local_timing.json`.
