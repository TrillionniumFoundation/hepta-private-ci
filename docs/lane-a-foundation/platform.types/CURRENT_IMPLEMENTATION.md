# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is an authority-free Rust contract library. It owns
bounded byte/text values, profiled stable identifiers, nonzero monotonic
generation/revision/sequence values, raw SHA-256 digests, canonical framed
digests, immutable schema/normalization definitions, checked Q32 values and
registered numeric signal conversion. The crate forbids unsafe code and owns no
clock, network, filesystem, credential, process-global registry or durable
writer.

## Public symbols and source bindings

- `BoundedBytes`, `BoundedText`, `BoundedValueError`:
  `src/bounded.rs`.
- `StableId`, `IdProfileV1`, `validate_id`, `Generation`, `Revision`,
  `LogicalSequence`, `AuthorityPosture`, `NonAuthorizingPosture`,
  `IdentityError`: `src/identity.rs`.
- `Digest32`, `DigestParseError`: `src/digest.rs`.
- `CanonicalFieldV1`, `CanonicalValueV1`, `canonical_encode_v1`,
  `canonical_digest_v1`: `src/canonical_digest.rs`.
- `ContractDefinitionV1`, `ContractDefinitionKindV1`,
  `ContractRegistryV1`: `src/registry.rs`.
- `FixedQ32`, `ProbabilityQ32`: `src/fixed.rs`.
- `NumericProfileV1`, `NumericSignalV1`, `rescale_signal`,
  `rescale_signal_registered` and conversion receipts:
  `src/numeric_profile.rs` and `src/numeric_conversion.rs`.

`IdentityError` is exported from the crate root so consumers can name the
constructor error without depending on a private module path.

## Durability and activation

The module is stateless and has no durability. `ContractRegistryV1` is an
immutable caller-owned value, not an ambient or process-global registry. The
module is a library-only dependency; its values grant no runtime or effect
authority. New Platform Types receipts use `NonAuthorizingPosture`, a type
that cannot represent a granted authority flag. Legacy `AuthorityPosture`
remains a public compatibility/tamper representation for existing records and
negative tests and is not an authority token.

## Target-only design

Generated cross-language bindings, an ambient mutable runtime schema registry,
production numeric-profile admission and named product composition remain
target-only. The repository now freezes a language-neutral canonical-digest
vector and independently verifies it in Rust, Python and Node, but this does not
claim generated bindings or a production consumer.

## Known limits and non-claims

Rust type equality is not a frozen wire representation. `Digest32::of_bytes`
still performs raw SHA-256 and is appropriate only when the caller already owns
a frozen byte representation. Protocol owners that need structured semantic
digests should use `canonical_digest_v1`, whose domain separation, type tags,
field framing, ordering and bounds are versioned.

`IdProfileV1` validates namespace grammar; it does not make an identifier safe
for a filesystem path, URI, SQL identifier or other context. Generic bounded
values are not secret containers, and their debug representations must not be
used for credentials.

`ContractRegistryV1` resolves an immutable digest to an exact definition body. Schema definitions require `schema:*` IDs and normalization definitions require `normalization:*` IDs.
It does not provide network discovery, mutable registration, trust
distribution, production admission or process-global state.

## Verification

Native tests cover zero/MAX/MAX+1 bounds, UTF-8 byte boundaries, exhaustive
ASCII StableId grammar, namespace/profile mismatch, digest parsing/stability,
monotonic overflow, Q32 error boundaries, canonical framing/order/duplicate
rejection, immutable registry duplicate/kind/digest behavior, numeric profile
mismatch, overflow, rounding, normalization resolution and error bounds.

The frozen vector
`docs/lane-a-foundation/platform.types/CANONICAL_DIGEST_V1.json` is checked by
`src/canonical_digest_tests.rs`,
`scripts/verify_platform_types_vectors.py` and
`scripts/verify_platform_types_vectors.mjs`. `CAPABILITY_EVIDENCE_MAP.json`
binds each current capability to exact source and positive/negative tests.
Executed exact-head and synthetic-merge proof remains a workflow receipt, not a
static documentation assertion.

## Integration prerequisites

A consumer must name the semantic type and version, preserve exact values for
authority/fence fields, resolve required schema/normalization definitions from
an explicitly supplied immutable registry, and add a frozen wire contract before
making product or generated cross-language compatibility claims. Production
composition still requires a named caller and separate activation/acceptance
evidence.
