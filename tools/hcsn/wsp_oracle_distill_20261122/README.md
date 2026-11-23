# Bellman score distillation on five renewal-policy checkpoints

This experiment measures a shared-readout repair on actual `85 → 48 → 4` policy checkpoints. In the earlier value study both optimizer families selected KEEP. The question here is whether fitting absolute Bellman scores from multiple worlds jointly can fix hard-policy quality. The operational decision remains KEEP.

## Experiment

* The 160 source graphs, five design matrices and five original checkpoints are bound to the fixed input protocol in PR #6956, at commit `def96748960a30eaf917bd43a368cfddddfd547f`. The matrices represent 32 training worlds per checkpoint.
* The three continuation rows predict the corresponding legal own-law optimal Q scores. The Belief row predicts the logit of the own-law deadline posterior, clipped to [0.0001, 0.9999]. Each readout averages squared error equally over its eligible worlds and then states. A ridge term of 0.01 penalizes squared displacement from the original head.
* The shared head contains 196 parameters. The Euclidean radius is half the norm of the three original Q rows, with a relative inward margin of 1e-12 for floating-point encoding. DIRECT uses eigendecomposition with a common trust-region multiplier. The gradient control uses 128 full-batch projected steps, with the reciprocal of the common gradient Lipschitz bound as its step size. Both reuse identical sufficient statistics. This compares solution methods for the same fixed-feature distillation objective. It includes neither ordinary full-network training nor financial outcomes.
* Before drawing entropy the run sealed all five sets of candidate weights. Each checkpoint received 16 IID and 16 OOD worlds from the parent's public schedule generator. All 160 schedules differ from the 3,956 historical exclusions. There was no score-based selection or repeat draw. Deployment evaluation uses complete hard-policy DP including terminal payoffs and continuation fees. A world loss exceeding 0.05 excludes the candidate under the study rule.
* Q-only and B-only keep the corresponding rows of the direct edit. Half-dose, sign-reversed and one matched-norm random direction per checkpoint, and a fresh solve after within-world/row target permutation provide controls. Two additional interventions zero only the 33 input masses or the nine renewal forecast entries on the original model. Zero can be out of distribution. These interventions measure dependence on that feature group.

## Results

| Arm | Mean IID utility | IID change | Mean OOD utility | OOD change |
| --- | ---: | ---: | ---: | ---: |
| Original | 0.202528 | 0 | 0.117413 | 0 |
| DIRECT | 0.165334 | -0.037194 | 0.066343 | -0.051070 |
| Projected gradient | 0.161758 | -0.040770 | 0.054557 | -0.062856 |
| Q only | 0.165874 | -0.036654 | 0.085107 | -0.032306 |
| Belief only | 0.202389 | -0.000139 | 0.100915 | -0.016498 |
| Half dose | 0.208042 | +0.005514 | 0.094574 | -0.022839 |
| Reversed | 0.128463 | -0.074065 | 0.079550 | -0.037863 |
| Matched-norm random | 0.080771 | -0.121757 | 0.020341 | -0.097072 |
| Shuffled targets | 0.128279 | -0.074249 | 0.066307 | -0.051106 |
| Zero forecast bank | -0.008631 | -0.211159 | -0.032196 | -0.149609 |
| Zero latent masses | 0.196828 | -0.005700 | 0.083293 | -0.034120 |

The original, DIRECT and gradient mean training objectives were 0.026733, 0.017136 and 0.017735. DIRECT lowered hard-policy mean utility for each checkpoint in both domains. Twenty IID and 23 OOD worlds exceeded the loss limit for DIRECT, versus 23 and 26 for projected gradient. All five checkpoints violated the limit in each domain for both methods. DIRECT minus gradient averaged +0.003576 IID and +0.011786 OOD. Two-sided paired sign-flips across five checkpoint differences give 0.8125 and 0.4375 under sign symmetry. Five fits give limited precision.

The main job used 45.027 CPU seconds and 45.296 wall seconds for 75,336 states and 1,760 candidate policy DPs over 160 complete worlds. The independent forward expected-payoff calculation took 37.002 CPU seconds. Its maximum value difference was 3.89e-16. Both readers share the pinned graph and feature builders. DIRECT's maximum stationarity residual was 2.16e-16. Measured solver time excludes historical graph/feature preparation and program discovery. The five direct eigensolves took 0.0105 CPU seconds; the 640 total gradient steps took 0.0119 seconds after a shared 0.1308 seconds for sufficient statistics. These single small timings do not establish a hardware-independent speedup.

## Reproduce

Use a checkout containing the PR #6956 commit, the private `Hepta_WSP_Next_20261122_Evidence.zip`, Python 3.11+ and NumPy (recorded version 2.3.5). Use a new output directory. On a POSIX shell, from this module:

```bash
python prepare.py /path/to/Hepta_WSP_Next_20261122_Evidence.zip /path/to/hepta-private-ci
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python -B experiment.py output --replay-entropy records/ENTROPY.json
python -B verify.py output
python summarize.py output
```

A new entropy draw constitutes a separate experiment. Different math libraries or dispatch may change candidate bytes and therefore the seed derived from the model seal. For recorded replay compare the model seal first. `records/ORIGINAL_RECORD_PINS.json` contains the hashes of the original full records. `WORLD_RESULTS.json` holds per-world scores in the private evidence package. Research checkpoint bytes are supplied by their owner.

The independent fixed-point benchmark in `fixed_point/` applies an early-stop patch only to a private copy of the previous direct optimizer. The five parent checkpoints are distinct from Pocket4's trading adapter.
