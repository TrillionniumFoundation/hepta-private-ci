# Hand-only validation, 2026-10-24 UTC

Final code check: **12/12 tests PASS**, warnings treated as errors. All tests
use deterministic arithmetic tensors or a fixed randomly initialized source
model; no Fashion data was opened/downloaded, no real TRAIN or parameter sweep
ran, and no empirical quality/training/budget advantage is claimed.

## Retained execution history

| Attempt | Tests | Result | Child CPU | Peak RSS | Reason |
|---|---:|---|---:|---:|---|
| hand-01 | 11 | PASS | 0.261805 s | 44,195,840 bytes | Initial integration suite |
| hand-02 | 12 | PASS | 0.274008 s | 44,236,800 bytes | Added independent 40-outcome enumeration |

Both attempts and their per-source hashes/stdout/stderr are retained under
[evidence](evidence/); no failed attempt was removed. Cumulative test-child CPU
is 0.535813 s. These are verification-resource receipts, NOT benchmark evidence.
Both commands held the shared exclusive benchmark lock and set OpenBLAS/OMP/MKL
to one thread. Each child had hard 60 CPU-second and 256 MiB address-space
limits. Tests used dot's current execution environment only; no cloud CPU was
added to or compared with these receipts.

## What the checks establish

- H, A and N values/gradients match the fixed source objective, then each
  complete Adam chain updates real model parameters and distinct optimizer state.
- Independent enumeration of the 10 x 4 outcomes reproduces the declared
  per-row auxiliary laws and N <= A reward bound.
- Common draws and whole-request weights propagate into all terms. Explicit
  denominator scaling is checked against independently weighted single rows.
- For every objective, encoder, qT/qI, feedback and both heads have nonzero
  parameter gradients consistent with fixed directional finite differences.
- Saturated target probability retains its small complement gradient.
- Serving exposes no label/reference/draw/weight channel, and returns identical
  outputs when those offline inputs change; actual greedy/mean outputs differ
  from the auxiliary law in both wrong-class and accurate-mean fixtures.
- Missing/mismatched H/A/N opportunities, mixed-executor costs and selected
  claim families fail closed. Shared costs charge every consumer in full;
  actual overruns stay in the ledger and invalidate comparison eligibility.

These checks do not prove empirical false-positive rates, independent training
replication, wire-format behavior, every clipping-boundary derivative, or a
complete real budget instrument. Existing 140 terminal-reference checks were
not rerun. There is no new real-data launcher.

All new Python files also passed AST parsing. `git diff --check` passed.
Repository `just fmt` could not run because this checkout has no `codex-rs`
directory (and no `just` executable); no Rust files changed. The full repository
suite was not run. Real-data confirmation remains subject to PROSPECTIVE.md.
