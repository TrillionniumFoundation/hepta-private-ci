# platform.types: implementation and qualification dossier

Parent guides:

- `docs/modules/platform.types/TECHNICAL.md`
- `docs/modules/platform.types/TECHNICAL_CURRENT_AMENDMENT_V2.md`
- `docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md`
- `docs/modules/platform.types/NORMATIVE_PROTOCOL_SOURCE_V2.md`

Lane: `LANE-A-FOUNDATION`.

Status: core source, compatibility-preserving V2 protocols, strict product
codecs for all five transport contracts, named manifest owners and owner-pinned
registry verification are implemented. Exact-candidate source-head and
synthetic-merge qualification remain separate until retained receipts pass for
the final candidate. Independent current-head approval remains a separate merge
gate.

## 1. Source and ownership envelope

Root: `codex-rs/hepta-types`. The crate owns authority-free validation and
semantic commitments, not execution, authenticated registry publication,
deployment or release. `platform.wire` owns strict JSON transport. NDU and the
runtime supervisor own product-specific manifest admission.

The closed-world top-level ownership projection is
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`; it covers exact
`pub use` exports and exact public `pub mod` declarations. The module truth
matrix is `docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`.
Complete public API evidence is rustdoc-derived per candidate rather than
inferred from top-level exports alone.

## 2. Versioned protocol contracts

Prompt V1 remains frozen under its historical custom digest. Prompt V2 uses an
HPTC semantic commitment and can bind the exact V1 digest as an explicit
migration witness. There is no silent V1 reinterpretation.

Runtime topology HPTC binds every candidate and delta semantic field. The stored
candidate digest is derived. Delta and related-module sets have one canonical
representation: strictly increasing `StableId` order; duplicate, self and
non-canonical producers fail. The product codec returns a validated wrapper.

The three manifests use private native fields, bounded constructors and HPTC
semantic digests. Their strict schemas and cross-language vectors distinguish
JSON transport bytes from semantic identity.

Numeric admission V2 binds registry generation/digest, source and target profile
definition digests, normalization-definition digest and base conversion-receipt
digest. Its receipt is privately constructible and fully recomputed from native
inputs. `verify_for_snapshot` additionally compares the receipt with an
independently owner-pinned `RegistrySnapshotIdentityV1`; a valid receipt from an
older generation or different registry digest therefore fails current-owner
admission. The crate does not authenticate, publish or advance that pinned
snapshot.

## 3. Product wire and owner composition

`platform.wire` owns strict codecs for:

- `PromptDeliveryObservationV2`;
- `RuntimeTopologyCandidateV1`;
- `RandomStreamManifestV1`;
- `ExternalSystemManifestV1`;
- `SensorCalibrationManifestV1`.

Every decoder enforces raw byte/depth limits before Serde, rejects duplicate,
unknown and missing fields, uses canonical decimal strings for precision-
sensitive integers, and reconstructs the validated native value. The manifest
codecs live in `codex-rs/hepta-wire/src/platform_manifest_json.rs`; Prompt and
Topology live in `platform_types_json.rs`.

Current named product boundaries are:

- Codex/Agentd producer and Learning Ledger consumer for Prompt V1 compatibility;
- `platform.wire` strict codecs for all five product transports;
- Runtime Supervisor validated topology admission;
- authenticated NDU registered numeric evaluation plus owner-pinned V2 snapshot
  verification;
- NDU random-stream manifest admission bound to generator, episode, decision and
  counter window;
- Runtime Supervisor external-system manifest admission bound to system/class,
  host identity and authorization witness;
- Runtime Supervisor sensor manifest admission bound to sensor/class, hardware,
  generation, clock and failure policy.

Every owner receipt is deny-only evidence. Source composition does not imply
product activation.

## 4. Rust normative catalog and documentation

`protocol_catalog_v2.rs` is the typed source for protocol field/version/identity,
codec-owner and compatibility tables. A compiled generator verifies schema field
coverage and emits exact-candidate JSON and Markdown. Candidate documentation
bundles include those outputs; reviewers do not edit duplicate field tables.

The stable `TECHNICAL.md` retains long-form architecture and work-package
history. `TECHNICAL_CURRENT_AMENDMENT_V2.md` narrowly corrects its stale
executable-state claims without deleting that design material.

## 5. API and provenance closure

Rustdoc JSON snapshots cover the complete public API surface. Base/candidate
comparison fails on existing public item removal or fingerprint mutation and
reports additive paths separately.

Git provenance records exact candidate SHA/tree, root trees and every tracked
source/schema/doc/verifier/workflow blob. A committed observation base cannot
qualify later bytes. The candidate bundle explicitly tracks the technical
amendment, both strict-codec modules, consumer verifier, independent-review
verifier/tests and both platform.types workflows.

## 6. Verification matrix

The 24-check consumer matrix includes Rust, Python and Node semantic oracles,
strict product codecs for all five contracts, complete type and NDU tests,
prompt producer/ledger, topology admission, all three manifest product owners
and strict lint.

Deterministic property checks cover semantic leaf mutation, field removal,
unknown fields and JSON-order invariance. Pinned libFuzzer targets exercise raw
HPTC validation and strict product JSON decoding. MSRV, native, Miri, provenance,
rustdoc semver and generated catalog are distinct outcomes.

## 7. Candidate identity, review and receipts

Source-head and synthetic-merge receipts name exact, non-interchangeable
candidate identities. Diagnostics remain available on failure but never become
qualification receipts. The authoritative receipt is produced only when every
required outcome passes in one exact-candidate job.

Independent review is a separate governance outcome. The exact-head review gate
accepts only a decisive approval from a repository owner/member/collaborator who
is neither the PR author nor an author or committer of any candidate commit.
Stale approvals, bots, outsiders, dismissed reviews and a latest decisive
changes-requested state reject. Review evidence does not qualify source or
synthetic-merge execution.

## 8. Durability, authority and non-claims

`platform.types` has no authoritative mutable state, writer, transaction log,
recovery process or effect owner. V2 registry generation is caller-supplied and
owner-pinned evidence; the crate does not authenticate or advance the current
generation.

Random streams are not executed here, hosts are not inventoried here and sensors
are not operated here. Production activation, deployment qualification,
independent acceptance, promotion and release remain false.

## 9. Reproduction commands

```text
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/platform_types_public_api.py
python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
python3 codex-rs/hepta-types/conformance/verify_platform_wire_vectors.py
node codex-rs/hepta-types/conformance/verify_platform_wire_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
python3 scripts/test_platform_types_independent_review.py
```

Manifest and topology producers must preserve the HPTC semantic commitment at
cross-owner boundaries. Prompt migration must preserve the frozen V1 digest and
use V2 as a distinct identity. Generation-sensitive numeric owners must verify
against their independently pinned exact snapshot.
