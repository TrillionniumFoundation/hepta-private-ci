# R14 — certified two-step nonzero-risk NDU forward Stem

Exact finite 40-leaf law, two shared forward weights, stochastic preference transitions at both stages, two nonzero risks and nested entropic backward recursion. Proof and implementation are additive research materials; no runtime or production authority is changed.

Run from this directory using Python 3.13, numpy 2.3.5, scipy 1.17.0, mpmath 1.3.0:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest -v test_certified
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python certificate.py > CERTIFICATE.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python sweep.py sweep --out /fresh/output/runs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python audit.py --source . --runs /fresh/output/runs --out /fresh/output/verified
NDU_R14_RUNS=/fresh/output/runs python -m unittest -v test_tamper
```

The exact certificate is authoritative only for the enumerated law. See `PROOF.md`, `RESULTS.md` and `PROTOCOL.md`. Whole-process CPU/wall (including imports) are separate from fit-only CPU time. Strong L-BFGS results and the continuous-input negative transfer are not excluded. The raw run packet includes every fit, monitoring history, initial/selected weight, audit record and test log.