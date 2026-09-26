# platform.types: implementation and qualification dossier

Parent guides:

- `docs/modules/platform.types/TECHNICAL.md`
- `docs/modules/platform.types/PROTOCOL_AND_QUALIFICATION_V1.md`

Lane: `LANE-A-FOUNDATION`.

Status: native foundational contracts, registry-bound numeric evidence,
prompt-delivery/topology contracts, three manifest contracts, strict manifest
JSON codecs and cross-language semantic vectors are source implemented.
Exact-candidate source-head and synthetic-merge qualification remain separate
until their retained receipts pass for the current candidate.

## 1. Source and ownership envelope

Root: `codex-rs/hepta-types`. The crate is stateless and authority-free. It
owns validation and deterministic semantic commitments, not collection,
execution, authentication, deployment or release.

The closed-world public API inventory is
`docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`; the module-scoped
truth matrix is
`docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`. The inventory is
regenerated from `src/lib.rs`, and every public export has one source module
and one operation owner. Unregistered exports fail qualification.

## 2. Protocol contracts

### Runtime topology

`RuntimeTopologyCandidateV1::content_digest()` uses HPTC V1 and commits:

- proposal and candidate identity;
- baseline and candidate generation;
- selected topology, evaluation and rollback predecessor digests;
- changed state;
- every delta and every delta semantic field.

`candidate_digest` is derived and excluded from its own preimage. Candidate
`deltas` and each delta's `related_module_ids` are set semantics encoded as a
strictly increasing `StableId` order. Duplicate, self or non-canonical order
fails closed. Mutation-completeness tests cover every semantic field.

### Registered numeric conversion

`RegisteredNumericConversionReceiptV1` binds the immutable registry generation
and digest, source/target profile definitions, normalizer definition and base
conversion evidence. It cannot be substituted with a pure
`NumericConversionReceiptV1`.

### Manifest protocols

`RandomStreamManifestV1`, `ExternalSystemManifestV1` and
`SensorCalibrationManifestV1` use private fields, bounded constructors,
validation and HPTC semantic digests. Their schemas define strict JSON
transport; unknown fields and non-canonical integers reject. JSON bytes are not
hashed as semantic evidence. The validated projection is the HPTC semantic
commitment.

i64/u64 fields are canonical decimal strings in JSON. This prevents silent
JavaScript precision loss while keeping transport distinct from native numeric
semantics.

## 3. Public API truth closure

`scripts/platform_types_public_api.py` parses every `pub use` in
`codex-rs/hepta-types/src/lib.rs`. It rejects:

- unsupported export syntax;
- duplicate exports;
- a new public symbol without explicit operation ownership;
- a removed registered symbol;
- a symbol moved between source modules without an ownership change;
- inventory drift;
- missing operation owners in the implementation map;
- stale inventory counts in the truth matrix;
- missing protocol and provenance statements in current documentation.

The inventory currently records 78 exports, 11 source modules and 17 operation
owners. These counts are computed, not manually asserted.

## 4. Verification matrix

Shared manifest evidence:

- `codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json`;
- three strict JSON schemas under `codex-rs/hepta-types/schemas/`;
- `conformance/verify_manifest_vectors.py`;
- `conformance/verify_manifest_vectors.mjs`;
- `tests/manifest_protocol_consumer.rs`.

The consumer qualification runs 19 independent checks. A failing command does
not suppress later diagnostics. The aggregate remains failed if any command
fails. The evidence record includes each exit code, duration and log SHA-256.

The selected matrix covers canonical vectors, rejection vectors, generated
binding drift, Python/Node generated bindings, Python/Node manifest codecs,
Rust external manifest consumption, multi-crate consumer compile, complete
types and NDU tests, prompt producer, prompt ledger, topology consumer and
strict Clippy.

## 5. Candidate identity and receipts

Committed documentation cannot truthfully embed the SHA of the commit that
contains itself. The repository therefore uses two non-interchangeable layers:

1. the implementation map observes the immediately preceding content commit;
2. Lane A injects the exact checked-out candidate SHA and tree into provenance,
   diagnostics and authoritative receipts.

Source-head and synthetic-merge receipts must name their candidate kind and
exact SHA/tree. Neither receipt class can qualify the other candidate. A
receipt is authoritative only when truth, native, consumer and final-gate
outcomes all passed in the same job.

Diagnostics are retained on failure, but a failure diagnostic is never promoted
to a qualification receipt.

## 6. Durability, authority and non-claims

There is no authoritative mutable state, transaction log, recovery protocol or
effect owner in `platform.types`. No manifest executes randomness, inventories
a host or drives a sensor. No observation or candidate grants authority.

Production activation, target-host qualification, independent acceptance,
promotion and release remain false. External registry provisioning and the
runtime owners of described systems remain separate.

## 7. Reproduction commands

```text
python3 scripts/verify_lane_a_foundation.py verify
python3 scripts/platform_types_public_api.py
python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
```

Topology producers must supply all set-valued IDs in strictly increasing
`StableId` order. Manifest producers must treat JSON transport as strict
transport only and preserve the HPTC semantic commitment at every durable or
cross-owner boundary.
