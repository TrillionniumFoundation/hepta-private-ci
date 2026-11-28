# A tonic-current extension with exact pricing and a separate physical drift

In the standard moving-grid cell, a new upper or lower boundary initially changes the firing flux. Once the boundary stops moving, the transition becomes identical across clamped current levels. With a fixed reset margin, the limiting firing rate therefore cannot represent the steady current. This does not prevent the prices or levels themselves from carrying steady information.

The public constructor `ContinuousSpikingNetwork(..., initial_physical_gain=0.15)` adds a signed, trainable gain in each unit of each physical layer. At drive u, the physical log drift is μfinancial−g tanh(u). Its absorption kernel and future physical hit probabilities use this drift. Equity and debt prices continue to use the financial pricing measure. Default construction omits the extra trainable parameter and strictly loads earlier checkpoints; the default had exactly the same outputs and derivatives in the regression. All trained gains remain interpretable as physical drift per unit of bounded input. Both the dense and FFT transport accept this option, independently of price caching.

| Clamped drive | Original stationary mass crossing per tick | Extended stationary mass crossing per tick | Unbounded continuous extended rate per model time |
|---:|---:|---:|---:|
| −2.0 | 0.00864335 | 0.00006460 | 0 |
| 0.0 | 0.00864335 | 0.00864335 | 0 |
| +0.5 | 0.00864335 | 0.03615879 | 0.11577 |
| +2.0 | 0.00864335 | 0.08188465 | 0.33882 |

The finite mesh has 12 atoms, a highest representative margin of 1.30 and step 0.25. Its top bin forces back escaped mass; it produces a small positive stationary flux for outward drift. The continuous unbounded process admits escape for positive drift and zero asymptotic firing for nonnegative drift. For inward drift its renewal rate is 1/(d+x_reset/|μphysical|). The finite transition's per-tick value and the analytic per-time value are on different time scales; the JSON also gives per-time finite-grid values. At the four currents the first-tick flux of the original model varied from 0.000000167 to 0.68754 despite the identical long-run rate. The relative reset convention and the fixed physical drift jointly produce this insensitivity.

Two-layer forward/gradient checks used 12/64 atoms, cache on/off, all input and parameter gradients and signed gain finite differences. Largest forward/state discrepancies between dense and FFT were 4.00e−15, all-gradient discrepancies below 2e−14. The four nonzero physical-gain gradients agreed with centered differences to about 1e−9. The test directly checked row mass conservation and the actual second recurrent step against its fixed-boundary Markov matrix. The physiological finite-window count comparison in the next folder is about a related renewal mechanism. Its cell fits do not imply that the new network has already learned cell-specific biological price channels. [Earlier tonic theorem](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fff9a90720deaf848ad30991158f2b6180e61f4f/qualification/hcsn_frontier_20261127/continuum/TONIC.md)
