# Native Stem/Cell scale trace contract v2 (read-only)

**Scope:** Offline diagnostic consistency only. This contract cannot authenticate
a native Hepta Worker, prove that one fused tensor kernel ran, issue any use
grant, or authorize production. `native_worker_attested=false` and
`production_authorized=false` remain mandatory in analyzer output.

## What changed from v1

V1 checked the claimed model digest and numeric batch size but could count one
self-reported backend batch containing requests from *different scopes or
generations*. It also had no exact batch member list or backend clock interval.
Those missing observations let a fabricated multi-request batch pass the
diagnostic's internal consistency tests, despite no actual native attestation.

V2 refuses such batches **before** emitting latency, RSS or throughput
diagnostics. Existing V1 backend-batch events **must** be upgraded; there is no
v1 fallback, permissive mode or advisory ignore.

## Required trace fields

For every `request` event, preserve the existing exact workload request ID,
model digest, scope, generation and explicit `cold_encoder` /
`cache_hit_head` path. Record `enqueued_us`, `start_us`, `end_us`, CPU
microseconds and RSS bytes as nonnegative **integers**. Never use the generated
`submitted_at_us` scheduling offsets as true timestamps.

Every `backend_batch` event requires:

```json
{
  "kind": "backend_batch",
  "batch_id": "batch-001",
  "backend": "native_hepta",
  "batch_size": 2,
  "model_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "scope": "qualification_shard_0",
  "generation": 1,
  "member_request_ids": ["request-001", "request-002"],
  "backend_started_us": 12000,
  "backend_ended_us": 12500
}
```

The member IDs must identify **exactly** the successful cold-Encoder
requests referring to that batch, with no duplicate, missing, orphan, extra
or cached member. The native Worker batch cap is 32, so `batch_size` must
be in `[1, 32]`. All members must have identical model, scope and generation,
and these identities must match the batch-level echo. For each member:

```text
enqueued_us <= start_us <= backend_started_us
backend_started_us <= backend_ended_us <= end_us
```

This is only a same-clock **internal consistency check**. Neither an arbitrary
JSON label `native_hepta` nor a SHA-256 content digest is a signature from
an independently trusted Observer or Worker.

## Report semantics

The analyzer emits `hepta.stem-cell-scale-observation.v2` with
`trace_claimed_multi_request_batches`. It **does not** emit the old
misleading `actual_backend_multi_request_batches` field: the number of
independently authenticated/fused native backend batches remains `null`
under `independently_verified_backend_multi_request_batches`.

To elevate a v2 diagnostic beyond research, a separately trusted native
owner must bind the exact source SHA, model/CAS signatures, queue and backend
timing clocks, Scope/Generation/Revocation fence, member IDs, WAL fsync,
restart/checksum, real process CPU/RSS (and GPU if applicable), and target
host identity to verifiable observation receipts. The existing P0 security,
P1 production lifecycle, P2 real Encoder and P4 independent NDU gates must
still pass; a v2 diagnostic alone is not P3 acceptance.

## Cache lineage, workload-size honesty and resource checks

The analyzer refuses to count a self-declared `cache_hit_head` unless a
successful cold-Encoder request for the **identical declared input key** has
already completed within the same model, Scope and Generation, before the
cache-hit request's start time. A pre-warmed cache from before the trace is
not eligible for this v2 diagnostic without a separately signed owner
witness and a new explicit protocol. Even a matching input key is only
self-reported consistency, **not** independent proof of feature reuse.

Every workload declares one registered (logical Cell size, active fraction,
input repeat fraction, task similarity) scenario and contains exactly
`ceil(logical_cells * active_fraction)` distinct Cell intents. A trace
cannot label seven requests as a fully observed 4096-Cell stress run.
WAL fsync counters must be nonnegative integers, and recovery time must
be finite with an explicit boolean checksum-verified flag.

The output includes `cache_hit_evidence` and
`independently_verified_cache_hit_fraction=null` to separate an
internally consistent cache claim from real signed native cache receipts.
No value here authenticates real CPU/RSS, a native Worker, or 4096-Cell
production throughput.

## Adversarial tests

`test_stem.py::ScaleTraceTests` includes reject cases for:
mixed scope, mixed generation, forged batch identity, missing/duplicate
members, unbounded batch width, impossible batch timing intervals, and
noninteger/bogus resource counters. Success cases verify that the results
remain explicitly non-authorizing.
