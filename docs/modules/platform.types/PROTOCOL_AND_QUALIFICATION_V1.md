# `platform.types` protocol and qualification contract V1

This document is the current protocol/qualification supplement to
`TECHNICAL.md`. Where target architecture prose is broader than the current
source, this document and `CURRENT_IMPLEMENTATION.md` define the executable
claim boundary.

## 1. Sources of truth

The public Rust API is closed-world:

- source: `codex-rs/hepta-types/src/lib.rs`;
- generated inventory:
  `docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json`;
- generator/verifier: `scripts/platform_types_public_api.py`;
- module truth matrix:
  `docs/lane-a-foundation/platform.types/TRUTH_MATRIX_V1.json`;
- implementation map:
  `docs/modules/platform.types/IMPLEMENTATION_MAP.json`;
- execution dossier:
  `qualification/module-execution-dossiers/detail/platform.types.md`.

Every `pub use` must have one explicit source module and operation owner. A
symbol cannot appear by convention or an allowlisted anchor alone.

## 2. Runtime topology commitment

The V1 candidate semantic digest is:

```text
HPTC(
  type = platform.types:runtime-topology-candidate-v1,
  schema = 1,
  baseline_generation,
  candidate_generation,
  candidate_id,
  changed,
  deltas,
  evaluation_digest,
  proposal_digest,
  rollback_predecessor_digest,
  selected_topology_digest
)
```

Each delta is independently reduced to:

```text
HPTC(
  type = platform.types:runtime-topology-delta-v1,
  schema = 1,
  candidate_digest,
  evidence_digest,
  module_id,
  operation,
  predecessor_digest,
  related_module_ids
)
```

The stored candidate digest is derived and is not an input to itself.

`deltas` and `related_module_ids` are sets at the protocol level. Their sole V1
wire/native representation is a sequence in strictly increasing `StableId`
order. Implementations must reject duplicate, self-referential or
non-canonical sequences; they must not silently sort because doing so would
hide producer non-conformance.

Every semantic field has a mutation-completeness test. Mutating one field must
change the recomputed commitment. Mutating only the stored derived digest must
leave recomputation unchanged and make validation fail.

## 3. Manifest transport and semantic identity

The three owned V1 manifest transports are strict JSON objects. Their schemas
are:

- `schemas/random-stream-manifest-v1.schema.json`;
- `schemas/external-system-manifest-v1.schema.json`;
- `schemas/sensor-calibration-manifest-v1.schema.json`.

Transport rules:

- unknown fields reject;
- missing fields reject;
- enum values are closed;
- timestamps are canonical UTC `Z`;
- i64/u64 values are canonical base-10 strings;
- range, ordering and non-zero digest constraints are revalidated by the
  native contract.

Canonical JSON is not the semantic hash format. JSON member order, whitespace
and escaping are transport details. After strict validation, each language
projects values into the same typed field map and computes the HPTC semantic
commitment. `MANIFEST_V1_CONFORMANCE.json` is the shared accept/reject and
digest oracle for Rust, Python and Node.

## 4. Registry-bound numeric evidence

Pure rescaling and registry admission are separate evidence classes.

`NumericConversionReceiptV1` binds deterministic arithmetic. It does not prove
that a profile or normalizer was registered.

`RegisteredNumericConversionReceiptV1` additionally binds:

- registry generation;
- registry digest;
- source profile definition digest;
- target profile definition digest;
- normalization definition digest;
- base conversion receipt digest.

A consumer must require the registered receipt when registry admission is part
of its authorization or production policy.

## 5. Qualification identities

Two candidate classes exist:

- `source-head`: the exact branch source SHA/tree;
- `synthetic-merge`: the exact deterministic merge SHA/tree evaluated by the
  merge-candidate job.

Receipts must encode their candidate class. They are not interchangeable.
Exact candidate identity is injected by CI; it is not hand-written into a
self-referential committed document.

The implementation map uses an observation-base pattern: a map-only commit may
observe the immediately preceding content commit. The map file itself is
excluded from its own evidence hash set. Any later change to mapped source,
tests, documents or workflows requires a new observation-base update.

## 6. Diagnostics and authority

Truth, native, consumer and final-gate outcomes are independent. All available
diagnostics should be retained even when one check fails. An authoritative
qualification receipt may be emitted only when every required outcome in the
same candidate job is successful.

No receipt grants product activation, deployment, operator acceptance,
promotion or release. Those remain separate authorities.

## 7. Required reproduction

```text
python3 scripts/platform_types_public_api.py
python3 scripts/verify_lane_a_foundation.py verify
python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py
node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs
bash scripts/run_platform_types_consumer_qualification.sh
```

Any change to a public export, digest field, schema, validation rule or
candidate identity requires updated vectors/tests and exact-candidate
qualification.
