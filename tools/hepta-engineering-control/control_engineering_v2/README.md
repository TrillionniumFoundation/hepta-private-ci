# control_engineering_v2

Lane G owns durable local engineering coordination, bounded candidate qualification
and authenticated review eligibility. Run from the repository root:

```sh
PYTHONPATH=tools/hepta-engineering-control python3 -m control_engineering_v2 --help
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tools/hepta-engineering-control -p 'test_*.py'
```

Installing `tools/hepta-engineering-control` also provides `hepta-engineering`.
Commands are `schedule`, `candidates` and `sandbox`; all accept bounded JSON inputs.
The implementation guide, component map and security profile live in
[`docs/modules/control.engineering/`](../../../docs/modules/control.engineering/IMPLEMENTATION.md).
`SCHEMA.sql` is the sole executable schema, version 10. No import-time patches or
registry-count validators are required. Linux strong isolation must pass the actual
Bubblewrap probe; portable fixture success cannot become strong review evidence.
Review eligibility and dormant proposals do not merge, activate or deploy changes.

The named product composition is `EngineeringControlProduct`, which owns one SQLite v10
`EngineeringStore`, repository identity, verifier port, resource-aware planner, persistent
cross-generation capacity reservations, startup reconciliation and durable
integration-queue reconciliation. Stage and terminal receipts bind the complete persisted
source/base/queue/owner context. Product CI exercises exact-source and deterministic
base-merge lanes; GitHub reviewer observations are identity evidence only and never confer
independent acceptance or merge authority.

`python3 -m control_engineering_v2.qualification_profile` runs bounded per-host
measurements through the same complete candidate sandbox. Fixture mode is for local
regression only; strong mode requires the real Bubblewrap profile. Neither mode grants
operator acceptance.

## Bounded owner supplement (2026-09-28)

The [bounded owner contract](../../../docs/modules/control.engineering/BOUNDED_OWNER_CONTRACT.md)
documents exact audit read cuts and pre-payload budgets, connection-local incremental
capacity observations with external-writer invalidation and calibration, and authenticated
revision-bound worker renewal with retained-outcome replay. These capabilities are
composed through this same `EngineeringControlProduct`, not a parallel test executor.
The audit-page continuation is trusted only as a retained verification chain; it does
not certify a new owner-state snapshot. Capacity observations do not authorize writes.

Run the fixed-source/fixed-base evidence collector from a clean final checkout:

```sh
python3 scripts/control_engineering_candidate_evidence.py \
  --source-commit "$(git rev-parse HEAD)" \
  --base-commit "$(git rev-parse origin/main)" \
  --output /absolute/new/directory/outside/checkout
```

The collector retains each failed command and continues collecting later checks. It
never edits source, refreshes maps to hide drift, or grants production acceptance.
Source, merge, independent review and target-host acceptance remain separate gates.
