# kernel.authority hot-path decision gate

Status: **measurement-policy evaluator; never runtime migration, production SLO, activation, or release authority**.

The strict target collector validates completeness, identities, fault outcomes,
and each driver's reported row budget. A driver-reported budget is still not an
independent site policy. `hot_path_gate.py` therefore reopens the validated real
collection and compares its 25 history-sensitive diagnostics with a separately
owned, content-addressed policy.

## Policy schema

A policy uses schema `hepta.kernel-authority-hot-path-policy.v1` and binds one
exact candidate commit/tree and target profile. It contains exactly one limit
row for each metric:

```text
final_use_frontier_hash
lease_state_clone
lease_image_serialize
clock_floor_persist
restart_rebuild
```

Each metric row defines:

- `maxP99UsByPoint` for `empty`, `1k`, `8k`, `90_percent`, and `max`;
- `maxBytesTouchedByPoint` for the same five points;
- `maxTimePerHistoryGrowthPermille`;
- `maxBytesPerHistoryGrowthPermille`.

The relative-growth checks compare work per retained history unit between
successive positive-history points. A value of `1000` is no growth in work per
history unit; values above `1000` allow bounded superlinearity. Absolute point
budgets and relative-growth budgets must both pass.

The policy itself must retain all of these fields as `false`:

```text
runtimeOptimizationAuthorized
productionSloGranted
independentAcceptance
activationGranted
releaseGranted
```

A site policy is an externally reviewed measurement threshold, not a grant to
change authority semantics.

## Evaluation

Run the evaluator only after `capacity_matrix.py validate` succeeds:

```bash
python3 qualification/kernel-authority/hot_path_gate.py \
  --plan /evidence/plan.json \
  --collection /evidence/collection/capacity-collection.json \
  --policy /opt/hepta/policies/kernel-authority-hot-path-policy.json \
  --output /evidence/hot-path-decision.json
```

The evaluator revalidates the complete collection, requires exact policy
candidate/profile identity, rejects missing or duplicate metrics, and hashes the
policy and collection bytes into the decision. It returns nonzero when any
absolute or relative threshold fails.

A passing decision still sets `runtimeOptimizationAuthorized=false`. It only
establishes that the measured candidate stayed inside the independent policy.
A failing decision names the affected metric and emits a bounded investigation
direction while preserving the current owner and recovery contracts.

## Optimization constraints

Any later runtime change must preserve all applicable counterexamples:

- FinalUse external-frontier-first ordering and exact frontier recovery;
- durable pending revocation and complete nonce/replay identity;
- one generic-lease owner with exact predecessor/revision conflict semantics;
- no observability-driven epoch reset or history deletion;
- no unknown provider result converted into absence or redispatch authority;
- restart proof over every committed prefix used by a checkpoint;
- bounded clock uncertainty large enough to cover any deliberate floor-write
  coalescing and its crash window.

The qualification WAL/checkpoint and sharding models remain reference models.
They become runtime candidates only through a separately reviewed source change,
full negative tests, exact-head and merge execution, target measurements, and
independent acceptance.
