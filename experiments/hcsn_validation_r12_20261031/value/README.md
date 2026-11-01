# Deployed-value calibration on frozen HCSN content models

This additive experiment reuses all six ordinary/analytic width-16 models from
`hcsn_regeneration_content_20261031` at commit
`631d33ba7ee815ee48c017269033e94cb2bc107c`. The original 20 frozen source inputs and
all 60 primary candidate artifacts are verified against manifests freshly read
from that exact GitHub commit. The original model/controller hashes and source
binding remain mandatory. This experiment uses its own source/candidate freeze;
it does not bypass the old verification or label a refit as an old candidate.

## Change being evaluated

The old ridge learns optimal-continuation advantages. This study fits six fixed
rounds of actual-policy continuation advantages. Each round freezes the previous
policy, integrates all legal first actions, charges all downstream READ/SKIP
fees, and fits a new public-feature ridge. A quarter of each graph's head weight
is uniform over legal states; three quarters follows the previous policy's
occupancy. Immediate action fees and no-information SKIP endpoints are exact.

The unchanged content hidden state, model probabilities and public schedule are
the only policy inputs. The full-history Bayesian posterior is used only by
the offline reference. Initial STOP is legal before any observation.

One of rounds 1–6 is selected by exact mean return on four predefined development
configurations; ties keep the earliest. Eight different predefined configurations
are then evaluated once. All rounds and labels remain in evidence. The original
lightweight and Q* ridge are retained. A matched Q* refit uses the same expanded
training contexts, feature design and initial-lightweight weighting. Consequently
the comparison with the old ridge includes changed training coverage and known
cost structure, not only a change of Bellman target.

The primary factorial is ordinary/analytic crossed with original lightweight/
selected deployed-value control. With only three original fit seeds, reports
give all seed means and their observed range, without a broad significance claim.

## Actual intermediate-prefix verification

For each confirmation configuration, select root and one occupied prefix per
later nonterminal slot by the registered occupancy rule. At each selected prefix,
execute every legal first action, then follow each frozen controller. The original
executor rebuilds the prefix from raw observations, and all past fees are removed
when comparing suffix values. Independent label-conditioned lazy world enumeration
branches only when the real actor requests a not-yet-assigned raw observation;
unread future values are integrated out. It does not use Bellman edge probabilities.
Every completed conditional world, action trace, charge and identity is retained.

All-history exact Qpi calibration and regret are separate from this deterministic
sample of actual-execution prefixes. The source does not claim every occupied
prefix has been independently executed. No RECOVER or CONTINUE action is added.

## Reproduction

From the repository root, with NumPy 2.3.5 and SciPy 1.17.0 available:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_validation_r12_20261031.value.tests -v
```

The committed `SOURCE_FREEZE.json` must verify without changing frozen Python
sources. Do not regenerate or overwrite the original freeze to hide a mismatch.
Run fits into a new path under this namespace:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_validation_r12_20261031.value.run train \
  --out experiments/hcsn_validation_r12_20261031/value/evidence/reproduction_training
```

Freeze and publish the resulting `CANDIDATE_FREEZE.json` and all selected payloads
before a new confirmation. Then use another new directory:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_validation_r12_20261031.value.run evaluate \
  --fit experiments/hcsn_validation_r12_20261031/value/evidence/reproduction_training \
  --out experiments/hcsn_validation_r12_20261031/value/evidence/reproduction_confirmation
```

The runner checks every training artifact against the candidate manifest and
checks source hashes before and after execution. Raw logs are lossless gzip
parts smaller than 500,000 bytes. Interpreter startup and final receipt I/O are
outside internal phase clocks; the supplied outer process receipts include them.
CPU/wall, abstract task tariffs, numerical accuracy and scientific quality remain
distinct measurements. No GPU, energy, production or full financial-HX claim is made.
