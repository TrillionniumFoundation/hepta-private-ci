# cognitive.types wire contract

## Canonical JSON V1

Canonical wire bytes are UTF-8 JSON with lexicographically sorted object keys, no insignificant whitespace, integer-only numeric values, exact string code points, preserved array order, exact schema/version/contract identity and deny-unknown deserialization. Decode succeeds only when re-encoding the typed value produces the original byte sequence exactly.

Canonicalization ID: `canonical-json/sorted-keys/utf8/integer-only/no-whitespace/v1`

Unicode policy ID: `preserve-code-points/no-normalization/v1`

Digest algorithm ID: `sha-256/v1`

## Envelope

```json
{
  "contract": "MemoryWriteReceiptV1",
  "payload": {},
  "schema": "hepta.cognitive.memory-write-receipt.v1",
  "schemaVersion": 1
}
```

Consumers reject unknown schema IDs, versions and contract/schema combinations.

## Digest profiles

The compatibility digest remains:

```text
SHA256("hepta.cognitive.contract.canonical-json.v1\0" || contract_id || "\0" || canonical_payload_bytes)
```

New authority-bearing integrations use:

```text
SHA256(
  "hepta.cognitive.contract-domain.v1\0" ||
  schema_id || "\0" || u32_be(schema_version) || "\0" ||
  contract_id || "\0" || canonicalization_id || "\0" ||
  unicode_policy_id || "\0" || digest_algorithm_id || "\0" ||
  canonical_payload_bytes
)
```

The compatibility digest is not removed or silently changed. A caller states which profile it consumes.

## Write-receipt binding

`write_receipt::MemoryWriteReceiptV1` contains a self digest over all intent and outcome binding fields. This protects candidate, authorization, writer-fence, expected-snapshot, writer-identity and outcome bindings.

Rejected receipts use a tagged object with `state`, `rejectionCode`, optional observed snapshot digest and `retryable`. No record ID or record digest is permitted in that branch.

## Unicode

Strings are not normalized. Composed `café` and decomposed `cafe + U+0301` remain different byte sequences and different digests. Identifier-specific normalization requires a new registered schema/profile.

## Size and allocation

Every contract declares a maximum payload size. Collection caps are independent of byte caps. A decoder rejects oversize input before unbounded work. Serializer optimization may not alter canonical bytes.

## Golden vectors

The shared fixture is `qualification/cognitive-types-v1/golden-vectors-v2.json`. It is independently verified by Rust (`tests/domain_golden_vectors_v1.rs`), Python (`verify_domain_vectors.py`) and Node (`verify_domain_vectors.mjs`). Any implementation producing different canonical bytes or digests is incompatible.
