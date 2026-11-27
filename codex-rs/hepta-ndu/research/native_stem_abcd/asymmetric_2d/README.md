# R18 research-only asymmetric two-dimensional risk-sensitive Stem

R18 is a genuinely **two-dimensional** convex quotient of a parameter-nonconvex, known-law two-step forward Stem with positive entropic risks. The full target includes an offset, deliberately breaking R17's symmetry. It is **not** a generic deep-network theorem.

The Git research directory `asymmetric_2d/` contains `PROTOCOL.md`, the self-contained rational proof code `certificate.py`, actual finite 16-leaf model `problem.py`, matched new-process optimizers `solver.py`, 64-case census `run.py`, 25 mathematical tests, an independent pure-Python evaluator `reference.py`, an audit and nine tamper checks, exact proof/report, and all final weight hex strings.

## Replicate with Python 3.13, numpy 2.3.5 and scipy 1.17.0

From the research directory:

```bash
python -m unittest -v test_math
python certificate.py
python -c 'from certificate import ablation_certificate; print(ablation_certificate())'
python run.py sweep --out /tmp/new-empty-R18-runs
python audit/verify.py --source . --runs /tmp/new-empty-R18-runs --out /tmp/new-empty-R18-audit
NDU_R18_RUNS=/tmp/new-empty-R18-runs NDU_R18_SOURCE=. python -m unittest discover -s audit -p test_tamper.py -v
```

**Do not reuse an existing output directory:** all run/manifest writes are create-only, and time-based optimizer schedules are non-bitwise reproducible across hosts. Audit the latest sealed run rather than comparing expected SHA of a different benchmark host. The exact mathematical certificate output must remain invariant for identical source and Python version.

The full conversation ZIP contains the 64 original raw process runs, 4,112 checkpoint records, complete independent audit output, both exact rational certificates, all test logs, original core source bytes and a SHA256 manifest. The Git `WEIGHTS_HEX.csv` preserves all final binary64 tensors, not just winners; local NPZ is still provided separately for convenience. R17's global blocking-ci failures are not waived, and R18 remains Draft. No production or CURRENT changes.
