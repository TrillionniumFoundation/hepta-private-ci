use codex_hepta_cognitive_types::contract::Validated;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_cognitive_types::wire::encode_payload_canonical_v1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GoldenVectorsV2 {
    memory_write_receipt_rejected_v1: ReceiptVectorV1,
    unicode_preservation_v1: Vec<UnicodeVectorV1>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReceiptVectorV1 {
    payload: serde_json::Value,
    canonical_payload_utf8: String,
    canonical_wire_utf8: String,
    receipt_digest_sha256: String,
    legacy_canonical_digest_sha256: String,
    domain_bound_digest_sha256: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UnicodeVectorV1 {
    text: String,
    utf8_hex: String,
    sha256: String,
}

fn vectors() -> GoldenVectorsV2 {
    serde_json::from_str(include_str!(
        "../../../qualification/cognitive-types-v1/golden-vectors-v2.json"
    ))
    .unwrap_or_else(|error| panic!("parse V2 golden vectors: {error}"))
}

#[test]
fn rejected_write_receipt_matches_python_and_node_golden_vector() {
    let vector = vectors().memory_write_receipt_rejected_v1;
    let receipt: MemoryWriteReceiptV1 = serde_json::from_value(vector.payload)
        .unwrap_or_else(|error| panic!("parse canonical write receipt: {error}"));
    receipt
        .validate()
        .unwrap_or_else(|error| panic!("validate canonical write receipt: {error}"));

    let canonical_payload = encode_payload_canonical_v1(&receipt)
        .unwrap_or_else(|error| panic!("encode canonical payload: {error}"));
    assert_eq!(
        String::from_utf8(canonical_payload)
            .unwrap_or_else(|error| panic!("canonical payload UTF-8: {error}")),
        vector.canonical_payload_utf8
    );

    let validated = Validated::from_cognitive_contract(receipt.clone())
        .unwrap_or_else(|error| panic!("validated canonical write receipt: {error}"));
    assert_eq!(
        String::from_utf8(
            validated
                .encode_wire_v1()
                .unwrap_or_else(|error| panic!("encode canonical wire: {error}"))
        )
        .unwrap_or_else(|error| panic!("canonical wire UTF-8: {error}")),
        vector.canonical_wire_utf8
    );
    assert_eq!(
        receipt.receipt_digest().to_string(),
        vector.receipt_digest_sha256
    );
    assert_eq!(
        canonical_contract_digest_v1(&receipt)
            .unwrap_or_else(|error| panic!("legacy canonical digest: {error}"))
            .to_string(),
        vector.legacy_canonical_digest_sha256
    );
    assert_eq!(
        validated
            .domain_bound_digest_v1()
            .unwrap_or_else(|error| panic!("domain-bound canonical digest: {error}"))
            .to_string(),
        vector.domain_bound_digest_sha256
    );
}

#[test]
fn unicode_golden_vectors_prove_code_point_preservation() {
    let entries = vectors().unicode_preservation_v1;
    assert_eq!(entries.len(), 2);
    let observed = entries
        .iter()
        .map(|entry| {
            let bytes = entry.text.as_bytes();
            let hex = bytes
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>();
            assert_eq!(hex, entry.utf8_hex);
            assert_eq!(
                codex_hepta_types::Digest32::of_bytes(bytes).to_string(),
                entry.sha256
            );
            (hex, entry.sha256.clone())
        })
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(observed.len(), entries.len());
}
