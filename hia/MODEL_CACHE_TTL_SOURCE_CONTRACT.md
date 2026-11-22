# Model-cache TTL comparator: isolated HIA source candidate

This source increment prepares `model_cache_ttl.hepta` to replace **only the
freshness comparison** in `ModelsCacheEntry::is_fresh` under the opt-in native
feature. The original entry type, Chrono timestamp parser/serializer, calendar,
leap-second and extended-year semantics, model catalog, ETag, client version,
file reads/writes and refresh logic remain unchanged. It does not solve the
unmaintained Chrono dependency advisory or imply a completed Codex rewrite.

## Wire and admission

The entry uses the existing borrowed-buffer/u32 profile. It receives **exactly
40 bytes** consisting of five little-endian u64 words: protocol version `1`,
`age.num_seconds()` as signed two's complement, `age.subsec_nanos()` as signed
two's complement, the validated TTL's whole seconds, and the validated TTL's
nanosecond remainder. The caller must derive `age` from the original
`Utc::now().signed_duration_since(fetched_at)` and the TTL from the original
`chrono::Duration::from_std(ttl)`. An unrepresentable TTL returns `false`
before calling the HIA comparator. The HIA comparator itself rejects zero TTL.

The exact result is eight output bytes containing little-endian u64 `0` or `1`,
with a full u32 status of `8`. An input shape or fractional/sign error returns
`4294967295`; insufficient output capacity takes precedence and returns
`4294967294`. Errors write **zero output bytes**. The caller must reject every
non-8 status, invalid result value and mismatched shape without treating them
as a cache miss or silently falling back to the Rust comparator. The workspace
is unused. The module checks all structural preconditions before its sole
store; a Rust wrapper must allocate separate live buffers and validate the
full wrapper return.

For valid signed ages, HIA's comparison is: zero TTL is stale; any negative
age (future fetched timestamp) is fresh; otherwise compare seconds and then
fractional nanoseconds with an inclusive boundary. This keeps future timestamp
freshness and exact nanosecond ties. Parsing and signed-duration construction
remain the original Rust/Chrono behavior, not an approximate Unix timestamp
substitute.

## Qualification still required

The independent literal file contains 18 positive/comparison rows and eight
malformed transport rows. `tests/test_model_cache_ttl_source.py` checks only
the authored source shape and arithmetic expectations; it does **not** execute
HIA or the original Rust oracle. The module is deliberately **not** entered
into `toolchain.json`, linked to Cargo, selected in any workflow or installed
in the CLI in this preparatory increment.

Promotion requires an independent source review, exact `toolchain.json` and
native build/receipt integration, B1/B2/B3 fixed-point compilation, real ABI
and no-write tests, a deterministic original-Rust-vs-native comparator corpus,
all existing model-manager cache owner tests in default and native modes,
strict Clippy, formatter and package/CLI linkage, full original CI across
platforms, then separately measured performance. Preserve every failure and
unknown launch. Production dispatch, platform qualification, performance,
whole Codex replacement and Rust retirement remain **false**.
