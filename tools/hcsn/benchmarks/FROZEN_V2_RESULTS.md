# Fixed v2 heads on the frozen text encoder

The v2 architecture was fixed for the synthetic repair experiment before text-head outcomes were examined. This experiment changes only the Head and reuses exactly the same frozen feature file and data splits as `encoder/run_heads.py`. No encoder weights, PCA fit, feature rows, labels or v1 head files were modified.

This is an exploratory architecture comparison on the same SST holdout already examined in the v1 experiment. Fixing the v2 design before observing text-head outcomes does not make this a new independent held-out dataset.

Feature SHA-256 before and after training: `970c2c56442dc7deaa0e1db98f78b12ab0254a5fae2d45923852055252286a8a`.

All runs use width 26, **6060 trainable parameters**, **78 persistent state scalars**, five paired seeds, 300 Adam updates, batch 32 and learning rate 0.003. Checkpoints are chosen only by minimum validation cross entropy every 50 steps. Ten checkpoints and their SHA-256 hashes are retained.

| Model | Test accuracy mean ± seed SD | Corrupted test mean ± seed SD | Mean ECE | Mean Brier | Legacy training-time diagnostic seconds |
|---|---:|---:|---:|---:|---:|
| hcsn v2 | 76.050 ± 1.421% | 75.725 ± 1.119% | 0.0436 | 0.3202 | 0.5927 |
| sigmoid v2 | 76.575 ± 0.556% | 75.925 ± 0.520% | 0.0499 | 0.3175 | 0.5755 |

The paired HCSN-minus-sigmoid difference is **-0.525 percentage points**; its nominal 95% t interval over five seed differences is [-2.336, +1.286] pp. The same held-out examples are shared across seeds, so this interval does not represent all data-sampling uncertainty.

**No put-specific advantage is established.** These results do not justify full-backbone or multimodal pretraining promotion. No text-specific tuning was performed to rescue a negative result.

The corruption protocol exactly matches v1: Gaussian feature noise with standard deviation 0.15 and 20% local-feature-block dropout. The final global-mean feature, which retains full-sentence information, is always kept. This is a perturbation of already-computed frozen features and does not demonstrate robustness to missing raw input or missing sentence tokens before encoder execution.

The legacy `warm_training_seconds` field excludes only the first update. Weakly typed scalar parameters can cause a second JIT compilation on a new signature; later seeds can reuse cached compilations. All training-time fields are reference diagnostics and cannot be interpreted as pure warm timings or a speed/energy comparison. Reported latency measures only Head logits after JIT warmup, excludes the encoder, and uses a shared CPU. Sequence-experiment evaluation latency also computes loss, accuracy and Brier score and is therefore not directly comparable. No energy advantage is claimed. Original source and raw JSON are preserved for provenance.

Reproduce with `python run_frozen_v2.py --features PATH_TO_FROZEN_FEATURES`. Raw results are in frozen_v2_results.json; checkpoints are in frozen_v2_checkpoints/. Feature generation and model/dataset provenance remain in the parent encoder directory.
