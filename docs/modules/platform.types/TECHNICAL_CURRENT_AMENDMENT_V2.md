# `platform.types` current technical amendment V2

This amendment records versioned protocol corrections without deleting the
architecture, work-package, compatibility or readiness history in `TECHNICAL.md`.
The current guide and `CURRENT_IMPLEMENTATION.md` now incorporate these facts.
The latest resource/admission changes are specified in
`OPTIMIZATION_CLOSURE_20260929.md`.

## 1. Normative precedence

Use native contracts and the typed Rust catalog, then executable schemas and
strict codecs, then same-candidate Git/rustdoc/execution evidence, then explanatory
prose. Historical generated inventory is navigation and ownership evidence; it
cannot override versioned native semantic bytes.

## 2. Versioned prompt identity

Prompt V1 retains its custom domain-separated, length-framed SHA-256 commitment.
It is not HPTC and its existing bytes are never reinterpreted. Prompt V2 uses a
distinct private-field HPTC schema-2 contract, optionally carrying the exact V1
digest as a migration witness.

V2 token positions fit a single frozen HPTC array and therefore admit at most
4096 strictly increasing items. Earlier V2 constructors admitted 4097..=8192
items that the native digest could not encode. That unsupported interval is now
rejected at admission; no old computable digest changes. V1 retains its 8192-item
bound and larger V1 records remain V1. Migration rejects rather than truncating.
Schema, compiled Rust catalog, Python/Node boundary checks and the real Rust
codec share the corrected limit and a frozen 4096-position digest.

## 3. Registry integrity and freshness

`RegisteredNumericConversionReceiptV2` binds registry generation/content digest,
source/target profile-definition digests, normalization-definition digest, the
canonical base conversion receipt digest and derived V2 admission digest.
`verify` proves internal integrity by full recomputation. `verify_for_snapshot`
first checks the supplied registry against the independently pinned digest,
requires exact generation/digest equality and then recomputes the receipt.
Authentication, publication and advancement of the current pin remain external
owner responsibilities.

The optimized V2 construction resolves immutable definitions once and calls the
same checked converter directly, avoiding a redundant V1 admission hash. It does
not cache verification, freshness, revocation or final-use acceptance. The
ordinary NDU V1 owner still uses V1 registered receipts and a configured registry
content digest; the existence of this V2 library API does not prove its V2 owner
migration. Earlier prose that described that migration as already composed was
incorrect.

## 4. Product wire ownership

`platform.wire` owns strict Rust codecs for Prompt V2, Topology V1 and the Random
Stream, External System and Sensor Calibration V1 manifests. All enforce a 64 KiB
raw-input bound and depth 16 before deserialization. Unknown/duplicate/missing
fields reject. i64/u64 values use canonical decimal strings of at most 20 bytes
and native range checks. Native constructors revalidate semantic rules; topology
returns a validated wrapper after digest recomputation.

JSON bytes are transport rather than semantic identity. The five product fuzz
paths now require that successful decoding produces a computable semantic digest
and an exact semantic-preserving encode/decode roundtrip.

## 5. Product-owner composition

Source boundaries include frozen Prompt V1 producer/ledger paths, Supervisor
topology validation, NDU V1 registry-admitted numeric evaluation, NDU random-stream
seed/context/span admission, Supervisor host/witness admission and Supervisor
sensor/hardware/generation/clock/failure-policy admission.

These are still non-authorizing receipts. Trusted-clock validity, observation
freshness, current authorization, counter consumption, registry authentication
and deployed product activation require the existing owners' separate evidence.
No mutable authority, clock or effect executor is added to the type library.

## 6. Public API, provenance and resource behavior

The top-level `pub use` inventory is a narrow projection. Complete public API
compatibility remains a rustdoc comparison across modules, types, methods,
fields, variants and signatures. Exact candidate provenance binds Git blobs,
root trees, source/head/base and workflow/documents; old observations cannot
qualify later bytes.

Buffered and incremental-digest APIs now share the same canonical encoder and
errors. Bounded owned String/Vec inputs normalize only excessive retained capacity;
borrowed constructors validate before allocation. These changes do not imply a
physical RSS bound or migration of every historical adapter.

## 7. Qualification and review

Source-head and deterministic synthetic merge remain non-interchangeable. Both
schema gates compare the compiled catalog with structural schemas and the Prompt
capacity/u32-width contract. Deep qualification retains all previous truth,
consumer, provenance, rustdoc, MSRV, native/strict-Clippy, Miri, fuzz and document
gates, and adds actual resource-probe execution plus per-sample allocation gates.
All 24 consumer checks remain required; empty Cargo/libtest selections fail.

Resource samples and report hashes are bound through the mandatory truth log.
Timing is diagnostic by default; a matched-environment baseline and explicit
threshold are required for cross-commit latency comparison. Synthetic verifier
tests are not performance measurements. See the closure document for exact
sampling and allocation metrics.

Only a formal eligible independent approval bound to the final current head can
satisfy the separate review gate. Author-written prose, old approvals, bot
comments, queued jobs and uploaded failure logs do not qualify the candidate.

## 8. Completion boundary

The source changes implement contract repairs, optimizations and stronger
qualification machinery. They do not assert that the final source/head and
synthetic merge have executed successfully. Those receipts, eligible independent
review and applicable owner/target-host/operator acceptance remain required.
Authenticated registry publication, activation, promotion and release are not
asserted by this amendment.
