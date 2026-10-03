use crate::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[test]
fn complete_original_dataset_codec_preserves_native_receipt_and_public_principal() {
    let d = |v: &str| Digest32::of_bytes(v.as_bytes());
    let id = |v: &str| StableId::new(v.to_owned()).expect("fixture id");
    let producer = AuthenticatedPrincipalV1 {
        principal_id: id("original.dataset.owner"),
        credential_chain_digest: d("chain"),
        signing_key_digest: d("public key"),
        scope_digest: d("original training scope"),
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 60,
    };
    let mut records = vec![d("decision"), d("outcome")];
    records.sort();
    let original = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("whole.dataset"),
            producer,
            ledger_head_digest: d("whole head"),
            objective_digest: d("objective"),
            eligible_frontier: 3,
            outcome_watermark: 19,
            correction_cut_digest: d("correction"),
            revocation_cut_digest: d("revocation"),
            inclusion_policy_digest: d("inclusion"),
            source_record_digests: records,
            pending_outcomes: 1,
            censored_outcomes: 1,
        },
        20,
    )
    .expect("original receipt codec");
    let bytes =
        serde_json::to_vec(&ReviewDatasetWireV1::from_native(&original)).expect("whole wire");
    assert!(
        std::str::from_utf8(&bytes)
            .expect("JSON")
            .starts_with("{\"snapshot_id\":\"whole.dataset\",\"ledger_head_digest\":")
    );
    let decoded: ReviewDatasetWireV1 = serde_json::from_slice(&bytes).expect("common public wire");
    assert_eq!(decoded.native().expect("full native receipt"), original);
    assert_eq!(
        serde_json::to_vec(&decoded).expect("canonical field order"),
        bytes
    );
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("fixture value");
    let mut unknown = value.clone();
    unknown["extra_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<ReviewDatasetWireV1>(unknown).is_err());
    let mut principal = serde_json::to_value(&decoded.producer).expect("whole principal");
    principal["extra_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<PrincipalWire>(principal).is_err());
    value["authority_grants_any"] = serde_json::json!(true);
    assert!(
        serde_json::from_value::<ReviewDatasetWireV1>(value.clone())
            .expect("wire")
            .native()
            .is_err()
    );
    value["authority_grants_any"] = serde_json::json!(false);
    value["source_record_digests"] = serde_json::json!(vec![d("record").to_string(); 4097]);
    assert!(
        serde_json::from_value::<ReviewDatasetWireV1>(value)
            .expect("wire")
            .native()
            .is_err()
    );
    #[cfg(all(target_os = "linux", feature = "review-host"))]
    {
        let legacy: crate::review_host::ReviewDatasetWireV1 =
            serde_json::from_slice(&bytes).expect("old alias");
        assert_eq!(serde_json::to_vec(&legacy).expect("old bytes"), bytes);
    }
}
