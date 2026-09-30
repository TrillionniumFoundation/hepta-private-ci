# runtime.supervisor HOL refactor decision

Status: evidence-triggered architecture decision for the exact candidate. This document does not grant activation, deployment, promotion, release, or independent acceptance.

## Current ownership model

The daemon keeps one lifecycle writer and one FIFO execution permit. Synchronous process, registry, and durable-state effects run in the bounded blocking lane while mutation ordering remains serialized. Health, roster, and Agent snapshot reads use the immutable bounded read projection and therefore do not queue behind the lifecycle writer when the projection is current.

The measured owner mutex records acquisition count, contended acquisition count, total/max wait, slow waits, total/max hold, and slow holds. The 256-Agent qualification additionally records tick duration, owner-snapshot latency, cached status latency, slow-driver behavior, slow durable-I/O behavior, concurrent drain/status/tick traffic, and 10/50/100 percent crash waves.

## Decision rule

Do not replace the current writer with many independent mutexes merely because contention exists. A refactor is admitted only when an exact target-host receipt shows that unrelated-Agent mutation latency or lifecycle deadlines are violated by writer serialization after the read projection has removed observation traffic.

The receipt must bind commit/tree, binary digest, target host, runner/kernel, fleet size, Matrix posture, fault profile, lock telemetry, p50/p95/p99/max mutation latency, tick-delay maximum, missed deadlines, and per-Agent recovery completion time.

If the trigger is met, the preferred change is **collect -> effect -> apply** or equivalent per-Agent serialization with an explicit final apply fence:

1. collect immutable Fleet/lifecycle generation, release transaction identity, authority/frontier witness, and exact process identity;
2. execute only effects proven independent of the global writer under an Agent-scoped ownership token;
3. reacquire the authoritative apply boundary and reject if generation, Fleet CAS, authority epoch, admission frontier, or transaction predecessor changed;
4. publish the new immutable read projection only after the authoritative apply commits.

A mechanical `Mutex<Supervisor> -> many Mutex<Agent>` rewrite is prohibited because it would obscure cross-Agent Fleet ownership, release-state CAS, daemon authority, and recovery ordering.

## Current decision

Repository qualification intentionally creates slow-driver and slow-durable-I/O cases to make head-of-line coupling observable and measurable. Those synthetic delays establish the causal mechanism; they are not a target-host service-level violation. Until the exact target-host receipt crosses the rule above, retain the current single writer plus immutable read projection and optimize evidence/diagnostics rather than widen concurrency authority.
