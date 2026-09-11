# Main consolidation and implementation status — 2026-09-11

This change consolidates useful branch content and implements the next executable
connections in the seven development lanes. Passing a source contract verifies
the checked implementation; it does not mean that every design gap is closed.

The initial main subject was `41878c3b81a75e721cbbcf5cf7a4e45d094deaeb`.
Its multi-parent history included branches whose useful files were absent from
the selected tree. Content reconciliation therefore restored implementations,
tests and deployed-script consumers rather than trusting ancestry alone.
PR #541 carries the incremental changes and their actual CI results.

## Delivered implementation and remaining work

| Lane | Implemented in this consolidation | Next repository work |
|---|---|---|
| A — foundation | Strict Ed25519 verification; atomic SQLite replay admission and message enqueue; fenced, recoverable delivery leases; migration 0010; current-commit native bindings | Integrate production key/revocation ownership and actual effect, quota and policy consumers. Message delivery is at least once; it does not provide exactly-once external effects. |
| B — runtime | Reusable runtime state machines; bounded single-writer inference journal; private Agent SQLite context; real App Server run admission, dispatch intent and observed settlement; six deployment scripts | Priced quotas and device grants, local weights, unknown-provider reconciliation, journal archival, TaskFlow effects, fleet allocation and channel settlement. Local run slots are not a billing or hardware grant. |
| C — cognition | Canonical SQLite-to-Lane-C reads; retained-descriptor cold images with independent full-cut and index-integrity checks; a separate, immutable read-only recovery handle | Writable descriptor-backed VFS and current writer fence, live recovery/revocation ownership, rollback policy and deployed federation consumers. The writable recovery API remains unavailable. |
| D — control and NDU | Strict non-cyclic dominance; NDU-to-planner bridge; observed context planning; stateless read-only organ replacement; fully bound compiled V2 transport; objective-bound Debian discovery proposals | Canonical V1 producer/codec and product boot integration, stateful organ migration, general resource/endowment optimization, real-time scheduling and physical control. A compiled graph or context plan is not dispatch authority. |
| E — learning | Restored strict learning/artifact interfaces; authenticated evidence; role-bound evaluation metrics; atomic holdout reservations | Connect a running trainer and independently acquired observations; execute chronological holdouts and future-window evaluation. Local fixtures cannot demonstrate lifelong learning or lack of forgetting. |
| F — intelligence | Executable pipeline ports, calibrated receipt binding and durable registry recovery; signed E V2 admission binds actual candidate bytes and authority epoch; the concrete consumer appends real ledger Decisions | Supply and compose the seven remaining host ports and authenticated raw observations, then run the integrated shadow pipeline. Manifest checks and signatures do not demonstrate measured model efficacy. |
| G — engineering | Direct SQLite owner; bounded iterative scheduler; real CLI; strong candidate sandbox; discovery-to-review proposal; fixed-target OS evidence executor | Production candidate generation, independent review, deployment/rollback and Debian lifecycle integration. A proposal does not itself activate an external system. |

Keep these tasks in their owning module documentation. Do not create another
global self-certification layer or replace outstanding implementation tasks with
an `allGapsClosed` flag.

## Removed development friction

- Retired 16 one-shot or self-mutating workflow controllers and obsolete triggers.
- Removed two historical qualification payloads totaling about 44 MB and a
  source-materialization script; retained useful implementation in normal files.
- Retired duplicate engineering maturity/closure files and runtime monkey patches.
- Removed arbitrary documentation length gates and handwritten PR identity tuples.
- Source checks derive the current GitHub event/commit identity and inspect their
  own lane's changes, so one ordinary integration PR can contain multiple lanes.
- Native bindings record both historical provenance and the actual checked blob;
  a legitimate implementation change is no longer rejected for changing its hash.
- Preserved substantive tests, owner/root checks, signed evidence, bounded reads,
  source/merge verification, and actual sandbox admission.

## Verification limits

Focused local tests cover the new contracts, transactions, recovery, planning and
consumer paths. All new runtime tests passed; one existing Matrix Unix-socket
test encountered `EPERM`, also reproduced by an independent minimal bind probe.
This is recorded as a local environmental failure, not a passing test.

The pre-second-wave GitHub source and base-merge runs each executed 1,035 tests
successfully, with eight existing skips. They exposed strict Clippy failures in
knowledge support canonicalization and shared task lifecycle code; test success
alone did not qualify those candidates for merge. The final committed candidate
must pass its own integration checks. The separate native jobs executed 138
Engineering tests and 39 OS tests successfully, with zero skips.

The OS executor now rejects procfs/PID-namespace mismatches before execution,
process enumeration and each signal, including timeout cleanup fallback. Its
native process tests require matching procfs and PID namespaces. Local negative
and admission tests pass, and the dedicated Linux CI suite supplies actual native
process-cleanup evidence. No physical-device result,
live paid-model efficacy, production deployment or future learning window is
claimed by this document.

## Integration order after this change

1. A supplies actual host trust and effect consumers; B connects priced/device
   admission and provider reconciliation to its durable native execution path.
2. C completes writable recovery policy while D connects the compiled graph to
   product boot and implements stateful organ migration.
3. E and F connect a real trainer and the remaining shadow ports to C's canonical
   data and A's authenticated evidence, using chronological holdout admission.
4. G consumes reviewed candidates and real deployment/rollback observations.
   Debian integration proceeds from discovery to an admitted adapter and a
   reversible lifecycle; it does not use autonomous spreading as a substitute.

Longitudinal efficacy and embodied behavior require observations from the actual
running system. These are measurable acceptance conditions, not documentation
tasks that can be closed in advance.
