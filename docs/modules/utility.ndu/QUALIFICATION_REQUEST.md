# utility.ndu qualification request

This record requests a fresh execution of the repository's existing, fail-closed
`Hepta NDU deterministic qualification` workflow for the commit containing this
file.

The immediately preceding repaired source candidate was:

- commit: `439efc7b6d97339a199855803f24a8209384bf04`
- tree: `cf8e1b004b5607637cac1211e7caa48b55ce141a`

The qualifying candidate is **the commit containing this request**, not the
preceding commit. The workflow must bind and retain independent receipts for all
six suites in both lanes:

- `source-head`: source, core, callers, product, lint, host;
- `synthetic-merge`: source, core, callers, product, lint, host.

A queued, skipped, cancelled, historical, or partially successful run is not a
qualification result. Production activation, release authority, target-host
selection, protected-clock trust, protected-key trust, off-host backup trust,
and operator approval remain explicitly outside this request.
