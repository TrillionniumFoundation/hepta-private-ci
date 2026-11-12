# VERIFY-8 exact-source CI and provider follow-up

This evidence-only stage is stacked on the VERIFY-7 evidence head
`b49ee7b385958a7c6b12de147248dd6e745810ce`. It adds no model fit,
prediction, actor execution, business task, trust key, evaluator authority or
production adoption.

## Exact-source CI change

Direct job receipts now show these additional terminal successes:

- integrity head `3c2a347969291b2fbd99198140fbe608f3e4425d`: Windows job
  `130997532886`, 269 tests;
- callback-isolation head `8947b0c2a9c5829258dcec0498146872499c11b3`:
  macOS job `130997576719` and Windows job `130997577094`, 274 tests each;
- provider-adapter head `e23e343243c52608db5a59cf9a75e96591b31bb8`:
  Windows job `130997619062`, 284 tests.

Each retained job is attempt 1, binds its own exact head in the full jobs API
payload, concludes success and contains `CONSISTENT_COMPLETE_RECORDS`. The raw
decoded job logs and full attempt-1 jobs payloads are in
`EXACT_SOURCE_CI_ORIGINALS.zip`. These receipts do not transfer across heads or
platforms. The three Ubuntu jobs and the blocking/architecture workflows remain
queued, so the all-platform/blocking gate is not closed.

## Frozen prospective follow-up

The immutable 12-job roster was read again without rerunning or replacing any
job. Observations 17 through 24 append the eight exact run/attempt payloads to
the prior 16 observations. All 12 planned jobs remain queued, so the result is
0 known provider labels and 12 explicit UNKNOWN outcomes. Acquisition cost was
not measured and remains unknown.

The provider adapter accepts the 24-observation record and preserves all 12
denominators. These same-provider CI-property observations are not independent
business trajectories, independent terminal adjudication or evaluator custody.

## Decision

`BLOCKERS.json` remains authoritative: `all_blockers_closed=false`, scientific
admission `HOLD`, learning decision `NoUpdate`, production authority `NONE`.

