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
| A — foundation | Strict Ed25519 message verification; SQLite transactional replay admission; migration 0009; current-commit native bindings | Integrate production key and revocation ownership, durable effect outbox, quota and policy consumers. Admission is not exactly-once effect delivery. |
| B — runtime | Reusable runtime state machines; single-writer inference journal; private Agent SQLite context route; native App Server driver with generation fencing and observed terminality; six deployment scripts | Connect reservation and settlement to real model runs; implement local weights/device driver, TaskFlow effect consumers, fleet allocation and channel settlement. Five module maps explicitly retain repository gaps. |
| C — cognition | Canonical SQLite owner projects into the bounded Lane C read API, verifies content/revision and revalidates the cut before publication | Complete descriptor-safe recovery admission, rollback policy, and deployed federation consumers. Existing recovery APIs that cannot establish these facts remain unavailable. |
| D — control and NDU | Strict non-cyclic dominance; NDU-to-planner bridge; actual context count/byte planning; stateless read-only organ replacement; objective-bound Debian discovery proposals | Stateful organ migration, general organ wire adapters, full resource/endowment optimization, and physical device control. The context plan records selection at computation time; it is not model-dispatch authority. |
| E — learning | Restored strict learning/artifact interfaces; authenticated evidence; role-bound evaluation metrics; atomic holdout reservations | Connect a running trainer and independently acquired observations; execute chronological holdouts and future-window evaluation. Local fixtures cannot demonstrate lifelong learning or lack of forgetting. |
| F — intelligence | Executable pipeline ports, calibrated receipt binding, durable registry recovery and cross-module tests | Supply production cognitive/model/evaluation/ledger port owners and run the integrated shadow pipeline. Host-supplied observations must not be presented as measured model efficacy. |
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

The first GitHub consolidated Rust run executed 242 tests successfully. Strict
Clippy then found a redundant clone, which was fixed and checked locally with
warnings denied. The separate GitHub Engineering strong-sandbox job passed with
real Bubblewrap admission and no local-prerequisite skip substitution.

The OS executor now rejects procfs/PID-namespace mismatches before execution,
process enumeration and each signal, including timeout cleanup fallback. Its
native process tests require matching procfs and PID namespaces. Local negative
and admission tests pass; the native suite must run on the dedicated Linux CI
host before it can count as process-cleanup evidence. No physical-device result,
live paid-model efficacy, production deployment or future learning window is
claimed by this document.

## Integration order after this change

1. A supplies actual host trust and durable effect ownership; B consumes those
   ports for inference reservation/settlement and scheduled effects.
2. C completes recovery policy while D implements stateful organ migration.
3. E and F connect a real trainer and shadow pipeline to C's canonical data and
   A's authenticated evidence, using chronological holdout admission.
4. G consumes reviewed candidates and real deployment/rollback observations.
   Debian integration proceeds from discovery to an admitted adapter and a
   reversible lifecycle; it does not use autonomous spreading as a substitute.

Longitudinal efficacy and embodied behavior require observations from the actual
running system. These are measurable acceptance conditions, not documentation
tasks that can be closed in advance.
