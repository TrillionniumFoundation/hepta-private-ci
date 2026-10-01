# platform.wire: frame-work and blocking-read budgets

Date: 2026-09-29. Source amendment, not a release or target-host acceptance.

## Candidate identity and preserved owners

This amendment is based on `022f35a0947e8f7bce8cbac1c7be11f460398926`
on `codex/platform-wire-final-convergence-20260925`, PR #1094. The canonical
candidate is the actual PR head, not an older SHA embedded in historical prose.
Receipts must identify the exact source commit/tree, workflow, command, runner,
toolchain, exit result, log digest and, separately, ordered merge commit/tree.
Historical passes and queued runs do not qualify a changed head.

The same `ManagedRecordStream` and `ManagedAuthenticatedWireSession` admit and
authenticate records. No socket owner, identity source, replay journal, executor,
authority grant or product-dispatch alternative is added. Accepted-prefix
handling, consumption offsets, session retirement and consuming EOF remain.

The actual implementation has no `ManagedSessionManager` or `pending_plain`
queue. It returns owned batches. An earlier audit describing those types was
not a description of this source. Backpressure therefore belongs in the existing
consumer/transport owner, rather than in an invented second queue in wire.

## Three independent scheduling dimensions

`RecordStreamBudget` remains non-Clone/non-Copy. `new(bytes, records)` now also
bounds full serialized HPTA frame bytes to `MAX_WIRE_FRAME_BYTES` for that turn.
`with_frame_bytes(bytes, records, frame_bytes)` permits the caller to supply
already-reserved downstream capacity explicitly. `feed` continues through
`feed_with_budget`; per-stream source-byte and record-count ceilings still apply.

Charge source bytes when admitted. Charge full-record authentication attempts
and their declared complete HPTA frame size when attempted, including bad-MAC
attempts. Do not refund completed work on terminal failure. A one-byte suffix
finishing a large buffered record is charged for its full frame, not one byte.
Fragment storage remains bounded independently by the admitted record ceiling.

When a valid prefix announces a frame that does not fit, return a nonterminal
yield and `required_frame_bytes()`. The length is unauthenticated and is not
trusted content or an instruction to allocate without a host policy. Contiguous
input remains entirely unconsumed at this boundary; a split prefix may consume
only the bytes needed to complete and validate the fixed prefix. In both cases,
retain the exact suffix starting at `bytes_consumed()`. No MAC/sequence advance,
body staging or owner retirement occurs merely because capacity is unavailable.
Invalid framing is still rejected; capacity does not make invalid input valid.

This is serialized-frame work/output accounting, **not** a heap/RSS ceiling or
an automatic bound on batches retained across turns. A consumer must reserve
its queue/retention capacity before giving the allowance, account for all owned
batches, and release or transfer reservations before minting another turn.
Repeated zero-progress yields require capacity release, a larger policy-admitted
reservation, or transport-owned cancellation; do not busy-loop or drop bytes.
Connection count, queue overhead, decoded-object overhead, deadlines and peer
scheduling remain host responsibilities. Do not cache authorization decisions.

## Bounded existing blocking reader

The public `read_frame` entry now uses `bounded_read`, which delegates to the
unchanged canonical `stream::read_frame` parser. It is the same offline/plain
compatibility reader, not a new authenticated ingress or a live-peer authority.

`ReadFrameBudget` bounds every underlying Read attempt and Interrupted result.
The default allows `MAX_WIRE_FRAME_BYTES + 32` calls and at most 32 interrupted
attempts. `read_frame_with_budget` allows sharing a non-cloneable allowance
across reads. Either zero allowance rejects before touching the reader.

When a bound is reached, the wrapper returns a non-Interrupted I/O error so
`read_exact` cannot silently retry forever. The inner `ReadFrameBudgetExceeded`
reports bytes consumed, calls and interruptions for the current frame. Actual
EOF, WouldBlock and other errors retain their meaning. A reader violating the
Read contract by returning more bytes than requested is rejected.

No per-call time limit is implied: a blocking Read still requires its existing
transport deadline. This one-shot API cannot resume a partially consumed frame;
never retry it as a fresh frame after an error. Live fair/resumable scheduling
uses the managed incremental API and the existing transport/session owner.

## Regression coverage

Ten new frame-budget tests cover default-path buffered completion, zero/short
capacity, all two-part partitions, cross-peer shared capacity, charged bad MAC,
invalid prefix, replay after budget renewal, EOF and terminal isolation.
Nine blocking-reader tests cover continuous and transient Interrupted, aggregate
call bounds, zero allowance, one-byte delivery, partial progress, shared reads,
EOF, WouldBlock and invalid Read counts. Existing tests are not removed or
skipped; the new files are included in the crate's normal test module tree.

## Evidence and remaining acceptance

The editing environment has no Cargo/rustfmt toolchain. Static inspection and
source-byte checks are not Rust compilation, strict Clippy, formatting, target
execution or performance acceptance. Exact-source and ordered-merge CI must run
on the resulting commit. A prior compilation fix on the parent is not evidence
that these additional tests have passed.

This change does not grant RustOK, Ready, handoff, activation or release. Remaining
work includes authenticated real-network ingress composed with existing product
consumers; fresh identity/exporter/key-domain provisioning; reconnect/restart,
rolling upgrade and target-host cancellation; aggregate retained-memory and
fairness measurements; independent semantic/security and operations acceptance.
The five-path package-size ratio <= 0.70 and p99 ratio <= 0.80 requirements remain
unchanged. Buffer-capacity diagnostics and smoke tests do not prove them.

Continue from `TECHNICAL.md`, `BUDGET_AND_STAGING_20260929.md`,
`SECURITY_AND_QUALIFICATION.md`, and the Lane A `CURRENT_IMPLEMENTATION.md`.
