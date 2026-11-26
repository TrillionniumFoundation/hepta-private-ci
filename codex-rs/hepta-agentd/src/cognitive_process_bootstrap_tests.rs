use super::*;
use crate::cognitive_process_evidence::SignedLearningEvidenceV1Raw;
use crate::cognitive_process_wire::Signature;

#[test]
fn bootstrap_paths_reject_symlink_alias_and_oversize_materials() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path().canonicalize().unwrap();
    let path = root.join("material");
    std::fs::write(&path, b"bounded material").unwrap();
    assert!(open_bounded_regular(&path, 4, FileAccess::Read).is_err());
    let first = open_bounded_regular(&path, 32, FileAccess::Read).unwrap();
    let same = open_bounded_regular(&path, 32, FileAccess::Read).unwrap();
    #[cfg(unix)]
    assert!(reject_aliases(&[&first, &same]).is_err());
    let alias = root.join("alias");
    std::fs::hard_link(&path, &alias).unwrap();
    #[cfg(unix)]
    {
        assert!(open_bounded_regular(&alias, 32, FileAccess::Read).is_err());
        assert!(open_bounded_regular(&path, 32, FileAccess::Recover).is_err());
    }
    #[cfg(not(unix))]
    let _ = (first, same);
    #[cfg(unix)]
    {
        let link = root.join("symlink");
        std::os::unix::fs::symlink(&path, &link).unwrap();
        assert!(open_bounded_regular(&link, 32, FileAccess::Read).is_err());
    }
}

#[test]
fn raw_evidence_round_trip_preserves_exact_signature_preimage_and_rejects_grants() {
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
    use codex_hepta_types::StableId;
    let evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("evidence").unwrap(),
        principal_id: StableId::new("principal").unwrap(),
        role: LearningEvidenceRoleV1::Selector,
        trust_digest: Digest32::of_bytes(b"trust"),
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        authority_epoch: 7,
        issued_at: 11,
        expires_at: 19,
        payload_digest: Digest32::of_bytes(b"payload"),
        signature: [91; 64],
    };
    let bytes = serde_json::to_vec(&SignedLearningEvidenceV1Raw::from(evidence.clone())).unwrap();
    let round_trip: SignedLearningEvidenceV1 =
        serde_json::from_slice::<SignedLearningEvidenceV1Raw>(&bytes)
            .unwrap()
            .into();
    assert_eq!(round_trip, evidence);
    assert_eq!(round_trip.signing_bytes(), evidence.signing_bytes());
    let mut injected: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    injected["verified"] = serde_json::json!(true);
    assert!(serde_json::from_value::<SignedLearningEvidenceV1Raw>(injected).is_err());
    assert!(serde_json::from_str::<Signature>(&format!("\"{}\"", "0".repeat(126))).is_err());
}

#[test]
fn raw_selection_cannot_accept_a_receipt_or_duplicate_field() {
    let raw = r#"{"selection_id":"first","selection_id":"second"}"#;
    assert!(serde_json::from_str::<SelfEvolutionSelectionRequestV1Raw>(raw).is_err());
    assert!(
        serde_json::from_str::<CognitiveProcessDescriptorV1>(r#"{"selection_receipt":{}}"#)
            .is_err()
    );
}

#[test]
fn raw_product_input_rejects_opaque_qualification_and_out_of_range_propensity() {
    use crate::cognitive_process_product::ProductReplayDescriptorV1;
    use crate::cognitive_process_wire::Probability;
    let injected = r#"{"qualification_receipt":{"receipt_seal":"caller-selected"}}"#;
    assert!(serde_json::from_str::<ProductReplayDescriptorV1>(injected).is_err());
    assert!(serde_json::from_str::<Probability>("4294967297").is_err());
    assert!(serde_json::from_str::<Probability>("-1").is_err());
    assert!(serde_json::from_str::<Probability>("0.5").is_err());
    assert!(serde_json::from_str::<Probability>("4294967296").is_ok());
}
