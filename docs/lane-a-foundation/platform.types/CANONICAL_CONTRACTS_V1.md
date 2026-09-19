# Platform Types canonical contracts V1

This document freezes the current native canonical digest, profiled identifier
and schema/normalization registry contracts. It is an implementation-level
companion to `docs/modules/platform.types/TECHNICAL.md`, not an activation or
release claim.

## 1. Canonical digest bytes

`canonical_encode_v1(domain, fields)` emits:

1. ASCII bytes `HEPTA-CANONICAL-DIGEST-V1` followed by one NUL byte;
2. `u16be(domain_length)` and the lowercase ASCII domain;
3. `u16be(field_count)`;
4. for each field, in strictly byte-sorted unique name order:
   `u16be(name_length) || name || u8(type_tag) || u32be(value_length) || value`.

V1 type tags are: bytes=1, UTF-8 text=2, u64=3, i64=4, bool=5,
`Digest32`=6 and `StableId`=7. Integers are big-endian two's-complement where
applicable; bool is exactly `00` or `01`; digests are 32 raw bytes. Domain and
field names use `[a-z0-9._-]+`. Domain/name length is <=128 bytes, field count
is <=1024, and the complete canonical collection is <=256 KiB.

`canonical_digest_v1` is SHA-256 of exactly those bytes. Raw
`Digest32::of_bytes` remains available as a low-level primitive but does not
provide semantic domain separation or field framing.

## 2. Frozen cross-language vectors

The authority-free compatibility corpus is:

- `codex-rs/hepta-types/testdata/canonical_digest_v1_vectors.json`;
- Rust: `src/canonical_tests.rs`;
- Python: `scripts/verify_platform_types_vectors.py`;
- TypeScript: `scripts/verify_platform_types_vectors.ts` (Node 22 type stripping).

The mixed scalar vector freezes every V1 type tag and the empty-field vector
freezes the zero-field envelope. Any implementation that disagrees byte-for-byte
or digest-for-digest is incompatible with V1.

## 3. Profiled identifiers

`IdProfileV1` is a closed namespace profile over `StableId`. Current namespaces
are execution, schema, receipt, artifact, producer and normalization. Encoding is
`<namespace>:<local>`. Local parts are nonempty and contain only ASCII
alphanumeric, `.`, `_`, `-`. No normalization, case folding or nested `:` is
performed. `validate_id` checks the borrowed input before creating the bounded
owned `StableId`.

## 4. Authority posture

`AuthorityPosture` V1 intentionally represents only deny-all. The type has no
public authority-bearing fields. `from_untrusted_bits` accepts only zero and
rejects every nonzero bitmap, so qualification artifacts cannot carry a wider
authority value by caller convention or struct mutation.

## 5. Schema/normalization registry

`RegistryDefinitionV1` contains a registry kind, matching profiled ID, bounded
media type, nonzero schema version and <=64 KiB canonical body. Its key is the
`canonical_digest_v1` of those fields under domain
`platform.types.registry-definition`.

`SchemaNormalizationRegistryV1` is bounded to 256 entries. Re-registering the
same digest/definition is idempotent; unknown digests, kind mismatches, capacity
overflow and digest collisions reject. The registry is in-memory only and does
not claim a durable/global service.

## 6. Qualification boundary

Lane A runs the Rust suite, strict clippy and both cross-language vector
verifiers on exact PR head and on a deterministic synthetic merge. Those jobs
emit retained source/native receipt artifacts. Product composition, generated
bindings, host durability, independent acceptance, activation, promotion and
release remain separate gates.
