# control.engineering implementation binding

The canonical implementation guide is [IMPLEMENTATION.md](IMPLEMENTATION.md).
Concrete source lives in `tools/hepta-engineering-control/control_engineering_v2/`;
`__init__.py` exports the authenticated v2 public composition. `control_plane.py`
directly owns the SQLite v5 schema/transactions; `orchestration.py` owns exact-source
admission and resource-aware planning; `candidate.py` is the sole candidate workspace
owner; `sandbox_control.py` owns sandbox admission/retry ceilings; `mutation_testing.py`
owns evaluator mutation testing; `external_controls.py` verifies distributed fencing,
external audit anchoring and HSM/KMS custody; and `product_gate.py` is the named
repository CI product caller. The package-root API intentionally does not export
`facade.issue_work_envelope` or `facade.schedule_ready_packages`; those remain explicit
local compatibility primitives and do not authenticate canonical source/completion facts.
New composition uses `issue_repository_work_envelope` or `issue_signed_work_envelope`
plus `plan_engineering_work`. `hepta_engineering_control.py` is compatibility-only
and is not a native mapping or supported integration surface for new callers.

[COMPONENTS.json](COMPONENTS.json) and [TRACEABILITY.json](TRACEABILITY.json) are
source/test navigation maps. They do not self-certify maturity or grant authority.
Historical `HARDENING.json`, `CLOSURE_V4.json`, `MATURITY.json` and copied package
registries are retired; their useful behavior is in the current source, schema,
implementation guide and behavioral regressions. No historical materializer,
self-pushing workflow or static-registry validator is needed to run this package.

Run the test commands in the implementation guide. Strong sandbox qualification
requires the real Linux Bubblewrap probe and `HEPTA_REQUIRE_STRONG_SANDBOX=1`.
Portable fixture execution has a distinct maturity result. Current CI workflow
files, actual job logs and signed execution receipts establish qualification;
a document's description of a historical workflow does not. Backup, restore,
key-rotation and incident procedures are in [OPERATIONS.md](OPERATIONS.md).

Repository promotion of the `production_implementation` fact is fail-closed.
`control_engineering_v2.production.evaluate_production_readiness` projects
already-authenticated evidence into two separate states. Production implementation
requires exact source/merge CI, verified v2 native mapping, an observed named product
caller receipt, sandbox-controller evidence, evaluator mutation-testing evidence and
executable product tests. Deployment readiness additionally requires a distinct
independent reviewer, authorized handoff, external hardware-backed key custody,
strong sandbox observation, distributed fencing, an externally retained immutable
audit anchor, observed target deployment and a rollback rehearsal. The
projection grants no authority and cannot authenticate those external receipts.

Owner work stops at durable assignments, candidate qualification, signed review
eligibility or a dormant external-system proposal. Independent key custody,
measured benefit, real target operation, reviewer acceptance and deployment remain
separate externally evidenced deliverables. The repository product caller exists in
source but does not make `production_implementation` true until the exact candidate
has a successful source/synthetic-merge execution receipt.
