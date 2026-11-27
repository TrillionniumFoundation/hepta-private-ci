# learning.operator hardening — 2026-09-30

## Status and claim boundary

This hardening starts from the immutable source candidate
`a126987b84737dbc2ee2592442a314117bddb4a2`. It does not add a new model family,
does not activate an online learner, and does not grant policy or effect
authority. All qualification artifacts remain `DENY_ALL` and
`productionActivation=false`.

The checked-in `IMPLEMENTATION_MAP.json` remains the declared module inventory.
For every qualification run, `scripts/hepta-learning-operator-map.py` creates an
exact candidate-bound copy whose `observedAtHead` contains:

- source commit and source tree;
- ordered-parent base commit;
- exact-source or deterministic-merge candidate commit and tree;
- candidate-index object IDs for the operator, Agentd consumers, qualification
  tests and required workflows.

Both refreshed maps are immutable outputs in the combined qualification receipt.
The workflow never edits source files in order to manufacture evidence.

## Default and compatibility surfaces

The default crate surface is the bounded final-use surface:

- `TrainingProfileV1` and `WorldModelProfileV1` derive their identity digest
  internally from generation, objective, sensor core, dataset frontier,
  support/error limits and runtime limits;
- `WorkControlV1` carries a monotonic deadline, cancellation state and operation
  budget into long loops;
- `build_sensor_core_controlled_v2` performs ordered-set coordinate deduplication,
  uses the seed to choose the deterministic initial point, preserves exact
  farthest-point selection and checks work control throughout candidate scans;
- `VerifiedTabularOperatorPlanV3` and `VerifiedWorldModelDatasetV3` are one-shot
  capabilities and do not implement `Clone`;
- owner currentness is checked at verify, immediately before fit, and again
  before publication/selection handoff;
- the tabular publication handoff is `PreparedTabularPayloadV3`, which contains
  exact bytes and an exact pin and can be consumed into
  `LoadedTabularOperatorV1` without exposing a mutable product artifact.

Legacy target building, raw fitting/prediction and generic V2 dataset-bound
verification are available only through the non-default `compatibility-api`
feature. CI compiles and lints both the default and compatibility surfaces so
feature gating cannot hide source decay.

## Qualification truth

`.github/workflows/learning-operator-required.yml` is called by the existing
protected `CI required` fan-in. It always creates three jobs:

1. exact source qualification;
2. deterministic ordered-parent merge qualification;
3. an `if: always()` fan-in that rejects `failure`, `cancelled` and `skipped`.

The exact-source lane requires:

- locked default and compatibility builds/tests;
- owner final-use, fresh-load, shadow, source-revocation and lineage-rollback
  tests;
- strict Clippy and rustfmt;
- an operator-specific line coverage floor;
- bounded safety mutations with a 100% required kill rate;
- sensor-core measurements at 1K, 4K, 8K and 16K candidates;
- complete tabular fit measurements at 100K, 500K and 1M rows;
- a candidate-bound refreshed implementation map.

The deterministic-merge lane repeats locked build, tests, lint, formatting and
implementation-map observation on a synthetic commit with explicit ordered
parents `(base, source)`. Its commit and tree are verified in the producing job;
the commit is intentionally not pushed.

The combined receipt binds source/candidate commit and tree, Cargo.lock, Rust and
Cargo identity, runner image fields, workflow, implementation map, test-set
hash, coverage, mutation, performance and test logs. The synthetic receipt is
verified before upload; fan-in verifies its immutable bytes and output hashes
without pretending the isolated synthetic commit exists in another runner.

## Performance boundaries

Until the qualification measurements prove otherwise:

- the raw compatibility tabular fit is capped at 100,000 samples;
- the controlled tabular qualification fit is capped at 1,000,000 samples;
- the raw compatibility world-model fit is capped at 16,384 samples;
- the controlled world-model qualification fit is capped at 65,536 samples;
- every controlled sample, state/action, candidate and separation loop performs
  periodic cancellation, deadline and operation-budget checks.

The current time and RSS thresholds are runaway guards, not product SLOs. The
measurement receipt records p50, p95 and p99 for the complete operation,
including input materialization. A future SLO must be adopted separately from
measured target-host evidence.

## Existing shadow-loop composition

The hardening deliberately reuses the existing owner and Agentd path rather than
introducing another runtime:

```text
ledger dataset freeze
→ owner-terminal fit
→ independent frozen holdout comparison
→ artifact registration and lineage
→ fresh payload reload
→ Agentd read-only prediction
→ registry/source/dataset currentness checks
→ source withdrawal and descendant rollback checks
```

`terminal_cell_owner` exercises this path with authenticated durable owner
records, independent held-out episodes, fresh loading, payload tamper rejection,
artifact revocation, source correction and descendant ineligibility. This is a
qualification shadow loop. It is not canary promotion and does not set
independent acceptance or production activation.

## Deferred model expansion

The following remain explicitly deferred until the required qualification set is
green on the exact source and deterministic merge candidate:

- world-model uncertainty calibration;
- calibrated abstention;
- drift detection;
- HNMF or neural operator implementation;
- canary promotion and production writer activation.
