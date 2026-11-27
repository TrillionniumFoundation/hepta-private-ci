# R19 rigorous nonquotient forward Stem — reproducible research

Parent is R18 exact commit `02c2bd45592dbe4c4156cd08fb52f58811336f1a`. The R19 protocol was actually pushed before efficacy at `dfc8a50c329c75266ab3251f6040326f4e68ba62`.

This folder contains **byte-exact executed** `model.py`, `fitters.py`, `run.py`, `global_bound.py`, `test_math.py`, and independent `audit/verify.py` and `audit/test_tamper.py`. The unchanged R18 `../asymmetric_2d/problem.py` and `../asymmetric_2d/certificate.py` are required, and are present on the parent branch.

Python 3.13, NumPy 2.3.5, SciPy 1.17.0; set `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OMP_NUM_THREADS=1`.

```bash
cd codex-rs/hepta-ndu/research/native_stem_abcd/nonquotient_bnb
python -m unittest -v test_math
python global_bound.py --out /tmp/R19_CERTIFICATE.json --frontier /tmp/R19_FRONTIER.jsonl
python run.py sweep --out /tmp/R19_NEW_RUNS
python audit/verify.py --source . --runs /tmp/R19_NEW_RUNS --proof /tmp/R19_CERTIFICATE.json --out /tmp/R19_VERIFIED
NDU_R19_SOURCE="$PWD" NDU_R19_RUNS=/tmp/R19_NEW_RUNS NDU_R19_PROOF=/tmp/R19_CERTIFICATE.json python -O audit/test_tamper.py
```

Run directories must not already exist. The nominal fit CPU cap per case is 0.75 seconds. Calls may exceed this while a non-preemptible solver operation completes; all elapsed CPU is recorded. The **global cost bound** is independent of the floating-point fit and applies on the entire real parameter space. The historical threshold `<0.001` is assigned after each fit is sealed, with a floating score guard. The optional 53-box tighter bound is never used to retrospectively change eligibility.

The archived conversation ZIP `hepta_native_ndu_nonquotient_round19_20261015.zip` contains 64 complete run directories, 4,298 checkpoint snapshots, failed and successful models, original errors, independent audit, box frontiers and manifest. A Git hash receipt is not the same as uploading binary weights into Git.

The model is a known finite-law, two-step, two-parameter positive-risk NDU research special case, not a deep neural world-model, general unknown-dynamics/global-FBSDE theorem, or production readiness claim. R18 main/CURRENT/native production contracts and historical failed blocking CI remain untouched.
