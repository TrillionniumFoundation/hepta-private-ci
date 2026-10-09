use super::*;
fn snapshot() -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        scope_id: StableId::new("subject").unwrap(),
        owner_id: StableId::new("owner").unwrap(),
        generation: Generation::new(4).unwrap(),
        route_fence: 5,
        revocation_epoch: 6,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"head"),
    }
}

#[test]
fn strictly_binds_scope_generation_and_snapshot() {
    let s = snapshot();
    let tick = Digest32::of_bytes(b"tick");
    let read = Digest32::of_bytes(b"read");
    let bound = bind_ndu_snapshot_stage_v1(
        &s.scope_id, s.generation, s.snapshot_digest, tick, &s, read
    ).unwrap();
    assert_eq!(bound.authority, AuthorityPosture::DENY_ALL);
    let mut forged = s.clone();
    forged.projection_head_digest = Digest32::of_bytes(b"other");
    let forged_bound = bind_ndu_snapshot_stage_v1(
        &forged.scope_id, forged.generation, forged.snapshot_digest, tick, &forged, read
    ).unwrap();
    assert_ne!(forged_bound.binding_digest, bound.binding_digest);
    assert_eq!(
        bind_ndu_snapshot_stage_v1(&StableId::new("wrong").unwrap(), s.generation, s.snapshot_digest, tick, &s, read),
        Err(NeuronStageBindingErrorV1::ScopeMismatch)
    );
    assert_eq!(
        bind_ndu_snapshot_stage_v1(&s.scope_id, Generation::new(5).unwrap(), s.snapshot_digest, tick, &s, read),
        Err(NeuronStageBindingErrorV1::GenerationMismatch)
    );
    assert_eq!(
        bind_ndu_snapshot_stage_v1(&s.scope_id, s.generation, Digest32::of_bytes(b"wrong"), tick, &s, read),
        Err(NeuronStageBindingErrorV1::SnapshotMismatch)
    );
    assert_eq!(
        bind_ndu_snapshot_stage_v1(&s.scope_id, s.generation, s.snapshot_digest, tick, &s, Digest32::ZERO),
        Err(NeuronStageBindingErrorV1::MissingReadReceipt)
    );
}
