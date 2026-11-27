# Supervisord peer baseline failure observation

The original ARM job at fixed `020f69a4479409ed88daf7a23a6caea1417de708`
reported that Agent C was not healthy in the existing five-agent daemon
restart test. The complete failed output contains no baseline stage or
status details. The same helper is called before Agent A's isolation
sequence and after daemon restart and adoption, so that message cannot
identify which call failed.

## Change

Pass a private fixed stage enum at each of the two existing calls. The
existing `status.healthy` assertion retains its predicate and failure
prefix. On failure, its message also formats the stage and fields of the
same already returned status: lifecycle, active flag, process ID, spawn
generation, runtime generation, lifecycle generation and pending release
flag. These are fixed enum variants, booleans and bounded integer options;
no logs, paths, release strings or new responses are read.

The diagnostic is evaluated only by the failed assertion. Both calls,
their existing snapshot request and original loop, all health and identity
assertions, the 120-second readiness limit, the 15-second daemon limit,
and every original wait and restart remain unchanged. No additional
snapshot, probe, delay, retry, success condition or production code is
introduced.

## Evidence boundary

The retained failure proves that one snapshot returned successfully with
`healthy=false`. It does not identify a probe timeout, process exit,
identity mismatch, fence or lifecycle transition. The source combines
several conditions into that flag. The fixture is byte-identical to the
earlier ARM branch, whose Intel error instead reported a client read
timeout. No cause is inferred by combining those different observations.

This source-only diagnostic has no new native result. Normal CI must
exercise the existing test; the message does not repair an unhealthy peer
or weaken the original rejection.
