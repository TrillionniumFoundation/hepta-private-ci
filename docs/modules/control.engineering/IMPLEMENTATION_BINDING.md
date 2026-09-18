# control.engineering implementation binding

The canonical implementation guide is [IMPLEMENTATION.md](IMPLEMENTATION.md).
Concrete source lives in `tools/hepta-engineering-control/control_engineering_v2/`;
`__init__.py` exports the canonical authenticated v2 composition; `control_plane.py`
directly owns the SQLite v6 schema/transactions; `orchestration.py` owns verified
source issuance, signed predecessor completion and multidimensional planning;
`candidate.py` owns exact Git materialization/strong isolation while
`candidate_bundle.py` adds atomic multi-file/rename grammar; `execution_control.py`
owns host sandbox slots/retry/mutation admission and the public facade/CLI route every
strong candidate and bundle through that host-wide control; `external_control.py` persists
the highest admitted external worker fence, verifies store-bound external audit
anchors, and binds subject-specific hardware key custody to the production signing
port; and `product_caller.py` is the named read-only repository caller. `cli.py`
remains a bounded local compatibility surface.

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
requires exact source/merge CI, verified native mapping, a named product caller,
executable product tests, authenticated source issuance, authenticated predecessor
completion and the multidimensional orchestration path. Deployment readiness additionally requires a
distinct independent reviewer, authorized handoff, external hardware-backed key
custody bound to the exact production signing identity, a signed external audit
anchor that matches current authoritative store state, strong sandbox observation,
observed target deployment and a rollback rehearsal; multi-host execution also
requires an external leader/fencing backend receipt whose highest observed frontier
is durably persisted at the worker-write boundary. The projection grants no
authority and cannot authenticate or manufacture those external providers.

Owner work stops at durable assignments, merge-queue proposals, candidate
qualification, signed review eligibility or a dormant external-system proposal.
The named repository CI caller is composed but does not create a production writer.
Independent acceptance, measured benefit, real target operation, authorized
handoff/deployment, canary/promotion/release and externally governed custody/anchors
remain separate deliverables.
