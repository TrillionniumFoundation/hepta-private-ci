# Matrix-free free-boundary population transport

The HCSN population solver in `qualification/hcsn_continuous_20261127/core/population.py` at `b3fdc981568ab9ce122d2fb569372651e0b4b314` integrates an absorbing diffusion over a finite grid of live states and adds one refractory compartment. Its original implementation materializes a source-by-destination matrix per row for every step. This experiment replaces that calculation with two convolutions and two explicit endpoint corrections, while retaining the state variables, finite grid, transfer law and learned coefficients. Dense transport remains the default in the supplied opt-in patch.

## Derivation

For a row with atoms $g_i=g_0+ih$, the old minus new log barrier is $d$ and $x_i=g_i+d$. Only $x_i>0$ contributes to surviving mass. Write $s=\sigma\sqrt{\Delta t}$, $v=a\sigma^2\Delta t$, and $A(z)=\Phi((z+h/2)/s)-\Phi((z-h/2)/s)$. For finite-width interior bin $j$, its incoming mass is

$$
p'_j=\sum_{i:x_i>0}p_i A((j-i)h-d-v)
-\sum_{i:x_i>0}p_i e^{-2a x_i} A(2g_0+(j+i)h+d-v).
$$

The first sum depends on $j-i$. Reversing the reflected source sequence changes $j+i$ to a constant offset plus a difference of indices. Zero-padded real FFTs therefore compute both sums with $O(K\log K)$ arithmetic and $O(K)$ working storage per independent row. The first bin begins at zero, the last extends to infinity, and both are integrated directly. The hitting mass uses an independent closed-form CDF, and the caller re-injects last step's refractory mass. Each batch row and neuron can carry its own shift, mass and prices. There is no frequency cutoff or change in spatial resolution.

The construction assumes a uniform, positive one-dimensional grid, spatially homogeneous drift and diffusion within a step, and one common shift for all atoms of a row. The experiment uses the pinned financial law, with separate moderate negative-drift and zero-drift numerical checks. A shifted atom touching zero has a one-sided derivative. Roundoff, Gaussian tail cancellation and the placement of the small nonnegative clip can affect tiny bin masses. The original clips each source–destination entry, whereas this implementation clips the aggregated destination masses. Per-example analytic equivalence in real arithmetic does not imply bitwise equivalence in floating point. Larger negative drift and more extreme scales may require log-space or scaled-complementary-error-function evaluation.

## Measurements

The independent NumPy/SciPy study tests seven grid sizes, both distributed and one-atom initial populations, four boundary regimes (including exact contact and every atom stopped), three drift parameters and two floating-point precisions. These are 336 configurations, each with four rows. In FP64 the maximum single-step live-bin discrepancy was $8.89\times10^{-16}$, the first-hit discrepancy was zero, and total mass error was $2.00\times10^{-15}$. For five representative 60-step trajectories with regeneration and closed-loop moving barriers, maximum state discrepancy was $4.33\times10^{-15}$. A separate analytic derivative of Gaussian antiderivatives agreed with centered differences of the FFT solver to $1.41\times10^{-10}$ for the boundary shift. The full error matrix and alternating timing samples are in `transport_result.json`.

The separately hosted one-thread PyTorch CPU run compared both full two-layer implementations under identical weights, frames, and task loss for three interlayer port choices, two grid sizes (12, 64), and two dtypes, totalling 12 comparisons. All completed. FP64 maximum logit error was $1.78\times10^{-15}$ and maximum parameter-gradient error was $5.28\times10^{-16}$. FP32 errors were $8.05\times10^{-7}$ and $2.69\times10^{-7}$. Every trainable parameter and input frames were included. Eight rows and five alternating timing pairs yield the following median dense/FFT forward-plus-backward runtime ratios for just the transport kernel.

| Grid atoms | PyTorch CPU FP64 | PyTorch CPU FP32 |
|--:|--:|--:|
| 8 | 0.44 | 0.42 |
| 12 | 0.44 | 0.43 |
| 32 | 0.55 | 0.49 |
| 64 | 0.91 | 0.62 |
| 128 | 2.24 | 1.29 |
| 256 | 10.72 | 5.30 |
| 512 | 46.01 | 20.90 |

The default grid of 12 favors dense computation. The crossover in this PyTorch CPU experiment was between 64 and 128 atoms for both dtypes. Medium and large grids permit substantially cheaper exact propagation. This timing excludes feature extraction, the remaining financial and neural operations, the optimizer, and convergence to matched downstream quality. In a separate eight-row, 768-atom SciPy forward comparison on the local Linux host, peak process memory was 305,616 KiB (dense) and 47,676 KiB (FFT), including the interpreter. This is a measurement of the two standalone NumPy reference paths.

## Reproduction

Run `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validate_transport.py` for the NumPy/SciPy evidence. The Linux memory measurement reads process high-water marks. For native PyTorch, run `python qualify_native.py --core /path/to/pinned/core --device cpu --dtype float64 --output native64.json` and repeat with `--dtype float32`. The driver verifies the Git blob hashes of both upstream files before creating a private temporary copy and applying the opt-in patch. Use `--device cuda` for an independently provisioned GPU. The native CPU raw timing and gradient evidence is in `native_cpu_summary.json`.
