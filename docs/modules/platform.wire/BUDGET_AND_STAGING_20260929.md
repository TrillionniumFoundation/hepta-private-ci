# Shared feed budgets and contiguous-record staging

Date: 2026-09-29
Source baseline: `ae68b19710a13ed2fccd24798b1ccb842dae0a59`
Scope: `codex-hepta-wire` / existing `ManagedRecordStream`.
Status: source change and regression specifications; not an acceptance receipt.

## Correct source boundary

The baseline stream consumes the single `ManagedAuthenticatedWireSession` owner. It has one bounded incomplete-record buffer and returns owned batches to its caller. It does not contain a socket reader, manager-owned plaintext queue, transport retry loop or alternate product dispatcher. Baseline EOF is consuming, checks incomplete records and retires that same owner. Terminal feed errors already retain accepted frames and retire the stream. Those existing properties are preserved, not claimed as newly implemented fixes.

Do not use descriptions of `ManagedSessionManager`, `pending_plain`, a fixed inner 64-record decoder or `max_records_per_pump` as evidence about this implementation. The actual API is `RecordStreamLimits::{max_record_bytes,max_feed_bytes,max_records_per_feed}`.

## One implementation, two ways to supply work limits

`feed(input)` creates a local allowance from the stream limits and delegates to `feed_with_budget(input, &mut RecordStreamBudget)`. Existing consumers therefore use the same decoding path as consumers supplying a shared allowance. The budget is re-exported at the crate boundary and deliberately is neither `Clone` nor `Copy`.

The effective byte limit is the minimum of input length, the configured per-feed byte limit, and the shared remaining-byte allowance. The full-record authentication-attempt limit is the minimum of the configured per-feed record limit and shared remaining-record allowance. Every source byte consumed is charged once. A full-record MAC/schema/replay failure consumes one attempt; rejecting a framing prefix consumes only that prefix and no full-record attempt. A terminal error does not refund consumed work. An already retired stream consumes no further allowance.

Zero allowance is valid: a nonempty input yields with zero bytes consumed, no protocol error and no session reset. Empty input remains a non-EOF no-op. The caller must retain and resubmit the exact suffix after `DecodeFeed::bytes_consumed()`, yield the executor instead of spinning, and choose a fresh bounded allowance only when starting the next scheduling turn. Cancellation/retirement and consuming EOF do not depend on admission capacity.

Sharing one mutable allowance across peers bounds their aggregate admitted bytes and full-record authentication attempts. It is not a scheduler and cannot establish fairness by itself. Rotate the existing owner's starting peer between turns; otherwise the first busy peer can consume every turn's allowance.

## Memory accounting is explicit, not overstated

The incomplete-record buffer remains subject to the existing per-record bounds and bounded geometric reservation. The owner of returned batches must bound retained frame count and bytes, drain or otherwise account for accepted frames before starting another turn, and apply backpressure before reading more transport input. The transport owner must separately bound active connections, its input/output queues and pending writes. Bytes admitted this turn are not an exact bound on decoded bytes delivered this turn: completing a previously buffered large record can return more decoded bytes than the new suffix length. Combine the attempt allowance with admitted record-size ceilings and consumer-owned retention accounting.

No plaintext queue or second physical manager is introduced here. No end-to-end memory, executor retry, network ingress or host acceptance claim follows from the shared allowance alone.

## Contiguous-record optimization

When no fragment is buffered and an entire record fits within the current effective byte limit, framing admission checks inspect the caller's slice and the same session owner authenticates that exact slice. The intermediate record-buffer copy and its allocation are avoided. Fragmented records retain the existing bounded buffer/reuse behavior. Both paths use the same prefix, session identity and declared-length validation and the same final MAC, sequence and schema checks.

This is a framing-staging optimization, not end-to-end zero-copy. The owner may allocate decoded envelopes; batches own their frames; transport queues and allocator overhead remain outside `buffer_capacity_bytes()`.

## Regressions

`src/record_stream_budget_tests.rs` adds 14 tests: complete-record zero staging; every two-part partition; a shared allowance across independent peers; zero allowances; byte-exhausted fragment resume; local record and byte limits; charged bad-MAC suffix with valid-prefix delivery; early bad-prefix rejection; empty input; cancellation with no byte allowance; EOF after yield; retired-peer isolation; and replay rejection across fresh allowances. The existing tests remain unchanged, including direction/session isolation, mutations, all truncations and normal Unix-stream composition.

## Verification and remaining qualification

The editing environment had neither Cargo/rustc nor DNS access to install a toolchain. No local Rust compilation, Clippy, benchmark or host run is asserted. Exact original blob hashes were checked before modification. Remote execution must test the pushed source and ordered merge independently with the existing read-only workflows.

Required commands include the existing wire all-target tests, strict Clippy, consumer/resource contracts, release single-session and fleet profiles and validators, actual fuzz campaign, normal runtime.codex integration and target-host checks. Retain command exit codes, source/tree identities, workflow identity and raw measurement digests; queued or skipped work is not passed evidence. Do not compare parent benchmark results as though they measured this optimization.

Independent transport identity/exporter-key provisioning, real ingress/backpressure, I/O retry/deadline/cancellation budgets, reconnect/restart and mixed-version host acceptance remain their existing owners' responsibilities and require actual evidence. Frozen throughput/latency/size thresholds, protected target-host requirements, lifecycle flags and release gates are unchanged.
