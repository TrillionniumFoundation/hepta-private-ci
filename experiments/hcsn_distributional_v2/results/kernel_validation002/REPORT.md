# Final retained-distribution kernel audit

**All 13 tests, independent Monte Carlo and spatial-reference checks passed.** This audit binds the fixed numerical configuration selected before formal content training. It does not assert a content-quality advantage or task Bellman optimality.

## Final source identity

| File | SHA-256 |
| --- | --- |
| `MATH.md` | `8c53b63974883a4a0dd8281a419c7a3764e9fa898a21a4f9c43c935f407cd2ef` |
| `distribution_kernel.py` | `f272aa0808c2d497d4647dfb46fdc261ee481522affe0963b957d13b94f7f752` |
| `kernel_tests.py` | `ac638cb5ea04183f702295707a26bd436f86475713c0d5d982b04a8d9301662d` |

## Mathematical and numerical result

The model retains active-cell and refractory-phase probabilities across observations. A changing boundary is remapped in physical coordinates; covered active mass fires immediately even at zero elapsed time. Existing refractory phases are preserved. J and G evaluate the same finite generator, including its actual Erlang discount and all future regenerative rewards. During refractory residence G equals forced continuation; the eligible intervention term remains separately exposed.

| Check | Result |
| --- | --- |
| Independent SciPy augmented exponential, maximum state L1 error | 3.67775e-13 |
| Independent SciPy augmented exponential, maximum repeat-count error | 2.29994e-12 |
| Independent dense policy solve, maximum J/G error | 5.55112e-16 |
| Fixed neural configuration, worst-domain state L1 / count error | 5.75096e-13 / 1.69526e-12 |
| Seven physical gradients, fixed configuration, maximum scaled FD error | 5.3859e-10 |
| Prepared versus sequential float64 probability / gradient difference | 2.55351e-15 / 5.74818e-14 |
| Independent 30,000-path finite CTMC event-count comparison | z = 0.692916 |
| Generic adaptive-reference 64-step float32 maximum mass error | 5.96046e-07 |

The dense propagation audit checks both state and event/reward errors against the stated Poisson bounds, with an explicit floating-point allowance. The finite-generator time-composition check is separate from physical boundary changes. A true boundary round trip can incur finite-volume projection error and is not asserted to be an identity.

## Causality defect found and repaired before registration

The initial adaptive implementation passed its scalar numerical tests, but selected a uniformization rate and series length from the whole parameter batch. In a batch containing time, changing a future suffix or another example could therefore change the numerical approximation of an otherwise identical prefix. The old source is retained under `../kernel_validation001/source/`, and the actual counterexample is `../kernel_validation001/CAUSALITY_DISCOVERY.json`.

In that counterexample the old prefix transition changed by **1.1920929e-7 in float32** and **2.2440938e-12 in float64**, while the prefix physical coefficients were unchanged. The old numerical rate changed from approximately 3.625 to 7.960 and its series length from 9 to 21. Its bounded error did not satisfy strict numerical noninterference.

The neural model now fixes **Lambda=8.1, K=21, one chunk**, with **physical dt <= .36**. The independently computed active gross-rate upper bound is **7.960162969669533** and the phase-rate upper bound is **6.666666666666667** for the registered neural domain. No rate/series/chunk choice depends on future or neighboring inputs. Durations/rates outside the contract or insufficient fixed terms raise an error, without adaptive fallback.

For both float32 and float64, changing the future suffix and other examples leaves all prefix transition, count, reward, J and G arrays **bitwise identical** in the specified perturbation test. Their derivatives with respect to forbidden inputs are **exactly zero**. This is a same-shape noninterference test; different batching/streaming arithmetic may still differ by ordinary floating-point roundoff and is checked independently at model level.

The generic adaptive mode remains available for scalar numerical references. It is not the neural model's registered propagation mode.

## Approximation limits remain visible

Eight cells and two phases are the finite physical model, not an exact unbounded Brownian path law or deterministic refractory delay. On the recorded independent zero-delay Brownian renewal case, count error was approximately **0.0240 at 8 cells**, **0.0291 at 16**, and **0.00575 at 128**. The first refinement was not monotone. The lower reflecting wall, spatial upwinding and boundary remapping have separate approximation effects.

The analytic Brownian/Erlang boundary is a structured choice of threshold. J/G evaluate that threshold's finite-generator policy; this audit does not certify that it optimizes the finite grid or the classification/owner task. Gradient tests are local, away from interpolation/overlap/drift knots. Analytic Poisson error bounds exclude floating-point roundoff and spatial/modeling error.

## Measured cost and local preparation probe

The full final verification child process consumed **5.216470 CPU seconds** and **5.264669 wall seconds**, with peak Linux RSS **284240 KiB**. These `os.wait4` costs include interpreter startup, imports, tests, Monte Carlo/reference checks and the synthetic probe. The analyzer-body time is a nested component. The earlier successful audit cost **4.996561 CPU seconds** and remains a separate cost; it is not erased by this repair.

The final local performance probe uses batch 8, sequence 16, four physical channels, eight cells, two phases and float32, under the fixed 8.1/21/one-chunk configuration. It measures **forward plus backward only**, with no optimizer update and no content task.

| Path | Three CPU measurements, ms | Median, ms |
| --- | --- | ---: |
| Sequential sparse step | 252.890, 234.361, 202.069 | 234.361 |
| Prepared basis operator | 40.153, 37.215, 36.958 | 37.215 |

The final median ratio is **6.297x**. The retained fixed-configuration development run measured **4.810x**, and the individual sequential timings vary. These local results do not establish an end-to-end training, GPU or energy advantage. Model-level runtime measurements and all complete training costs must be consulted separately.

`RESULTS.json` retains every parameter case, independent reference, finite-difference pair, solver certificate and repeated timing. `EXECUTION.json` binds the executed command and full process cost. The parent content study uses a separate source registration and does not overwrite this numerical audit.
