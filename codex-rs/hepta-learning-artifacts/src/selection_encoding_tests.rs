use super::*;

fn selection(kind: ArtifactKind, predecessor_id: Option<StableId>) -> SignedArtifactSelectionV1 {
    let id = StableId::new("roundtrip").unwrap();
    let digest = Digest32::of_bytes(b"persisted-selection-roundtrip");
    SignedArtifactSelectionV1 {
        selection_id: id.clone(),
        artifact_id: id.clone(),
        registry_id: id.clone(),
        withdrawal_scope_digest: digest,
        registry_head_digest: digest,
        current_witness_digest: digest,
        current_trust_digest: digest,
        artifact_kind: kind,
        artifact_generation: Generation::new(2).unwrap(),
        predecessor_id,
        content_digest: digest,
        objective_digest: digest,
        support_digest: digest,
        compatibility_digest: digest,
        encoded_size_bytes: 1024,
        selector_id: id,
        selector_credential_digest: digest,
        signing_key_digest: digest,
        authority_epoch: 2,
        issued_at: 10,
        expires_at: 100,
        signature: [7; 64],
    }
}

#[test]
fn persisted_selection_roundtrips_kinds_and_optional_predecessors() {
    for kind in [
        ArtifactKind::Prompt,
        ArtifactKind::Policy,
        ArtifactKind::Model,
        ArtifactKind::Workflow,
        ArtifactKind::Skill,
        ArtifactKind::Parameters,
        ArtifactKind::Topology,
        ArtifactKind::Code,
        ArtifactKind::ExternalAdapter,
        ArtifactKind::SensorCore,
    ] {
        for predecessor in [None, Some(StableId::new("previous").unwrap())] {
            let expected = selection(kind, predecessor);
            assert_eq!(
                SignedArtifactSelectionV1::from_persisted_bytes(&expected.persisted_bytes())
                    .unwrap(),
                expected
            );
        }
    }
}

#[test]
fn persisted_selection_rejects_every_torn_prefix_and_trailing_data() {
    let bytes = selection(ArtifactKind::Policy, None).persisted_bytes();
    for length in 0..bytes.len() {
        assert!(
            SignedArtifactSelectionV1::from_persisted_bytes(&bytes[..length]).is_err(),
            "accepted torn record at {length}"
        );
    }
    let mut trailing = bytes;
    trailing.push(0);
    assert!(SignedArtifactSelectionV1::from_persisted_bytes(&trailing).is_err());
}

#[test]
fn persisted_selection_rejects_oversized_identity_before_allocation() {
    let mut bytes = selection(ArtifactKind::Policy, None).persisted_bytes();
    bytes[DOMAIN.len()..DOMAIN.len() + 8].copy_from_slice(&u64::MAX.to_be_bytes());
    assert!(SignedArtifactSelectionV1::from_persisted_bytes(&bytes).is_err());
    assert!(
        SignedArtifactSelectionV1::from_persisted_bytes(&vec![0; MAX_SELECTION_BYTES + 1]).is_err()
    );
}
