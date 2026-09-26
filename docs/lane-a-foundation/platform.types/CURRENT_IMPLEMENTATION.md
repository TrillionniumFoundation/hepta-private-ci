# `platform.types` current implementation

## Current executable contract

`codex-rs/hepta-types` is the authority-free Rust contract library for shared
Hepta values. The current source implements bounded values and identities,
HPTC V1, checked Q32 arithmetic, immutable contract registries, numeric-profile
admission, pure and registry-bound numeric conversion receipts,
`PromptDeliveryObservationV1`, `RuntimeTopologyCandidateV1`, and the three
owned manifest contracts.

The exact public Rust surface is machine-enumerated in
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`. The module-scoped
truth state is recorded in
`docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`. Both are verified
from `codex-rs/hepta-types/src/lib.rs`; a new, removed, duplicated or moved
`pub use` without an explicit operation owner fails Lane A truth verification.

`RuntimeTopologyCandidateV1::content_digest()` is an HPTC V1 commitment over
all semantic candidate fields and every semantic delta field. The stored
`candidate_digest` is the derived result and is deliberately not an input to
itself. `deltas` and `related_module_ids` have set semantics represented in
strictly increasing `StableId` order. Duplicate, self-referential or
non-canonical order rejects instead of being silently sorted.

The three manifest wire schemas use strict JSON transport: unknown fields,
unknown enum values, non-canonical integers and invalid bounds reject. JSON
member order and JSON bytes are not evidence. Validated values are projected
into the native contract field map and the HPTC semantic commitment is the
cross-language identity. Unsigned 64-bit and signed 64-bit values use canonical
base-10 strings in JSON so JavaScript cannot silently lose integer precision.

## Public symbols and source bindings

The generated inventory currently covers 78 exports from 11 private source
modules and assigns each export to one of 17 operation owners. It is generated
with:

```text
python3 scripts/platform_types_public_api.py --write
```

The inventory is closed-world, not an advisory list. `scripts/platform_types_public_api.py`
rejects unsupported re-export syntax, duplicate symbols, unregistered symbols,
or movement between source modules without an ownership update. The
implementation map must contain every operation owner and must explicitly bind
the inventory path and counts.

Key source bindings are:

- bounded values: `src/bounded.rs`;
- identities and deny-only authority posture: `src/identity.rs`;
- digest and HPTC primitives: `src/digest.rs` and
  `src/canonical_digest.rs`;
- Q32 values: `src/fixed.rs`;
- immutable registry and numeric profiles: `src/registry.rs` and
  `src/numeric_profile.rs`;
- pure and registered conversion receipts: `src/numeric_conversion.rs`;
- prompt delivery: `src/prompt_delivery.rs`;
- topology candidates: `src/topology.rs`;
- random-stream, external-system and sensor-calibration manifests:
  `src/manifests.rs`.

Current named consumers are the Codex adapter and learning ledger for prompt
delivery, the runtime supervisor for topology admission, and the authenticated
NDU owner for registry-admitted numeric utility signals. These source
callsites prove composition of the named contracts, not product activation.

## Durability and activation

`platform.types` is stateless. It owns no clock, filesystem path, network,
credential, mutable global registry, journal, recovery worker, durable writer,
model call or external effect. Registry generations are immutable caller-owned
inputs.

A plain `NumericConversionReceiptV1` proves deterministic arithmetic.
`RegisteredNumericConversionReceiptV1` additionally binds the immutable
registry generation and digest, source and target profile definitions,
normalization definition and the base arithmetic receipt. The two evidence
classes are intentionally non-interchangeable.

Production implementation, deployment qualification, activation and release
remain false until the exact source candidate and the deterministic synthetic
merge each complete their own Lane A qualification. A source-tree receipt
cannot qualify a synthetic merge and a synthetic-merge receipt cannot qualify
a source tree.

## Target-only design

The following remain outside this module's present source claim:

- authenticated product publication, rotation and distribution of registry
  generations;
- random-stream execution, host inventory collection and physical sensor
  calibration drivers;
- product-specific authorization, selection, promotion or release;
- target-host performance, MSRV and Miri qualification until their exact
  workflow receipts exist;
- independent semantic acceptance and operator canary approval.

The manifest JSON codecs are conformance codecs for the three owned contracts.
They do not turn arbitrary Rust domain structs into a general-purpose wire
platform and do not execute the systems described by a manifest.

## Known limits and non-claims

- `StableId` is bounded to 128 encoded bytes.
- HPTC V1 is bounded to 256 KiB, 4096 collection items and depth 16.
- Registries admit at most 256 entries and 256 KiB aggregate ordinary
  definition data.
- Numeric signals admit at most 4096 values and reject overflow.
- Manifest text, timestamps, ranges and confidence are explicitly bounded.
- UTC timestamps accept canonical `Z` form with at most six fractional digits.
- Manifest JSON rejects unknown fields and uses decimal strings for i64/u64.
- Topology delta and related-module sets must arrive in canonical order.
- Generated foundational bindings do not expose every Rust contract.
- No type in this crate grants runtime, write, selection, promotion or release
  authority.

Committed prose does not pretend to contain its own current commit SHA. The
implementation map observes the immediately preceding content commit, while
the Lane A job injects the exact checked-out SHA and tree into candidate
provenance, diagnostics and qualification receipts.

## Verification

The selected consumer qualification executes all checks independently and
retains each log. Its matrix includes Rust compilation and tests, strict Clippy,
canonical HPTC vectors, generated-binding drift checks, the prompt producer,
ledger consumer, topology consumer, and three independent manifest consumers:
Rust public API, Python and Node.

`codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json` contains shared accepted and
rejected vectors. The strict schemas are under
`codex-rs/hepta-types/schemas/`. Python and Node independently validate and
project JSON to HPTC; the Rust external-crate test constructs the native public
types and must produce the same digests.

Topology tests use mutation-completeness: changing each semantic candidate or
delta field changes the digest, while changing only the derived
`candidate_digest` does not change the recomputed content digest and causes
validation to reject.

Repository truth is checked by:

```text
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/platform_types_public_api.py
bash scripts/run_platform_types_consumer_qualification.sh
```

Exact-head success is established only by retained workflow receipts and
artifacts. Until those artifacts exist for the current head, qualification is
`exact_candidate_pending`.

## Integration prerequisites

A consuming owner must pin exact contract/profile IDs and, for registered
conversion, one immutable registry generation whose digest is bound into the
owner identity. Consumers must validate at their final use boundary and must
not reinterpret a pure conversion receipt as registry admission.

Manifest producers must first construct and validate the native manifest
contract, then preserve its HPTC semantic commitment through transport or
storage. JSON transport must remain strict, deny unknown critical fields and
retain parity with native validation.

Topology producers must emit deltas and related module IDs in strictly
increasing `StableId` order, preserve every committed digest and generation,
and allow the final supervisor boundary to recompute and compare the candidate
digest.
