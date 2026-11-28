# Affine pricing in the recurrent HCSN population

The optional `cache_prices=True` on `ContinuousSpikingNetwork` and `BoundaryPopulation` evaluates both fixed-grid price surfaces at two principal values once per layer per forward. Each recurrent update obtains the prices for its batch of time-varying principals by affine interpolation. Every subsequent forward rebuilds its two tables from the current grid, dtype, device and pricing module. Existing state dictionaries load with `strict=True`. The default continues to call the price model at each step. Independent callers of `step` also use that direct evaluation by default.

This implements a previously established property in the general two-layer entry point. At fixed log margin, fixed contract coefficients and fixed stationary maturity, the published barrier is affine in nominal principal. The terms of equity and the new-issue monetary deficit are each affine in that barrier and principal. Prior work proved the property and benchmarked a specialized FordA training procedure. The CREMA-D encoder also used fixed-grid affine slopes. Here both anchor calls stay in the PyTorch computation graph. Input-driven changes in the barrier displacement continue to affect transport and first-passage independently of the pricing path. The accelerated method assumes a pricing model affine in principal at fixed grid coordinates. Users who customize the price function to violate this property can use the default path.

[Prior derivation and FordA timing](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b3fdc981568ab9ce122d2fb569372651e0b4b314/qualification/hcsn_continuous_20261127/core/AFFINE.md)

## Reproduction

Use a work directory containing the supplied `validate_prices.py`, `time_steps.py`, patched `population.py`, matching `he_xiong.py`, `fft_transport.py` and the original `digits01.npz`. The hashes of these five model/data/validation inputs are in `cloud_inputs.json`. Both scripts require NumPy and PyTorch. Fixed grid sizes are 12 and 64. The dataset SHA is verified at run time. The timings below use a physical ai395 host with the CPU backend of PyTorch 2.13.0+rocm10.0.0, one intra-op/BLAS thread and hidden accelerators.

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" ROCR_VISIBLE_DEVICES="" python validate_prices.py --device cpu --output ai395_cpu.json
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" ROCR_VISIBLE_DEVICES="" python time_steps.py --output ai395_step.json
```

## CPU results

On two recurrent layers with five frames and both ports carrying the complete augmented message, 12 checks crossed float32/float64, both grid sizes and three execution variants. These variants used the original dense transport on the default and a nonuniform mesh, and the matrix-free transport on its supported uniform mesh. Each check loaded the direct model's state into the warmed cached model. The nonuniform case also differentiated the grid and confirmed that a further mesh modification changed the next forward without stale prices. Maximum FP64 differences for predictions and both layer states were 2.22e-15 and for the complete loss gradient 1.78e-14. FP32 maxima were 9.54e-7 and 5.73e-6. On the two isolated price surfaces the maximum FP64 derivative error for principal was 7.11e-15, for grid 4.48e-12 and for the registered spectral buffer 1.82e-12.

Separate timings used two width-3 layers, eight frames, batch eight and the priced inter-layer port. Three warm-up iterations per implementation preceded eleven interleaved forward and loss-backward steps. Median direct and cached timings were 19.93 and 14.48 ms at 12 atoms and 60.73 and 52.78 ms at 64 atoms. The median ratios were 1.377 and 1.151.

For the end-to-end test each model trained with 16 AdamW updates on real UCI optical digit images for classes 0 and 1. The stratified split had 229 training, 58 development and 73 held-out images. Each fit ran in a fresh physical-CPU process. Direct/cached execution order alternated across grid sizes and seeds. The first timing includes optimizer creation, dataset loading, training, five development passes and one held-out pass. The cold timing also includes the Python child process, imports and exit.

| Atoms | Seed | Direct/cached setup, fit, validation & test | Direct/cached cold wall | Cold seconds direct / cached | Held-out balanced accuracy |
|---:|---:|---:|---:|---:|---:|
| 12 | 314 | 1.245 | 1.106 | 3.422 / 3.093 | .5000 |
| 12 | 159 | 1.233 | 1.102 | 3.319 / 3.013 | .8108 |
| 64 | 314 | 1.172 | 1.138 | 5.160 / 4.535 | .5000 |
| 64 | 159 | 1.158 | 1.086 | 4.590 / 4.227 | .8108 |

The largest paired CE difference was 2.22e-16. The four held-out accuracies matched their direct controls exactly. Seed 314 stayed at chance. A speed difference for a fixed 16-update workload does not establish time to a pre-specified quality target. The timings describe this hardware and execution order. The two anchors add work to a single-step segment, so a general low-latency single-tick advantage remains unmeasured.

## GPU job definition

The separate T4 worker requests a verified CUDA T4, performs a CUDA dot product, checks the two-layer equivalence cases, trains the primary original/cached comparison on nonfinancial digits at seed 314 and includes a flattened-image linear classifier trained on the same schedule. The linear control has a shorter timing scope and is a quality control. `run_t4.py` and `make_cloud.py` generate the sealed offline source from the five hashed inputs. Run from the directory containing both helper files.

```sh
python make_cloud.py population.py he_xiong.py fft_transport.py digits01.npz sealed_t4.py
```
