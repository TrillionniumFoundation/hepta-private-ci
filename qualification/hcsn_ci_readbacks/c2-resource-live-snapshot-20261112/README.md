# C2 live resource observation (evidence only)

**HOLD_NO_GO / all_closed=false. Full independent replay remains 0/6.**

This successor to #6252 preserves a read-only point-in-time observation from the configured `h` interfaces. It started no shell process, model, optimizer, native campaign, workflow rerun, or new idempotency key.

The observation closes only two facts for the sampled instant:

- `desktop` and `ai395` were authenticated and reachable through the configured transport.
- Their hardware snapshots reported host-level `MemAvailable` and `MemTotal`.

It does **not** supply ancestor-cgroup current/limit/headroom or ownership, an effective aggregate allocation, a six-fit concurrency/calendar reservation, a coherent source/runtime/model/data freeze, all six original start parents, or the non-refunded remaining-wall ledger. The runtime policy's `concurrent_execution=unbounded_by_runtime` describes the controller configuration; it is not an allocation.

Therefore these snapshots cannot authorize or justify starting the original six-worker full replay. Historical OOM, cancelled attempts, full replay 0/6, known diagnostic calls 52, lifetime optimizer total UNKNOWN, and original controller terminal UNKNOWN remain unchanged.

`OBSERVATION.json` contains the complete returned health, hardware, and redacted effective-config objects. `HOLD.json` records the exact closure and remaining prerequisites. This branch contains no executable workflow or model source.
