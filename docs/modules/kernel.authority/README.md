# kernel.authority development index

Use this directory in the following order:

1. [`TECHNICAL.md`](TECHNICAL.md) — stable architecture, ownership, state,
   linearization, failure and completion contracts.
2. [`CONVERGENCE_STATUS.md`](CONVERGENCE_STATUS.md) — latest immutable-source
   overlay for trusted-clock ownership, production bootstrap, executable port
   acceptance and target-host capacity.
3. [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) and
   [`TRACEABILITY.md`](TRACEABILITY.md) — generated implementation and caller
   projections.
4. [`PORT_MATRIX.md`](PORT_MATRIX.md) — declared target-port source maturity;
   use retained `port_acceptance.py` output for executable evidence.
5. [`LINEARIZATION.md`](LINEARIZATION.md),
   [`PRODUCTION_TRUST_PROFILE.md`](PRODUCTION_TRUST_PROFILE.md),
   [`PRODUCTION_CLOSURE.md`](PRODUCTION_CLOSURE.md) and
   [`CAPACITY_QUALIFICATION.md`](CAPACITY_QUALIFICATION.md) — normative
   ordering and qualification details.

The latest source-bound overlay is generated from
`qualification/kernel-authority/convergence_manifest.json` and checked by
`qualification/kernel-authority/convergence_acceptance.py`. It pins source facts
without self-granting exact execution, production trust, target-host
qualification, independent acceptance, activation or release.

Do not infer completion from a source callsite, a parser unit test, a queued
workflow, a synthetic fixture, or a compatibility trust profile. The relevant
raw execution and external evidence must be reopened under the same immutable
candidate identity.
