# control.engineering implementation binding

The canonical implementation guide is [IMPLEMENTATION.md](IMPLEMENTATION.md).
Concrete source lives in `tools/hepta-engineering-control/control_engineering_v2/`;
`__init__.py` exports authenticated public composition, `control_plane.py` directly
owns the SQLite v6 schema/transactions, `assignment.py` owns the durable worker/claim
lifecycle, `controller.py` is the named single-writer source composition,
`candidate.py` is the sole sandbox owner, and `cli.py` exposes local qualification.

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
a document's description of a historical workflow does not.

Owner work stops at durable worker claims/assignment state, candidate qualification,
signed review eligibility or a dormant external-system proposal. The source-level
controller rejects fixture trust by default and durably binds one writer identity.
Independent external signing/key custody, deployed host identity, reviewer acceptance,
measured benefit and production deployment remain separate deliverables.
