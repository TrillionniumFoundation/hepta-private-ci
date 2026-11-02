# Independent fit review

`audit_fits.py` does not import the campaign, renewal evaluator, or count transformation helper. It uses `scipy.stats.invgauss.cdf`, constructs event-count probabilities by independent vector differences, and independently implements the two simplified count shapes.

All **189 training-grid NLL values and 9 validation NLL values** agree within the previously declared absolute `2e-8` audit tolerance. Maximum actual difference is **6.827871601444713e-14**. The declared winners are selected only by training NLL and grid tie order. Validation outcomes were retained rather than used to change the fitting choice.

| Seed | Shape | Selected drift multiplier | Validation NLL | Train labels with exactly zero predicted mass | Validation labels with exactly zero predicted mass |
| --- | --- | --- | --- | --- | --- |
| 91103 | full | 1.00 | 0.631553 | 0/512 | 0/128 |
| 91103 | mean two-point | 0.95 | 2.557787 | 42/512 | 10/128 |
| 91103 | single transition | 0.95 | 7.553499 | 111/512 | 34/128 |
| 91107 | full | 1.00 | 0.715663 | 0/512 | 0/128 |
| 91107 | mean two-point | 1.00 | 2.821337 | 28/512 | 11/128 |
| 91107 | single transition | 1.00 | 7.200107 | 94/512 | 32/128 |
| 91113 | full | 1.05 | 0.677837 | 0/512 | 0/128 |
| 91113 | mean two-point | 0.95 | 3.635508 | 39/512 | 15/128 |
| 91113 | single transition | 1.00 | 6.706478 | 136/512 | 30/128 |

The `1e-12` NLL floor assigns a finite numerical loss to impossible count labels. It is a declared loss convention, not an extension of model support. Consequently these two very restricted replacements cannot represent all sampled event counts after their single parameter is refitted. This establishes a count-likelihood limitation of those replacements in the registered finite model; it does not establish a necessary task-level utility gain for the complete mechanism, exclude richer ordinary alternatives, or qualify an analytic neural network.

The task comparison uses the same execution observation interface and controller for ordinary and analytic cores, but **training budgets and priors differ**: historical ordinary GRU/SSM fits each consumed 8,192 training and 1,024 validation labels; each new analytic calibration fit consumes 512 training and 128 validation labels and assumes the renewal law. It is not strict matched-training-information architecture admission. Refit-shape comparisons measure the difference between separately refitted model families, including the selected drift multiplier, rather than a fixed-weight single-shape intervention.
