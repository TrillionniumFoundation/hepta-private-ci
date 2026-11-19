# HCSN P1: scalar log F/G Hessian correction, still HOLD_NO_GO

**Source parent:** Draft PR #6005 exact head `93b8b9175a9c40e2e50e438de35c099a3ea6d7b8`.
**Scope:** isolated P1 diagnostic repair only; no C2 relaunch, training, readout substitution, model adoption, P2--P5 scientific qualification, or source-history overwrite.

## Reproduced failure and change

The custom `_LogNormalCDF.backward` was annotated `@once_differentiable`.
First-order probability/log-risk and gradient checks were successful, but differentiating
that first-order result again produced **incorrect yet finite** volatility curvature.
For five predeclared discounted scalar fixtures, the old implementation failed **5 of
5 parameterized cases** inside one unittest (process exit 1). The scaled
`d²log(G)/d sigma²` errors included **27.327%, 23.883%, 20.802%, 33.332%,
and 0.8248%**; the RED log records the exact per-case diagnostics.

The repair removes only `@once_differentiable` and its unused import. The
existing first-order Mills-ratio formula consists of differentiable Torch operations,
so the second derivative now follows the backward graph instead of a disconnected
or misleading gradient path. The first-order formula and physical model are not changed.

The new test checks **eight scalar conditions**: negative, zero, and positive
drift; short intervals, near-boundary distances and rare log probabilities;
five discounted `G` cases and three `F` cases. For each case it checks
`d²log F/G / d sigma²` and `d²log F/G / (d mu d sigma)` against
80-digit mpmath differentiation of the reflection-formula reference.
**16 second-order comparisons** are measured in `HESSIAN-MEASUREMENTS.json`,
whose maximum scaled absolute difference is
**4.9261450690761e-11** with the new code. This is *not* a global Hessian
certificate; in extreme domains, second-order derivatives may still fail closed.

## Independent-read evidence and actual native regression

The original C2 job and historical outputs were not written or restarted.
Tests used desktop Python 3.12.3, Torch 2.8.0+cu128 with CPU FP64 tensors,
mpmath 1.3.0; the GitHub HCSN CI pins Torch 2.8.0+cpu, so only new-head
GitHub CI can establish hosted qualification.

- `RED.native.log`: old source, 1 unittest containing five failing
  parameterized cases, exit 1; 5/5 failures.
- `TRIAL.native.log`: repaired source, initial five fixed cases pass.
- `EXTENDED.native.log`: three new cases initially revealed an **audit-test
  indexing error**, three errors, exit 1; preserved unmodified as a development
  failure (not a production defect).
- `EXTENDED-GREEN.native.log`: corrected eight-case fixture, 1/1 test,
  8/8 cases, 16/16 Hessian comparisons, exit 0.
- `GREEN.native.log`: initial repaired full local suite, 96/96 PASS.
- `FINAL-GREEN.native.log`: final eight-case repaired full local
  suite, **96/96 PASS**, no failures, 0 skipped, exit 0.
- `NATIVE-QUALIFICATION.json` + `NATIVE-QUALIFICATION.log`: actual
  `run_qualification --threads 1`, **96/96 PASS**, exit 0.
- `audit_hessian.py`: executable independent high-precision measurement script;
  `HESSIAN-MEASUREMENTS.json`: full literal fixtures, numerical results,
  source/test/reference SHA-256, runtime, elapsed, error definition.
- `EVIDENCE-SHA256.json`: exact byte commitments for all listed raw inputs
  and logs and Git blob SHAs for changed implementation/test files.

These are sampled scalar numerical results, not measured post-training posterior
states, full train-visited numerical coverage, six C2 terminal results or independent
replay. **P0--P5 all remain HOLD_NO_GO.** Production adoption remains prohibited.

Run from repository root:
```bash
PYTHONPATH=. /home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python -m unittest discover -s qualification/hcsn_differentiable/tests -p 'test_*.py' -q
PYTHONPATH=. /home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python -m qualification.hcsn_differentiable.run_qualification --threads 1 --output /tmp/hcsn-r10-qualification.json
```
