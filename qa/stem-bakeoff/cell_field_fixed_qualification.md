# Fixed-action synthetic QA qualification

Source-only additions against c69e4e7ab55456e75476be4ca9a3bcaeaea1934c
(tree 67a83f5bace75465fd1dc775292b70cf491f2c6b). No serving or experiment
entry point is changed. The four original Cell source modules are reused in
place and verified against cell_field_fixed_sources.json; there are no vendored
copies, model weights, experimental data, archive parts or final labels here.

## Reviewable stages

1. Fixed actions, summary algebra and tests, with this note and source contract.
2. Real-class q4 adapter, shared synthetic fixture and adapter tests.
3. Bounded in-memory prediction census and tests.
4. Fixed subprocess worker, parent fsync census gate and six-window tests.

Each stage adds under 500 lines. Apply them in order. The source contract
binds the existing base modules, not external provenance or production authority.

## Run

From qa/stem-bakeoff using an existing Python 3 environment with NumPy:

    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s . -p 'test_cell_field_fixed_*.py' -v

The subprocess gate is explicitly Linux/POSIX-only (fcntl, /proc and process
groups). Non-Linux discovery explicitly skips its six grouped tests and the
one direct-RSS census test; it does not fail importing unavailable modules.
These skips are not non-Linux qualification. On Linux, all 52 tests execute.
It requires 3 GiB observed free space before starting; that is not a
reservation against concurrent consumers. No security settings or cgroups are
changed. The other numerical fixtures require only Python/NumPy.

The integrated namespace contains 52 tests: 24 action/summary, 8 adapter,
14 census and 6 grouped subprocess windows. This is a fresh integrated suite,
not the sum of historical prototype counts. The prototype's earlier 52-test
suite included six history tests that are deliberately excluded here; its six
subprocess windows were qualified separately. Do not add those historical totals
to the integrated result. A passing namespace suite is not a whole-repo pass.

## Boundaries

Fixtures contain random synthetic features, artificial labels and constructed
finite Adam state, not trained or recovered experiment checkpoints. Numerical
checks cover H3 and positive variance, not real H8 checkpoint qualification.
The q4 adapter scores fixed impulses; it does not optimize or train a policy.
Only Loss2/q4/Full are wired here, not all five proposed predictors.

The in-memory census enforces attempts and JSON payload limits and makes
cooperative wall/RSS observations; it is not crash durable or a hard sandbox.
The subprocess gate freezes all 147 synthetic Linear36 action/mode tuples but
executes at most three calls, which are zero impulses in the fixed order. Its
single writer publishes a full plan and fsynced started/terminal hash chain.
Recovery never retries a started-but-unfinished call. Success requires a matching
finite response, reaped direct child, zero exit and deadline compliance.

stdout/stderr are separately bounded. Timeout signals the owned process group,
but only direct-worker reaping is confirmed. There is no complete descendant,
parent-death, sudden-power-loss, rollback resistance or hard RSS guarantee.
Local hashes do not protect against hostile concurrent file replacement.

Separated original development inputs remain required for actual experiments.
No result here establishes model quality, retention, utility or production readiness.
