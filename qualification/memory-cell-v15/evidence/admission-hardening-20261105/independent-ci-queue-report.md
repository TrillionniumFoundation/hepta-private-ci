# Scoped CI queue observation

Observed: 2026-11-05 15:19:21 UTC.

PR #4885, head `e455cfb761c8e41d8add94a7790e9d0e51fdff2d`.
Run [42051127746](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42051127746), job `127327265779`.

The run and sole `verify` job remain **queued**, with null conclusions. The run was created at `2026-11-05T15:03:50Z`; the observation is 931 seconds later. No runner has started, the job has no steps or log URL, and the artifact list is empty.

The requested ordinary protocol, history, optimized Python, old-signature and native transition checks have no execution result from this run. No new native CI qualification, ZIP, member or CI log/source-hash validation is claimed.

Separately, all 16 Python Git objects fetched at the fixed head were checked by their Git blob identity and SHA-256 against the local candidate. Those source bytes are in `pinned-source/`; their manifest is in `STATUS.json`. This source check is not a substitute for CI execution.

Raw run, normalized job-tool, artifact-list and polling observations are preserved alongside `queue-status.json`. The bounded queue observation ended after approximately 15 minutes. The remote run remains untouched and queued.
