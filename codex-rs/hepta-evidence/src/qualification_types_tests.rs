use crate::EvidenceDispositionV1;
use crate::EvidenceId;
use serde_json::json;

#[test]
fn evidence_result_round_trips_without_a_store() -> Result<(), serde_json::Error> {
    let digest = "c".repeat(64);
    let mut value = json!({"state": "supported", "evidence": [{
        "evidence_id": "evidence.1", "claim_class": "exact_source", "receipt_kind": "evidence",
        "issuer_role": "reviewer", "issuer_principal_id": "reviewer.1",
        "payload_sha256": digest, "envelope_sha256": digest,
        "predecessor_evidence_id": null, "target_evidence_id": null,
        "observed_unix_ms": 1000, "expires_unix_ms": 2000
    }]});
    let decoded: EvidenceDispositionV1 = serde_json::from_value(value.clone())?;
    assert_eq!(serde_json::to_value(decoded)?, value);
    value["evidence"][0]["issuer_role"] = json!("self_authorized");
    assert!(serde_json::from_value::<EvidenceDispositionV1>(value).is_err());
    Ok(())
}

#[test]
fn invalid_identity_and_unknown_disposition_are_rejected() {
    assert!(serde_json::from_str::<EvidenceId>("\"\"").is_err());
    assert!(serde_json::from_value::<EvidenceDispositionV1>(json!({"state": "accepted"})).is_err());
    assert!(
        serde_json::from_value::<EvidenceDispositionV1>(
            json!({"state": "supported", "evidence": [], "accepted": true})
        )
        .is_err()
    );
}
