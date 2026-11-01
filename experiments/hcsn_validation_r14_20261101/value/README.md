# R14 actual deployed-policy value audit

This directory extends the independent PR #4542 finite-state experiment inside the
R14 delivery branch based on PR #4544. Its results do not reuse PR #4544's content
models or SKIP-tail metrics. `UPSTREAM.json` binds the minimal reference code and
all 24 frozen model checkpoints to the independently identified source line.
`INHERITED_COST_PROVENANCE.json` retains the other 17 frozen cost/data artifacts.
Only the financial kernel import path changed in the copied reference code.

## What now executes

All four original A/B/C/D actors run on the same 2,048 fresh indexed random tapes.
The evaluator records the root and every occupied causal prefix, copies the
complete recurrent decision state, forces every legal first action, then executes
that same actor at every subsequent branch. Future probabilities and endpoint
fees come from the separately instantiated true world. The fitted world and
fitted planner remain distinct. Evaluator posteriors and hidden fees never reach
the actor.

Each first action has a complete conditional execution tree. Its node masses,
terminal rewards and immediate READ/RESET/time fees reconstruct Qpi. The three
components `state_estimation`, `continuation_policy`, and `world_model` sum exactly
to planned fitted Qstar minus actual true-world Qpi. This is an algebraic
attribution of value discrepancies, not an experimental causal decomposition of
architecture benefit. For fixed-read A/C, planned Qstar is an evaluator diagnostic;
A/C do not consult those scores to select actions.

Eight inherited paired fit seeds are the statistical units. New tapes do not
create new independent fits. The old negative confirmation is preserved. New
results are descriptive evaluation of frozen candidates, not a new selected
architecture or a positive acceptance claim.

## Reproduce

From the repository root, with NumPy and SciPy available:

```bash
python experiments/hcsn_validation_r14_20261101/value/publication/pack.py restore
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m experiments.hcsn_validation_r14_20261101.value.tests -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m experiments.hcsn_validation_r14_20261101.value.run run --out experiments/hcsn_validation_r14_20261101/value/evidence/reproduction_02
```

Use a fresh output directory. `SOURCE_FREEZE.json` already binds all required
sources, protocol, and checkpoints; do not recreate it. `verify()` checks both
that freeze and every copied upstream identity before and after evaluation.
Historical cost receipts are not evaluation inputs and are separately hashed.

`CONFIRMATION_PROCESS.json` is the authoritative fresh process receipt, including
interpreter startup, imports, data construction, real rollouts, exhaustive
counterfactual trees, evidence writes and process exit. Nested body, actor and
audit times must not be added to it. This diagnostic's capture/inference timing
is not a production latency benchmark. The measurement runner uses POSIX wait4;
no device energy reading is available.

## Evidence

- `PROTOCOL.json`, `SOURCE_FREEZE.json`: fixed protocol and pre-evaluation identity.
- `evidence/confirmation_01/SUMMARY.json`: per-domain means, every factorial effect,
  descriptive paired-fit intervals, root versus occupied-prefix diagnostics.
- `evidence/confirmation_01/<seed>/<domain>/episodes.jsonl.gz`: every actual
  original actor rollout with observed causal inputs, full actions and paid fees.
- `evidence/confirmation_01/<seed>/<domain>/prefixes.jsonl.gz`: each distinct
  seed/domain/arm/prefix record, actual visitation count, estimator hidden/current,
  independent true/fitted conditional posterior, every forced first action,
  complete following actor tree, all value components and numerical identities.
- `RAW_RECONCILIATION.json`: independent arithmetic aggregation of all 16 cases,
  all 8,192 rollouts and all 380,584 tree nodes.
- `VALIDATION.json`: passed behavior checks and the retained pre-freeze test
  fixture assertion failure.
- `RESULTS_ZH.md`: findings, limits, costs and remaining blockers.


The historical PR #4542 tape replay is in `evidence/historical_replay/` and
`publication/replay_historical.py`. All 8,192 original episode action/terminal
records and numerical values were reproduced exactly; this is not a new fit or
independent confirmation. The separately frozen actor-aware candidate, including
its new tapes, complete finite 27-clock expectations, negative/small effects,
and substantial actor CPU costs, is documented in `rollout_repair/RESULTS_ZH.md`.

Publication restores 665 original members from 80 complete independent gzip
containers. `publication/RESTORE_CHECK.json` records fresh-tree input/source
verification and exact member hash equality. See `publication/README.md` for the
transport details, and `RESEARCH_COST_LEDGER.json` for non-overlapping measured
research scopes and explicit unmeasured items.
