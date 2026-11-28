# Full-data shared audio, visual and transcript decoder on physical hardware

The private Kaggle notebook and the native AMD run are separately identified. The frozen seed-137 comparison uses the full 7,442 CREMA-D examples, three conditional generation tasks and the original actor-disjoint splits. Each run compares the two-layer endogenous-boundary financial decoder to the closest-parameter two-layer causal scaled-dot-product attention decoder with common batches, shuffled ordinals and AdamW. There are 14,952 training, 3,441 development and 3,933 held conditional sequences. Each complete pass contains 200,672 supervised next-token targets, including end tokens. The sensory streams are low-bandwidth nibble codes and the natural words come from twelve scripted transcripts.

### Physical AMD Radeon 8060S Graphics

ROCm 7.15.26333, Torch 2.13.0+rocm10.0.0, one observed device, real device dot product 140. All data, parameters, optimization and loss were on GPU. Synchronization brackets each update. Both arms finish a full pass and sixty active optimizer seconds. Development mean over the three target-specific NLLs selects the 60-second checkpoint for both arms. The reported held measures are teacher-forced target-token NLL (nats). Original per-token arrays and checkpoints are archived.

| Arm | Parameters | One pass update time | Examples by 60 s | Targets by 60 s | Held visual | Held audio | Held text |
|---|---:|---:|---:|---:|---:|---:|---:|
| Financial boundary | 9,690 | 2.41308 s | 992,880 | 13,325,761 | 1.56662 | 1.84031 | .35196 |
| Matched causal SDPA | 9,810 | 1.28083 s | 907,680 | 12,181,975 | .97266 | 1.76517 | .31329 |

First-pass costs include startup under the fixed arm order. Their ordering differs from sustained example throughput. One seed and one integrated GPU cannot identify a universal speed or energy advantage. Both measured endpoint budgets allow backpropagation. The precomputed exact frozen contract tables handle the native Python environment lacking SciPy. The two cached arrays were bitwise equal to both corresponding buffers from the primary CPU seed-137 epoch-one financial and smooth checkpoints. Native timings exclude creation of those tables. The complete native script embeds the data and cache, and verifies their identities before training.

[Native result and device proof](native/result.json) · [Reassembly manifest for four exact original raw chunks](native/raw/manifest.json) · [Exact native program](native/task.py) · [Cache build and bitwise verification](native/build_native.py).

### Private Kaggle execution

T4 was requested by the HeptaRuntime router. Registered private notebook 148105349 version 1 reached COMPLETE, all three files including the manifest were collected, and the router closed the request as COLLECTED. The worker observed Torch 2.11.0+cpu, no CUDA devices, no nvidia-smi and no loadable libcuda.so.1. The CUDA-only worker therefore executed zero training updates. The 53-byte empty output archive and the original result are preserved. This is a completed diagnostic for that particular allocation. The AMD result above is from a separate physical host.

[Kaggle result](kaggle/result.json) · [Sanitized receipt](kaggle/receipt.json) · [Empty output archive](kaggle/raw.tar.gz) · [Exact private script served](kaggle/task.py) · [Data-preserving project packer](build.py) · [Worker](worker.py).
