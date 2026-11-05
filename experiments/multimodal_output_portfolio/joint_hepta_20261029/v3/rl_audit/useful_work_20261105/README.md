# Executed structural critic roster — 2026-11-05

The unchanged source and protocol were frozen at
`9c6ad78bd6643185ab788b1a9a534450716747a5` (PR #4860). The complete default
roster has now run: **55 panel/fit-seed cases, 660 arm records, 645 complete,
15 expected unidentified zero-diffusion Z records, zero execution failures**.
The added post-execution verifier replays **61,440 fitted-model decisions** from
the retained parameters, without refitting, and recomputes raw decision metrics.
These are repeated decisions within a synthetic design, not 61,440 independent
learning samples. All existing negative real-generation and V3 results stand.
The panels reuse 640 distinct two-dimensional public state vectors and 640
four-dimensional vectors. These simulated vectors are not independent real tasks.

## What the experiment tells us

Each entry below is mean expected regret across the five registered fit seeds;
lower is better. Panels are separate designed scenarios, not IID observations.
All methods see the same noisy value stencil, with model information and action
fees as declared in [the original protocol](../STRUCTURE.md).

| Panel | Quadratic ridge value | Quadratic ridge gradient | Neural gradient |
| --- | ---: | ---: | ---: |
| Base | 0.000094 | 0.000049 | 0.000152 |
| High adjustment cost | 0.000047 | 0.000088 | 0.000110 |
| No complementarity | 0.000118 | 0.000125 | 0.000198 |
| Four dimensions | 0.000480 | 0.000432 | 0.000418 |
| Biased training model | 0.016789 | 0.013964 | 0.017018 |
| Large noise | 0.001852 | 0.001648 | 0.001227 |
| Small noise | 0.000135 | 0.000042 | 0.000057 |
| Zero noise | 0.000135 | 0.000042 | 0.000057 |
| Reset always succeeds | 0.000177 | 0.000067 | 0.000195 |
| Reset never succeeds | 0.000094 | 0.000049 | 0.000148 |
| Resource/residency restriction | 0.000065 | 0.000093 | 0.000084 |

The simple quadratic controls are already competitive. This result does not
justify dropping them for a neural critic. The misspecified simulator degrades
all these methods. At positive diffusion, every retained direct/Z decision pair
agrees: noiseless target rescaling supplied no extra information. At zero
diffusion the 15 Z records remain unidentified, with attempted computation costs.

Capacity and costs are **not matched**: in two dimensions these three arms have
6, 12 and 62 fitted parameters. The neural arm uses 160 Adam updates; the ridge
arms solve their registered regularized systems. Measured inference and training
times remain separate in `STRUCTURE_REPLAY.json`; this particular NumPy code can
make neural inference faster despite more expensive fitting. No universal speed
ranking or lifecycle break-even follows. CPU has no registered conversion into
the task's utility, so task fees are not full economic cost.

## Reproduce and check

Use Python 3.12 and NumPy 2.3.5. From a full checkout of this candidate:

```sh
python -m pip install numpy==2.3.5
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.test_structure experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.test_verify_structure
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.structure --out NEW_DIRECTORY
python -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("NEW_DIRECTORY/INDEX.json").read_bytes()).hexdigest())'
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.verify_structure NEW_DIRECTORY --index-sha256 HASH_FROM_PREVIOUS_COMMAND
```

Retain that index independently before verification. `STRUCTURE_INDEX.json` pins
the observed execution's 55 case files. It is losslessly minified for publication;
the original writer's `json.dumps(parsed, sort_keys=True, indent=2, allow_nan=False)`
plus a newline restores the original index bytes and SHA recorded in `RUN.json`.
Recomputation creates new timing values
and therefore new byte hashes. It does not reproduce old machine timing bytes.
The small published manifests and verifier suffice to regenerate the full raw
package; no large raw archive is required. `RUN.json` records the source,
environment, command envelope, inherited six-panel semantics result and checks.
The initial inherited-test attempt lacked an existing sparse-checkout dependency;
materializing `unified_20261028` restored all 42 original tests without edits.

The verifier is a post-execution audit. It is not another preregistered efficacy
test, an independent implementation of the learned predictor, or a prospective
model-selection procedure. It checks the retained checkpoint's own predictions,
the registered raw inputs, action roster, observations, costs and metrics. The
original tests additionally check the Gaussian formula by quadrature and the
critic derivatives by finite differences. Statistical benefit, production owner
integration and independent real future-window net gains remain unqualified.
