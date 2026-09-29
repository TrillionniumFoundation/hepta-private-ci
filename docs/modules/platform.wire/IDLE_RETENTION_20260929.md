# platform.wire: bounded idle record staging

Date: 2026-09-29. This is an implementation contract, not a qualification, activation or release receipt.

## Source provenance

This change is based on source `08568107e11f841692ba4a84f3c19ac1b7a31339`, tree `1407ec567c2173fe8c85604cddb681c8a25d51f8`, on `codex/platform-wire-final-convergence-20260925` (PR #1094). The original `record_stream.rs` was verified byte-for-byte against Git blob `4a4a9bf5995ab22019e18139457e02e161f0a2ec` before editing. This revision's implementation blob is `c29654af8ed359c8042296b7233eeb856f4b0e83`; its ten-test regression file is blob `8763c661ed1b2e82d120417e7a442cebac0d714a`.

The candidate commit and tree are those containing this document and these blobs. The PR's current-candidate section and workflow receipts must name the resulting full source SHA, source tree, tested ordered-merge SHA/tree and actual run. No parent result qualifies changed code. No self-referential source SHA or manually fabricated passing receipt is embedded here.

## Existing path, not another executor

`ManagedAuthenticatedWireSession::into_record_stream` still creates one `ManagedRecordStream`. Its normal `feed` still calls `feed_with_budget`. All framing, authenticated opening, terminal retirement and egress still use the same session owner. HPTA/HPTM bytes, negotiation, keys, sequence rules, public `RecordStreamLimits` fields and returned-frame ownership are unchanged.

The baseline already has consuming EOF checks, terminal failure retirement, exact consumed offsets, full-frame work accounting and valid-prefix/error batches. Those are preserved rather than presented as new fixes. It has one incomplete-record staging buffer, not a `pending_plain` queue or `ManagedSessionManager`.

## Why bound idle capacity separately

`Vec::clear()` removes buffered bytes but retains allocation capacity. A fragmented large record can therefore leave a large allocation behind after successful delivery, even when `buffered_bytes()` is zero. Single-call work limits do not bound this across many idle connections.

The stream now defaults its idle retention ceiling to `min(max_feed_bytes, max_record_bytes)` (64 KiB under default limits). At each successfully authenticated record boundary, before staging a following prefix, and at the end of every nonterminal `feed_with_budget` call, an empty record buffer whose capacity exceeds that ceiling is dropped. Smaller allocations stay available for reuse. Complete contiguous records retain the existing direct-authentication path; no staging allocation is introduced there.

An incomplete prefix or body is never reclaimed to satisfy the idle limit. The already-consumed prefix remains owned by the same stream until completion or normal retirement. A call ending with another incomplete record is not an idle boundary. A large-record allocation can thus remain until that record completes; this rule is an idle-capacity ceiling, not an active-buffer or process-RSS ceiling.

## Owner-facing APIs

- `idle_buffer_limit_bytes()` reports the effective idle limit.
- `set_idle_buffer_limit_bytes(limit)` clamps to the configured record ceiling and releases excessive idle capacity immediately. Zero disables idle retention. During a partial record it updates policy but preserves every staged byte. It returns the capacity released immediately, not RSS reduction.
- `release_idle_buffer()` allows the existing connection owner to reclaim all empty staging capacity under memory pressure. It is idempotent and a no-op during a partial record. It returns the released capacity and changes no key, sequence, session identity, terminal state or already-returned frame.

Ordinary successful ingress applies the default limit without a new opt-in product route. The optional pressure API belongs in the existing transport/connection owner; it is not a second scheduler. Retired connections stay retired even after a limit update or a pressure call. EOF remains connection-wide and consuming, not a newly introduced half-close.

## Aggregate resource contract

For N idle streams with configured limits L_i, their summed idle staging capacities at completed feed boundaries are at most sum(L_i). This does not include active fragments, owned output frames, transport queues, allocator metadata or memory retained by the allocator after deallocation. A finite aggregate bound also requires the existing host to bound N.

The host must separately account for downstream queues and retained batches before renewing `RecordStreamBudget`. A fresh work allowance is not permission to retain unlimited previous output. Slow consumers require bounded queue admission/backpressure; active peers require connection, read-call, deadline and scheduling bounds. Pressure reclamation is not an excuse to discard unknown operations, accepted frames or partial authenticated records.

## Regressions

`record_stream_retention_tests.rs` is included in the ordinary `record_stream` unit-test module tree. Ten tests cover repeated large records on the normal feed path; small-record allocation reuse; every two-part partial-record partition while lowering the limit; idempotent reclamation and unchanged replay rejection; normal egress identity and sequence continuity; limit clamping and admission independence; exact suffix retention under work/frame-budget yields; valid-prefix preservation before a bad-MAC suffix; every nonempty truncation at EOF; and independent-peer/retired-owner isolation.

The tests assert staging capacity and retained-pointer reuse, not allocator-call counts or RSS. Existing tests, command sets and floors are not removed or weakened.

## Verification and performance evidence

In the editing environment, the original Git blob identity and patch whitespace were checked. Rust/Cargo/rustfmt are unavailable there, so no local Rust build, unit-test pass, Clippy pass, formatting pass or benchmark pass is claimed. The exact-source and ordered-merge workflows must execute the new tests and retain their results. A queued, cancelled, skipped, startup-failed or historical run is not passing evidence.

Use the existing managed-record release profile to compare small repeated frames, intermittent large frames and repeated large frames under default and explicitly raised idle limits. Record allocation/growth observations, retained capacity, RSS, latency percentiles, throughput and multi-peer progress on the same source, runner and toolchain. Repeated large fragmented traffic may trade extra allocation work for lower idle retention; no net performance win is asserted without measurements.

The five-path package-size ratio <= 0.70 and p99 ratio <= 0.80 against reference gRPC remain unchanged. This capacity fix does not replace those gates or target-host evidence. Real authenticated ingress, peer identity/exporter/key-domain provisioning, reconnect/restart, mixed-version operations, protected target-host execution, independent reviewer acceptance and operations/release receipts remain separate requirements. RustOK, Ready, handoff, activation and release are not granted by this change.

See also `TECHNICAL.md`, `FRAME_AND_IO_BUDGETS_20260929.md`, `BUDGET_AND_STAGING_20260929.md`, `SECURITY_AND_QUALIFICATION.md` and `../../lane-a-foundation/platform.wire/CURRENT_IMPLEMENTATION.md`.

## Follow-up: record-boundary reclamation

The follow-up in `PRODUCTION_VALIDATION_20260929.md` prevents a short next-record prefix in the same feed from pinning the completed large record's allocation. Reclamation occurs only after successful authentication and delivery, while the staging buffer is empty. The existing ten regressions remain; an additional regression covers 1-, 49-, 50- and 51-byte following fragments, exact suffix continuation and unchanged replay rejection. No partial record is dropped to satisfy an idle limit.
