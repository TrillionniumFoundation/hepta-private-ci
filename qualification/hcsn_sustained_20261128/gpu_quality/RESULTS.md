# T4 time and board energy at the first 80% validation check

One private Colab allocation ran all eight fits and eight independent checkpoint evaluations on a Tesla T4 with Torch 2.14.1+cu130. The measured device performed the CUDA check with result 140. Four matched training pairs crossed the same prespecified balanced-accuracy threshold at the same update. Development cross-entropy differences were at most 7.78e-16. The maximum absolute difference across the scored raw held-out logits was 5.94e-15.

| Grid | Seed | First update | Held-out balanced accuracy both | Dense / FFT cold seconds to threshold | Dense / FFT board joules |
|---:|---:|---:|---:|---:|---:|
| 12 | 314 | 32 | .905405 | 18.465 / 18.949 | 527.170 / 520.267 |
| 12 | 159 | 24 | .986486 | 11.641 / 14.907 | 327.411 / 415.703 |
| 128 | 314 | 32 | .878378 | 13.495 / 18.849 | 506.036 / 539.057 |
| 128 | 159 | 24 | .986486 | 11.078 / 14.404 | 417.961 / 430.700 |

All four observed FFT fits took longer to reach matched quality on the T4. The NVML cumulative counter showed slightly lower FFT board energy in one pair and higher FFT board energy in the other three. Integrating contemporaneous power at about 5 Hz agreed on the direction in every pair. The separate pre-work idle check measured median 25.358 W. The energy interval includes the fresh child process, checkpoint write and exit. The threshold clock stops at the score computed by the training child. The 73 held-out images also appear in earlier CPU engineering work. This GPU test adds independent hardware evidence and shares its statistical cohort with the CPU result. A single GPU, two seeds and one run per arm cannot resolve small energy differences such as the first K=12 comparison.

The full worker took 164.29 s. The notebook source, identifier, device arithmetic, per-child observations, board-power traces, all-development-points and raw prediction-difference statistics are linked through the source and result manifest. Exact output SHA-256 is `012cc7fb6e3e1c53fd6f94c5f4e45e75cc37068dafec10233ae94ce459685078`, 69,501 bytes. Collection reported no missing artifact and released one owned runtime and one bound kernel in one release request.

The returned artifact retains the SHA of each checkpoint, the development history, independently loaded cold scores, the maximum paired logit error and the board traces. Individual checkpoint bytes and 73-by-2 logit arrays were compared in temporary storage on the GPU runtime and were discarded after the registered comparison. Re-executing `sealed.py` on a compatible T4 recreates the trial from the hashed dataset and code.
