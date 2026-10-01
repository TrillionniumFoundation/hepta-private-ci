# Managed HPTM stream integration

## Ownership and compatibility

`ManagedAuthenticatedWireSession::into_record_stream(RecordStreamLimits)` consumes the existing authenticated owner. `ManagedRecordStream` does not establish a transport, issue authority, clone replay counters, or create a checkpoint/store. Frozen HPTA V1/V2, HPTN and HPTM V1 bytes and key derivation are unchanged. HPTM framing is distinct from the existing raw-HPTA `WireSessionDecoder`.

The transport owner must supply the already authenticated channel binding, peer identity and key before construction. A fixture key or Unix socket round trip is not a TLS-exporter or deployment acceptance claim. In-process runtime.codex V3 admission remains before its existing final-use authority; this extension does not relabel it authenticated remote ingress.

## Read-loop contract

Call `feed` on the available bytes. Read `bytes_consumed`, deliver each admitted frame in order, and retain the untouched suffix. `yielded()` means the per-call byte or record budget was exhausted; yield the executor before resubmitting that suffix. A completed prefix is delivered even when a later record is terminal. Never replay that prefix. Terminal framing, MAC, policy or sequence failure retires the same bidirectional owner and destroys its key-bearing state. `retire` is the cancellation path. `finish` consumes the stream and rejects partial records at connection-wide EOF; half-close is not supported by this API.

Read deadlines, connection counts, cancellation scheduling and effect recovery remain with the existing transport/domain owners. No decoder recovery permits an uncertain domain effect to be replayed.

## Bounds and diagnostic privacy

Limits are validated at construction: record bytes cannot exceed the frozen global ceiling; per-call bytes are positive and globally capped; records per call are 1..1024 (default 16). The default per-call byte budget is 64 KiB. The caller's input is borrowed, never copied wholesale. Only the 50-byte outer prefix is admitted before the declared frame length is checked. Allocation is fallible and bounded by the admitted record. The pending buffer is reused between records, avoiding front-draining a shared queue. Returned frames belong to the caller, which must bound its own queues.

A pending large record plus its decoded payload, returned frames, caller read buffers and caller queues all contribute to peak memory. These are structural bounds, not target-host measurements. Debug formatting reports counts, limits and the session digest, not payload or key bytes. HMAC is not encryption.

## Regression sources and evidence

`src/record_stream_tests.rs` covers every two-way transport split, byte/record yields, every incomplete second-record prefix at EOF, valid-prefix plus tampered suffix, mutation of every record byte, oversized declared lengths, reflection/replay/cross-session replay, cancellation and invalid budgets. Its Unix socket-pair case exercises real local OS I/O with fixture authentication and the same owner API; it is not independently authenticated peer admission.

At source publication these are test sources, not a passing execution receipt. The read-only core source/ordered-merge workflows must run the full package and strict lint on the final commit. Fuzz, resource measurement, protected target-host, independent reviewer, operations and release receipts remain separate. No lifecycle boolean is promoted by this document.
