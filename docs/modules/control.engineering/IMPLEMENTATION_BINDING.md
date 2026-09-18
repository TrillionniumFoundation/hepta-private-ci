# control.engineering implementation binding

The canonical implementation guide is [IMPLEMENTATION.md](IMPLEMENTATION.md).
Concrete source lives in `tools/hepta-engineering-control/control_engineering_v2/`;
`__init__.py` exports authenticated public composition, `control_plane.py` directly
owns the SQLite v5 schema/transactions, `candidate.py` is the sole sandbox owner,
and `cli.py` exposes local scheduling and candidate qualification.

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
requires exact source/merge CI, verified native mapping, a named product caller
and executable product tests. Deployment readiness additionally requires a
distinct independent reviewer, authorized handoff, external key custody, strong
sandbox observation, observed target deployment and a rollback rehearsal. The
projection grants no authority and cannot authenticate those external receipts.

Owner work stops at durable assignments, candidate qualification, signed review
eligibility or a dormant external-system proposal. Independent key custody,
production callers and adapters, measured benefit, real target operation,
reviewer acceptance and deployment remain separate deliverables.
