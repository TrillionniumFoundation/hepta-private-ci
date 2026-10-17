# platform.types protocol and resource closure — 2026-09-29

This document describes source changes and acceptance obligations. It is not a
pass receipt, independent approval, deployment authorization or target-host
performance claim. The integration line remains PR #1001 on
`codex/platform-types-production-convergence-20260925`; history is retained and
no force-push, main update, self-approval or parallel production path is required.

## Review layers and compatibility

The review layers are: (1) Prompt hashability and semantic fuzz regressions;
(2) bounded retained capacity, the shared canonical sink and immutable numeric
reuse; (3) allocation/timing measurement and strict regression verification;
(4) schema/consumer/deep qualification integration; (5) current documentation.
Each layer preserves the authority-free library. The benchmark allocator is
isolated in a diagnostic executable; it is never linked into the type library.

### Prompt admission correction

Frozen HPTC V1 admits 4096 items per container. V2 previously validated up to
8192 token positions but represented them as one HPTC array, so values above
4096 had no native semantic commitment. V2 now rejects that unsupported range
at construction, migration and strict wire ingress. It does not truncate.
The schema and Rust-generated catalog expose the same limit. The catalog's
16384-byte field value denotes decoded u32 payload, not JSON text or the HPTC
u64-tagged representation.

Prompt V1 still accepts 8192 positions and uses the same custom SHA-256 bytes.
A V1 value fitting V2 receives its exact V1 digest as an explicit witness.
A larger value remains readable V1; V2 migration fails without changing it.
All previously computable V2 digests and the frozen HPTC profile are unchanged.
A larger HPTC-backed representation needs a new protocol, not an in-place limit
increase or altered V2 preimage.

`prompt_v2_hashability.rs` and the actual product wire test cover 1, 4095, 4096,
4097, 8192 and 8193 positions. Python/Node use the same capacity cases. The
4096-position fixture has digest
`c499a4a2479291376878d2f3a506d342c7f96b3eaa0fea3d206aafcbaf5a4e36`.
The three implementations must agree on that commitment and reject the upper
boundaries. The schema gate checks compiled payload bounds, u32 width, required
nullable presence and the declared ordering invariant.

### Canonical and memory optimizations

`canonical_encode_v1` and `canonical_digest_v1` share `encode_fields` and every
nested-value encoder, sorter, validator and byte-budget check. The digest path
uses a SHA-256 sink and does not materialize the entire canonical preimage.
The buffered API and original golden vectors remain the byte oracle. New tests
compare all value tags, ordering, invalid labels, duplicate fields, container and
byte ceilings and nesting boundaries. A failure never publishes a partial hash.

Owned bounded String/Vec inputs retain their allocation when capacity is already
within the declared maximum; excessive capacity is normalized after validation.
Regressions exercise a one-megabyte reservation carrying a five-byte value and
pointer reuse for ordinary input. Borrowed constructors validate before copying.
The legacy owned `Into<String>` API can allocate before inspection; callers
admitting borrowed untrusted data should use `try_from_str`/`with_profile`.
This sequence does not claim that every historical external adapter has already
migrated, or that allocator bookkeeping/physical RSS equals logical capacity.

V2 numeric admission resolves profiles and normalization once and then uses the
existing pure checked conversion. It omits the previously unused intermediate
V1 admission hash. Compatibility tests reconstruct the previous result path and
compare entire V2 receipts across signed inputs and generations. Full receipt
recomputation and the independently pinned snapshot comparison remain mandatory.
Immutable reuse never becomes a cached current-authorization decision.

## Resource measurement and regression policy

The standalone `platform-types-semantic-bench` executes actual public APIs:

| Workload | Sizes | Measurement |
| --- | --- | --- |
| buffered versus streaming canonical digest | 8, 4096, 65536 payload bytes | paired semantic equality, allocation calls/bytes and elapsed time |
| immutable registry construction | 8, 256 entries | validated entries cloned into a new immutable snapshot; definition creation excluded |
| identity/digest lookup | 8, 256 entries | lookup of the same existing entry; no mutable cache |
| V2 numeric conversion and pinned verification | 8, 4096 elements | complete checked operation including result construction/destruction |

There are 16 named cases, 17 samples per case and 64 operations per sample.
Fixtures and eight warm-up operations are outside the measured interval. Hash
pairs alternate execution order. The allocation observer counts successful
GlobalAlloc allocation/reallocation calls and requested bytes; reallocation
records the new requested size. It is not live-memory, physical-heap or RSS
measurement. The observer performs only atomic accounting and forwards memory
ownership to `System` unchanged.

`medianNs` and `p95Ns` summarize the distribution of the 17 sample-average
operation times (each elapsed batch divided by 64). They are not individual
request tail-latency or service-level guarantees. p95 uses nearest rank.

Mandatory deterministic gates reject missing/duplicate/unknown samples, invalid
counts, zero elapsed time, every paired streaming allocation-byte non-improvement,
allocation-call regression and any allocation in immutable lookup. Raw data is
retained, not replaced with a success-only summary.

Shared-runner timing is diagnostic. An explicitly requested baseline comparison
additionally checks identical environment and harness fingerprints and enforces
both median and p95 ratios for every named case. The threshold is finite and
explicit (1 through 2). Operator control of CPU isolation, power/thermal state,
background load and baseline provenance still needs separate acceptance; the
report always retains `targetHostQualified=false` and `independentAcceptance=false`.

Reproduce from a clean checked-out candidate:

```sh
bash scripts/run_platform_types_resource_qualification.sh /tmp/platform-types-current
```

On an independently controlled host, an optional same-method baseline comparison
is requested explicitly:

```sh
PLATFORM_TYPES_RESOURCE_BASELINE=/retained/baseline/report.json \
PLATFORM_TYPES_MAXIMUM_LATENCY_RATIO=1.15 \
bash scripts/run_platform_types_resource_qualification.sh /tmp/platform-types-current
```

No numeric performance improvement is claimed by committed source. The legacy
registry benchmark remains a distinct versioned measurement with no host threshold.

## Qualification integration

Both exact source-head and deterministic synthetic-merge deep pipelines execute
the new resource gate under `truth`. Raw sample and report hashes are printed into
the mandatory truth log; the candidate receipt commits that log. The complete
consumer evidence directory is now inside the retained candidate artifact.
All 24 independent consumer checks remain. Cargo/libtest selections need actual
nonzero executed-test summaries; a compile-only or zero-match success cannot pass.
The command verifier checks the real Cargo entrypoint rather than stale `just`
command strings. Failures retain diagnostics and block receipt emission.

Python verifier tests use synthetic samples only. Local Python/Node conformance
and verifier success must never be relabeled as native Rust, strict Clippy,
Miri, libFuzzer, hosted qualification or target-host measurements.

## Existing product owners and remaining work

NDU's ordinary configured numeric owner uses the V1 registered receipt with a
frozen registry content digest. The V2 snapshot verifier is implemented in the
type library; its availability alone is not evidence that this owner already
pins and consumes V2 generations. That distinction corrects earlier prose.

Supervisor manifest admission binds identities and policy. Current calibration
validity and observation freshness require the existing product owner's trusted
clock and final-use check; random counter consumption/reuse requires its existing
execution owner. No clock, mutable registry, counter database or effect executor
is added to `platform.types` to manufacture those proofs.

Completion still requires current exact-head and merge execution, eligible
independent review of the final candidate, and separate owner/host/operator
acceptance where applicable. No queued run, uploaded diagnostic, source commit
or author-written document substitutes for those outcomes.
