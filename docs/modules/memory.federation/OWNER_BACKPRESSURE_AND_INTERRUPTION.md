# Owner backpressure and interrupted qualification

## Status and ownership

This addendum describes a source candidate on the existing memory-federation
closure branch. `CAPABILITY_STATE.json` remains the sole capability-status
owner. No execution, independent acceptance, real-host qualification,
activation, promotion or release claim is advanced by this document.

The canonical V2 engine, Agentd/Memory composition, preflight/post-I/O/final-use
authority checks, half-budget discovery reservation, deterministic peer
selection, explicit `legacy-v1` compatibility gate, authenticated-before-staging
admission and indexed expiry maintenance remain unchanged. There is no new
execution spine, peer registry, credential store, authority cache or retry loop.

## Nonblocking acquisition at the existing transport boundary

`FederationWireTransportV2::send_once` must not block an executor thread waiting
for its synchronous client-owner mutex. A blocked poll prevents the canonical
engine from observing its deadline/cancellation future. The two async-path owner
acquisitions now use `try_lock` and distinguish the boundary already crossed:

| Boundary | Busy owner | State and effect |
| --- | --- | --- |
| Before durable query preparation | `NonTerminal(Unavailable)` | No clock observation, query attempt or network exchange is created by this call. |
| After the network exchange, before response admission | `NonTerminal(NoTerminalObservation)` | The pending intent survives. No response is parsed/admitted, no terminal result is invented and the request is not replayed. |
| Either acquisition, poisoned owner | `TransportRejected` | Poisoning is not relabeled as ordinary backpressure. |

Successful acquisitions still sample the local clock after obtaining the owner.
The existing post-preparation deadline check, exact-query response preflight and
post-terminal-persistence expiry checks are retained. Receiving packet bytes is
not a trustworthy terminal observation before authenticated durable admission.

This is bounded fail-closed backpressure, not an asynchronous wait queue. It can
reduce availability under contention, so a selected deployment must measure
rejection rate, pending-attempt occupancy and cancellation latency. Repeated
calls are not an authorization to retry an already prepared query identity.

The synchronous administrative `maintain_expired` operation remains under the
same client owner. This change does not make a synchronous recovery-store write
interruptible once it has begun. A selected host still needs an independently
qualified execution/resource policy for blocking persistence; substituting an
unbounded detached worker or discarding an admitted write on timeout is not an
acceptable substitute.

Four regressions are compiled with the existing wire library test suite. They
exercise contention before preparation, contention after exchange, lock poison,
and dropping a pending exchange. The contention tests poll on a worker thread
with a bounded rendezvous and release the held lock before joining, so reverting
the fix produces a bounded test failure rather than hanging qualification.
Private owner state is inspected only by a nested test module; the production
API gains no test-only bypass.

## Interrupted command evidence

The existing `memory_federation_execution_receipt.py` recorder remains the only
executor for the existing shell qualification entrypoint. Its command manifest,
source identity, raw-log digest and final-input checks remain in force.

When SIGTERM or SIGINT interrupts a running command, the recorder forwards the
signal to the command's own process group, reaps the leader, escalates when
necessary, and retains the actual exit status and log. A child that traps the
signal and exits zero does not turn the interrupted qualification into a pass.
The recorder stops the command matrix and writes diagnostic failure evidence.
A timeout remains distinct from an interruption of the recorder itself.

A leader may also exit while descendants in its process group still own logs or
build inputs. The recorder attempts to terminate that remaining group even when
the leader exited zero and disqualifies the command. It never signals the
caller's process group. This is not a process sandbox: separately detached
sessions require runner-level containment, and SIGKILL, machine loss or storage
failure may prevent final diagnostic writes. Such missing or `running` receipts
remain unacceptable, not assumed successful.

Command entries add optional `interruptedSignal` and `orphanedChildren` fields.
The validator checks their types and allowed values and includes both in failure
determination. Older entries without these fields remain readable, but the
existing exact source/command binding still prevents historical receipts from
qualifying this new candidate. No validation is relaxed for successful receipts.

Ten new recorder regressions are included in the existing
`test_memory_federation_execution_receipt.py`, which is already in the canonical
qualification command manifest. They use actual child processes and output,
including external signals, a signal-trapping zero exit, a surviving descendant,
a normal success, nonzero and signal exits, timeout, malformed optional fields
and backwards-readable records. Test-local source/command fixtures exercise the
recorder only and cannot count as product execution evidence.

## Evidence and source freeze

Local author checks for this change ran the ten new recorder cases in isolation
against the edited recorder and passed. The external-SIGTERM regression failed
against the original recorder (process exit `-15` rather than retained failure
exit `1`). Both edited Python files also passed `py_compile`. The complete
existing Python suite and the Rust library, format and Clippy matrix were not
executed in the author's local environment; the four Rust regressions are source
additions awaiting that matrix. No real two-host experiment was performed.

Publish the source change first as an immutable Git commit, then bind its exact
commit, tree and changed source objects in a separate metadata-only
`IMPLEMENTATION_MAP.json` observation. Advance the feature branch to the complete
pair. The existing read-only exact-head and deterministic-current-base merge
qualification must execute against the published candidate; neither source
preparation nor map rebinding is a successful execution receipt.

Selected mutually authenticated transport, credential lifecycle operations,
production recovery choice, two independently provisioned hosts, measured
latency/capacity/backpressure, independent acceptance and operator-controlled
activation remain separate gates. This patch does not select or activate them.
