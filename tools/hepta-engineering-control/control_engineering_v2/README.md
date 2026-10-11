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
