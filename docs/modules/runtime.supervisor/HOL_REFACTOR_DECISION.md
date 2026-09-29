# runtime.supervisor HOL refactor decision

**Decision:** retain the single owner serialization boundary in this revision;
add complete wait/hold measurement and qualification before changing ordering.

## Evidence now produced

The daemon uses `MeasuredMutex<Supervisor<_>>`, preserving the existing linear
owner boundary while recording acquisitions, contended acquisitions, total and
maximum wait, total and maximum hold, and bounded slow-wait/slow-hold events.
The 256-Agent qualification exercises healthy operation, crash waves, slow
process control, slow durable I/O, and concurrent lifecycle/status/tick work.

## Why this revision does not partition the lock

The controlled fault cases are expected to create head-of-line delay: they are
there to make the risk observable and reproducible. They are not yet evidence
that a selected deployment host violates a documented deadline or accepted SLO.
Replacing the mutex with many locks without that evidence would make the
release-state CAS, lifecycle generation, process lease, restart budget, and
signed-intent ordering harder to prove while potentially preserving the same
slow external effects.

## Refactor trigger

Open a collect → effect → apply or per-Agent serialization change only when a
target-host receipt demonstrates at least one of:

1. an unrelated Agent misses a health, drain, or stop correctness deadline;
2. starvation is observed under a bounded fault wave;
3. accepted control-RPC p99/max latency is exceeded in the healthy or declared
   degraded profile.

The receipt must identify lock wait/hold, registry latency, durable publication
latency, and process-driver latency so the blocking source is known.

## Required ordering for a future change

A future implementation must specify and test:

- an immutable collection snapshot and exact generation for each Agent;
- one fenced external-effect token per Agent;
- no owner lock held across process-driver or filesystem effects;
- an apply phase that succeeds only if lifecycle generation, Fleet release-state
  generation, admission frontier, and signed authority epoch still match;
- deterministic reconciliation when the effect completed but apply lost its CAS;
- bounded global work scheduling so a crash wave cannot starve healthy Agents.

Until those rules and the trigger receipt exist, retaining the measured single
writer is the safer correctness choice.
