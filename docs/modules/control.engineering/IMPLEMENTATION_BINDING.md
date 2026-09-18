# control.engineering implementation binding

The canonical implementation guide is [IMPLEMENTATION.md](IMPLEMENTATION.md).
Concrete source lives in `tools/hepta-engineering-control/control_engineering_v2/`;
`__init__.py` exports the canonical authenticated v2 composition; `control_plane.py` directly
owns the SQLite v5 schema/transactions; `orchestration.py` owns deterministic rich
work assignment and integration-order proposals; `candidate.py` is the sole sandbox
owner; `product_gate.py` is the named read-only repository product caller; and
`cli.py` exposes local scheduling and candidate qualification. The historical
`hepta_engineering_control.py` module is compatibility-only and is not a canonical
native mapping or product-composition boundary.

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

Owner work stops at durable assignments, candidate qualification, signed review
eligibility or a dormant external-system proposal. Independent key custody,
external deployment adapters, measured benefit, real target operation,
reviewer acceptance and deployment remain separate deliverables.


## Canonical completion truth

For this module, `TRACEABILITY.json` maps design operations to v2 symbols and tests,
`IMPLEMENTATION_MAP.json` records repository composition state, and
`PRODUCTION_IMPLEMENTATION.json` records the fail-closed product/deployment claim
boundary. The shared `sourceBase` in implementation maps is a historical map-generation
baseline, not the current checked-out source identity; exact current source identity
comes only from Git/CI receipts. No document may infer product execution, acceptance,
activation, promotion, release, or deployment from that baseline.
