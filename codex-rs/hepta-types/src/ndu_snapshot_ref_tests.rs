use super::*;

fn sample() -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        scope_id: StableId::new("subject").unwrap(),
        owner_id: StableId::new("ndu-owner").unwrap(),
        generation: Generation::new(7).unwrap(),
        route_fence: 9,
        revocation_epoch: 11,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"head"),
    }
}

#[test]
fn every_binding_dimension_changes_digest() {
    let initial = sample();
    let original = initial.semantic_digest().unwrap();
    let mut tampered = initial.clone();
    tampered.scope_id = StableId::new("other").unwrap();
    assert_ne!(tampered.semantic_digest().unwrap(), original);
    tampered = initial.clone();
    tampered.route_fence += 1;
    assert_ne!(tampered.semantic_digest().unwrap(), original);
    tampered = initial.clone();
    tampered.revocation_epoch += 1;
    assert_ne!(tampered.semantic_digest().unwrap(), original);
    tampered = initial.clone();
    tampered.projection_head_digest = Digest32::of_bytes(b"new-head");
    assert_ne!(tampered.semantic_digest().unwrap(), original);
}

#[test]
fn refuses_missing_projection_or_fence() {
    let mut value = sample();
    value.route_fence = 0;
    assert_eq!(
        value.semantic_digest(),
        Err(NduSnapshotRefErrorV1::InvalidFence)
    );
    value = sample();
    value.projection_head_digest = Digest32::ZERO;
    assert_eq!(
        value.semantic_digest(),
        Err(NduSnapshotRefErrorV1::EmptyDigest)
    );
}
