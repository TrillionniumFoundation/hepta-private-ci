# First Codex Cloud execution: 2026-10-23 r1

**Outcome: the frozen finite-scene first-goal gates passed on the first and only held-out evaluation.** The exact runner returned 0. This does not establish natural-image, general NDU/FBSDE, synchronous audio/video, or long-horizon capability.

## Execution identity

- Configured environment returned `ready` before any execution; the enclosing Codex task log is the execution-location evidence. `execution-context.json` records the supplied environment ID, actual paths, commands and startup checks.
- Repository: `https://github.com/TrillionniumFoundation/hepta-private-ci.git`; execution directory: `/workspace/hepta-private-ci/qualification/joint-generation`.
- Branch: `codex/joint-generation-prototype-20261023`; execution source: `57d2c7aa5880dd761b4c43f79d0f6f16b26b72e7`.
- The complete source history includes `45505fd0a1` (tensor/utility), `81879d802f` (training/control), and `57d2c7aa58` (evaluation/serving/runner). No stage was cherry-picked or replaced by main.
- Python 3.12.14; NumPy 2.3.5; Pillow 12.3.0; Git 2.52.0; gh 2.46.0; CPU, observed OpenBLAS single thread. Both pinned dependencies were already installed.
- Repository `AGENTS.md` was read. Repository `.agents/skills` is absent and `/workspace/.agents` is empty.
- Before execution, a workspace search found no `selection.json`, `test-opened.json` or `cloud-run.json`, and the requested run directory did not exist. No earlier scratch preparation result was counted.

## Exact run and one-shot state

```bash
cd /workspace/hepta-private-ci/qualification/joint-generation
python cloud_run.py --out runs/codex-cloud-20261023-r1
```

The runner executed `python -W error -m unittest discover -p test_*.py -v`, `python train.py --out ABSOLUTE_RUN`, and `python evaluate.py --run ABSOLUTE_RUN` in order with BLAS/OMP/MKL thread counts set to 1. All three exit codes are 0; 30 tests passed. Runner wall time: 20.978537 seconds; training/selection lifecycle: 17.048075 seconds.

The train/validation/test row counts are 1,560 / 516 / 516, with 260 / 86 / 86 disjoint source groups. The retained manifests bind input and group hashes. Validation alone selected learning rate 0.01 for each arm across the three declared seeds (11, 23, 47).

**`test-opened.json` is final and must remain retained. Do not rerun this held-out split, including under a different directory.** `selection.json.test_opened=false` is the immutable pre-opening snapshot; the exclusive opening marker and `test-result.json` establish that the split is now opened. No training, plan, source, utility, or acceptance threshold was changed after viewing the result.

## Decoded-output benefit

The primary law samples independent text and image categorical heads. The following are exact expectations under that finite sampling law, scored from generated words and learned RGB pixels. Intervals are the frozen 2,000-replicate paired crossed seed/source-group bootstrap, including all three seeds and all 86 held-out groups.

| Comparison | Utility delta [95% CI] | Joint-success delta [95% CI] |
| --- | --- | --- |
| NDU minus supervised, always full | +0.020926 [+0.011638, +0.032925] | +0.021610 [+0.011700, +0.034267] |
| NDU minus additive, always full | +0.007661 [+0.003074, +0.013764] | +0.007981 [+0.003100, +0.014428] |
| NDU dynamic minus same-content matched random | +0.043656 [+0.021470, +0.070240] | +0.046856 [+0.022983, +0.075386] |

Content benefit and dynamic benefit both pass. Content is tested at identical full-input inference work, separately from routing. Dynamic control is tested on the identical NDU content model with identical forward count and critic work; it is not substituted for content benefit.

| Arm | Seed | Full utility | Full joint success | Full greedy joint success | Dynamic utility | Corrupt-decoder utility drop |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| supervised | 11 | 0.907759 | 0.902610 | 0.943798 | 0.912043 | 0.913516 |
| supervised | 23 | 0.934538 | 0.930736 | 0.968992 | 0.936858 | 0.936793 |
| supervised | 47 | 0.917179 | 0.912118 | 0.953488 | 0.919022 | 0.922423 |
| additive | 11 | 0.920431 | 0.915259 | 0.953488 | 0.923889 | 0.927031 |
| additive | 23 | 0.944597 | 0.941144 | 0.967054 | 0.947153 | 0.945785 |
| additive | 47 | 0.934246 | 0.929949 | 0.963178 | 0.935535 | 0.938246 |
| ndu | 11 | 0.931089 | 0.926433 | 0.953488 | 0.934754 | 0.936235 |
| ndu | 23 | 0.948582 | 0.945232 | 0.967054 | 0.950459 | 0.949802 |
| ndu | 47 | 0.942585 | 0.938630 | 0.963178 | 0.944076 | 0.945630 |

All nine selected models changed their shared encoder and both content heads relative to their hash-verified shared base. The learned decoder remained fixed during continued training, and the external utility definition was fixed. Parameter deltas are retained in `receipt-verification.json`. These checks support actual content training within this finite vocabulary; a score increase alone is not the evidence.

Maximum per-seed greedy joint-success drop versus either comparator is 0.001937984, below the frozen 0.02 bound. Greedy accuracy improvement is **not** established: its content-comparison confidence intervals include zero. Every decoder-corruption control reduced decoded utility; reload identities passed for all nine bundles; budget violations are zero.

## Full lifecycle cost coverage

Shared initialization was performed once for each seed and reused identically by all three arms. Across the three bases it included 900 decoder updates, 1,500 supervised pretraining updates, 96,000 pretraining examples, and 1,548 base-validation forward rows. Per-seed hashes, decoder errors and measured times remain in `selection.json` and `lifecycle-cost.json`. Shared costs must also be included if an arm is reproduced independently.

| Work across all three seeds | Supervised | Additive | NDU |
| --- | ---: | ---: | ---: |
| Searched candidates | 9 | 9 | 9 |
| Continued-training updates | 2,700 | 2,700 | 2,700 |
| Continued-training examples | 172,800 | 172,800 | 172,800 |
| Continued-training model MAC estimate | 3,881,779,200 | 3,881,779,200 | 3,881,779,200 |
| Both joint-utility diagnostic cells | 49,766,400 | 49,766,400 | 49,766,400 |
| Candidate-validation forward rows | 4,644 | 4,644 | 4,644 |
| Controller fits, each with 31 ridge features | 3 | 3 | 3 |
| Controller-fitting model forward rows | 9,360 | 9,360 | 9,360 |
| Controller-fitting outcome cells | 1,347,840 | 1,347,840 | 1,347,840 |

Each selected candidate itself uses 300 continued-training updates, 19,200 examples, 431,308,800 model MAC estimates and 5,529,600 joint-utility cells. All learning rates, including unselected candidates, are retained rather than charged as free search.

| NDU seed | Dynamic forwards | Same-content random forwards | MACs each | Critic scalar operations each |
| --- | ---: | ---: | ---: | ---: |
| 11 | 713 | 713 | 5156416 | 169248 |
| 23 | 700 | 700 | 5062400 | 169248 |
| 47 | 752 | 752 | 5438464 | 169248 |

Critics also each perform 12,384 log evaluations and sort 12,384 items per seed. All held-out mode costs and measured p50/p95 latencies are retained in `lifecycle-cost.json`. Diagnostic evaluation workload differs across arms and is reported separately from the matched content and dynamic comparisons.

**Cost boundary:** matched declared work counts do not establish equal hardware latency, FLOPs or energy. Measured wall times differ. Scalar nonlinearities, serialization, Python overhead and ridge factorization are not fully represented by model MAC estimates; their geometry, call counts and measured times are retained. No hardware-cost or wall-time equality claim is made.

## Exported serving demonstration

- Used `bundles/ndu-11-0.01`, the first declared seed with its validation-selected rate, rather than choosing a seed from held-out performance.
- Hand-authored an external normalized 8x8 RGB red square and the instruction `blue / cross / right`. The request contains no target labels, and serving did not construct a dataset.
- Fixed sample seed 42 produced caption `blue cross right` and a real 8x8 PNG. Output is retained under `serving-demo/sample/` together with the hash-bound append-only checkpoint.
- The model chose one forward; generator cost 14,848 plus controller cost 328 = 15,176 declared compute units, and 107 output bytes, under budgets 100,000 and 4,096.
- A second independent CLI process reloaded the bundle and reproduced the same choices, PNG bytes and bundle identity. Both commands, exits and log hashes are in `serving-demo/receipt.json`.
- The actual cloud unit tests cover cancellation and restored terminal state, append-only delivery and byte bounds, compute charging and atomic rejection, budget-limited continuation, malformed labels, corrupt bundles and content replay. Their complete output is in `unit.log`.

This single example is a deployment-contract demonstration, not additional held-out evidence. Archived monotonic deadlines expire; any future serving request needs a fresh deadline. Do not invoke the experiment runner or evaluator to replay this example.

## Retained evidence and remaining limitations

- `cloud-run.json`, `selection.json`, `test-opened.json`, `test-result.json`, all three runner logs, all base/candidate arrays, and all nine exported bundles are retained. `artifacts.sha256` inventories every evidence file except itself, with an 8 MiB total bound checked before staging.
- `receipt-verification.json` verifies source bytes against the exact execution commit and checks selection/plan/result/log/artifact hashes without creating a dataset or rerunning training/evaluation.
- `execution-context.json` records startup evidence and the exact access failures. `gh api user` returned `Get "https://api.github.com/user": Forbidden`; `gh pr view 3451` returned `Post "https://api.github.com/graphql": Forbidden`. Those denied API actions were not retried. Git branch listing and fetching succeeded in this same environment. GitHub API account identity and PR metadata remain unverified.
- The frozen finite-scene acceptance has no remaining experimental gate failure. Full-modality interfaces retain explicit unsupported audio/video profiles; synchronous AV, long-term interaction, natural-image generalization and production integration were not run.
- No browser login, alternative environment, Actions execution, merge, deployment, or permission change was used. Evidence persistence is a later commit; it does not change the recorded execution source commit.

The next scientific step is a separately frozen extension with new acceptance criteria and untouched data. This opened test set must not become a tuning set.
