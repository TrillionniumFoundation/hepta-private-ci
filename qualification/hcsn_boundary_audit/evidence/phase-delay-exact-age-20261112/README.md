# P1 exact-phase-age versus per-step reprojection diagnostic (HOLD)

This is an **independent deterministic-delay-only reference**, not an HCSN solver replacement. The experiment models eight uniform remaining-delay cells of width 1/40 seconds, a total time 1/50 seconds and an absorbing released-mass marker. It deliberately excludes diffusion, reset re-entry, content, reward, gradients, trained posteriors and continuum-value accuracy. All fractions and matrix compositions use Python stdlib `Fraction` without floating rounding.

## New exact observations

| Same total time, projected after each substep | Maximum phase-only TV vs single projection | Age-carry exact oracle TV |
| --- | ---: | ---: |
| n=2 | 0.320000000000 | 0 |
| n=4 | 0.390400000000 | 0 |
| n=8 | 0.417362480000 | 0 |
| n=16 | 0.429367015872 | 0 |
| n=32 | 0.435050247342 | 0 |

All phase-only rows conserve exactly unit mass. The largest row is source phase cell 1 (zero-based). The phase-only values agree closely with the existing #6090 observed refractory-row defects (0.32, 0.3904, 0.41736248, 0.429367015869, 0.435050247265). This explicitly demonstrates a **deterministic phase reprojection mechanism sufficient to generate most of those defects**, without implying the full stochastic/reset operator is fixed or uniquely attributed.

The age-carry control does not re-uniformize surviving mass after intermediate time steps. It carries the original source interval and accumulates exact elapsed time, projecting only once for display. For the examined fixed uniform source law it is path-independent by rational arithmetic; its zero error does **not** establish an implementable finite-state neural architecture for arbitrary trained distributions.

## Original native RED/GREEN

- Host: `heptaruntime desktop`, `/usr/bin/python3` 3.12.3, stdlib only, each run capped at 25% CPU, 2 GiB RAM and 90 seconds wall.
- Script source SHA-256: `86c353af842e19a6f7b1f6a15e00b99a2ac5b893e084dca21441a44baf40886b`; original source bytes retained in `qualification/hcsn_boundary_audit/test_phase_delay_oracle.py`.
- RED job `1a1ce038a30-2564-144c`, exit **1**: explicitly false hypothesis that substepping by n=32 halves the n=2 TV was actually rejected. See `RED.stdout` and `RED.stderr`.
- GREEN job `1a1ce03c6b2-2564-144e`, exit **0**, **4/4 tests passed**, 0 failures/errors/skips; test geometry, no-reprojection path invariance across 5 schedules and 8 source cells, exact mass and monotonic projection defect. See `GREEN.stdout` and `GREEN.stderr`.
- No original C2 process was resumed, no frozen files or other worktrees modified, no CUDA/Torch training invoked.

## Acceptance boundary

This is a **P1 causal numerical diagnostic**. It isolates an error mechanism and supplies a high-precision delay-only reference. P1 remains HOLD: do not claim it solves within-active-cell reprojection, reset coupling, rare tails, log risk, full visited-state continuation values (the recorded 14,336/14,336 failures at the original 1% threshold), or trained-model gradients. P0, P2 (original four producer results, two zero-byte interrupted checkpoints and 0/6 independent replays), P3, P4 and P5 remain `HOLD_NO_GO`. This Draft should not be merged, promoted or counted as scientific GO without an independent full-head CI and separate P1 repair/qualification.

Historical comparator: [PR #6090](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6090) and its immutable measurement JSON.
