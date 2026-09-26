# runtime.supervisor concurrency and host-qualification contract

This document defines the lock, I/O, scheduling and measurement boundaries for
the Supervisor daemon. It supplements `TECHNICAL.md` and
`RECOVERY_AND_QUALIFICATION.md`; it does not grant deployment, acceptance,
promotion or release authority.

## 1. State and lock domains

The daemon has four conceptually separate domains:

1. **immutable/request state** — decoded bounded request, peer identity,
   externally supplied signed material and response encoding;
2. **registry/release I/O** — Fleet records, release bundles, allow/revoke facts,
   lifecycle rows and durable journals;
3. **Supervisor mutation owner** — in-memory process slots, exact process
   handles, control revision, release transition and restart/recovery state;
4. **read observation** — cloned process snapshots combined with a registry cut
   into a digest-bound client observation.

A long-lived global mutex is not an authorization boundary. It exists only to
linearize the current in-process owner while the implementation is migrated to
narrower per-Agent execution. The following rules are mandatory:

- no socket read/write occurs while the Supervisor owner lock is held;
- ordinary roster/snapshot filesystem reads occur outside the owner lock;
- release bundle resolution occurs outside the owner lock;
- expensive build, hash, signer, audit or subprocess work occurs outside the
  owner lock;
- ticker work releases the owner lock between Agents and yields to control
  requests;
- a mutation re-enters the owner lock only for exact fence revalidation,
  preflight, control-revision reservation and the bounded owner operation;
- signed release/recovery mutation retains one exact owner/CAS critical section
  so no second mutation can pass between fence verification and durable
  transition admission;
- post-mutation read failure yields an indeterminate response, never inferred
  success;
- unknown/slow I/O cannot be converted into a positive health, drain, release or
  recovery observation.

## 2. Read-side snapshot semantics

`Snapshot` and `Roster` are optimistic observations rather than mutation
linearization points. Their safe sequence is:

1. load the bounded registry cut without holding the Supervisor owner lock;
2. acquire the lock only long enough to clone the corresponding in-memory
   process snapshot(s);
3. release the lock before serialization or transport;
4. bind registry and process fields into the returned control-state digest.

A concurrent mutation may make that observation stale immediately. This is
safe because every mutating request carries the complete control fence and the
mutation path recomputes current state under the owner lock before acting. A
stale or mixed-time read therefore causes refresh/retry or a conservative
health result; it cannot authorize a transition.

`ProductionMutationContext` is intentionally stricter. It is an authority
preparation surface and may retain the registry read in the exact owner/CAS
critical section until a revisioned registry snapshot API replaces that read.
This exception must remain bounded and measured; it must not spread to ordinary
status endpoints.

## 3. Per-Agent execution migration

The current safe intermediate design preserves one durable release coordinator
and performs ticker work one Agent at a time while releasing/yielding between
Agents. The target architecture is:

```text
Daemon accept/parse
    ├── immutable read snapshot publisher
    ├── Agent executor[A]
    ├── Agent executor[B]
    ├── Agent executor[C]
    ├── bounded process-I/O semaphore
    └── short global release coordinator
```

Each Agent executor serializes lifecycle mutations for one `AgentId`. Process
probe, drain transport and release-bundle/file I/O execute outside the Agent
state lock, then commit through generation/revision CAS. The global coordinator
is retained only for facts that are truly fleet-wide, including supervisor
epoch, external authority frontier and cross-Agent atomic release policy.

The migration is complete only when tests demonstrate:

- a blocked Agent A probe/drain does not block Agent B snapshot or mutation;
- mutations for the same Agent remain ordered and replay-safe;
- cross-Agent release policy remains atomic;
- stale async completions cannot mutate a replacement generation;
- actor/executor queues and process-I/O concurrency are bounded;
- shutdown drains or explicitly fences queued work;
- restart/recovery can reconstruct executor ownership without duplicate child
  creation.

Until that implementation lands and is qualified, the repository must not claim
that the full per-Agent actor migration is complete.

## 4. Required metrics

Target-host qualification must retain the following distributions and maxima:

- Supervisor owner-lock wait and hold duration;
- per-Agent executor queue depth and age;
- ticker scheduling delay and full-fleet tick duration;
- snapshot and roster p50/p95/p99/max;
- unrelated-Agent snapshot latency while another Agent drains, crashes or
  performs recovery;
- process probe, drain, stop and kill duration;
- restart detection and replacement-ready latency;
- registry load and release-resolution latency;
- release/restart/recovery journal append, file `fsync`, rename and parent
  directory `fsync` latency;
- open file descriptors, process count, RSS and durable-journal size;
- connection admission rejection and frame timeout count.

Repository host qualification currently enforces snapshot/drain latency from the
physical-host receipt. It is an initial SLO gate, not evidence that every metric
above is deployed or independently accepted.

## 5. Repository host profiles

The dedicated workflow executes the exact source and deterministic prospective
merge on:

| Host | Source-head load | Merge load | Named fault boundary |
|---|---:|---:|---|
| Ubuntu 24.04 | 256 real process fixtures | 8 | `SIGKILL`, crash waves, restart budget, malformed/trickled drain, permission denial, injected `ENOSPC` and `fsync` EIO |
| macOS 15 | 64 real process fixtures | 8 | `SIGKILL`, crash waves, restart budget, malformed/trickled drain and permission denial |

The macOS lane explicitly reports Linux-interposer storage cuts as unmeasured;
it may not inherit Linux evidence. Both platforms must pass exact candidate,
strict lint, signed real-Agentd lifecycle and host receipt policy. A skipped or
blocked command is a failure, not a reusable receipt.

## 6. Initial SLO gate

The repository-controlled receipt gate currently requires:

- all configured instances became live;
- 10%, 50% and 100% crash waves replaced every victim;
- unrelated PIDs stayed unchanged during partial waves;
- fourth crash exhausted the durable restart budget;
- Supervisor `SIGKILL` recovered/adopted children;
- malformed and trickled drain peers terminated through the bounded deadline;
- Linux fault injection triggered and never published an unwitnessed
  replacement;
- warm snapshot, crash-wave snapshot and peer snapshot during faulty drain have
  p99 no greater than 1000 ms and max no greater than 2000 ms.

These limits are conservative CI guardrails. Deployment profiles may impose
stricter limits. A slower runner does not turn a deadline miss into pass merely
because the command eventually exits zero.

## 7. Target-host completion boundary

Repository host evidence is insufficient for deployment completion. Actual
production qualification additionally requires the selected kernel,
filesystem, mount options, storage controller, service manager, process
namespace and release artifact. Hardware power loss, actual disk exhaustion,
reboot behavior, service-manager restart, long soak and operational recovery
must be recorded against that frozen deployment profile.

`deploymentQualificationComplete`, `independentAcceptanceComplete`, activation
and release remain false until those external receipts exist and are verified by
the independent ceremony.
