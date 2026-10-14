use super::*;

#[cfg(unix)]
#[test]
fn adapter_uses_same_durable_control_owner_for_reads_and_checkpoint_publication() {
    use codex_hepta_types::Generation;
    let dir = tempfile::tempdir().expect("private root");
    let scope = StableId::new("subject").unwrap();
    let snapshot = NduSnapshotRefV1 {
        scope_id: scope.clone(),
        owner_id: StableId::new("ndu-owner").unwrap(),
        generation: Generation::new(1).unwrap(),
        route_fence: 1,
        revocation_epoch: 1,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"head"),
    };
    let owner = Arc::new(
        NduPublicationOwnerV1::open_production(
            &dir.path().join("ndu-control.wal"),
            snapshot.clone(),
            Digest32::ZERO,
        )
        .expect("durable owner"),
    );
    let adapter = ControlNduFrontierAdapterV1::new(owner.clone());
    assert_eq!(adapter.latest(&scope).unwrap(), snapshot);
    assert_eq!(
        adapter.check_checkpoint_publisher(&snapshot, Digest32::ZERO),
        Ok(())
    );
    let mut stale = snapshot.clone();
    stale.route_fence += 1;
    assert_eq!(
        adapter.check_checkpoint_publisher(&stale, Digest32::ZERO),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
    let next = Digest32::of_bytes(b"checkpoint");
    let head = adapter
        .compare_and_publish_checkpoint(
            &snapshot,
            Digest32::of_bytes(b"authenticated-read"),
            Digest32::of_bytes(b"tick"),
            Digest32::ZERO,
            next,
        )
        .expect("Control atomic CAS");
    assert!(!head.is_zero());
    assert_eq!(owner.current().unwrap().1, next);
    // A matching snapshot with an older checkpoint cannot start another tick.
    assert_eq!(
        adapter.check_checkpoint_publisher(&snapshot, Digest32::ZERO),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
    assert_eq!(adapter.check_checkpoint_publisher(&snapshot, next), Ok(()));
    assert!(adapter.latest(&StableId::new("other").unwrap()).is_err());

    // CNS uses the same exclusive Control lane; the earlier signed read
    // cannot publish a second checkpoint after the route has advanced.
    let mut successor = snapshot.clone();
    successor.route_fence += 1;
    let cutover = owner
        .publish_cutover(&snapshot, successor.clone(), next)
        .expect("durable CNS cutover");
    assert!(!cutover.is_zero());
    assert_eq!(adapter.latest(&scope).unwrap(), successor);
    assert_eq!(
        adapter.check_checkpoint_publisher(&snapshot, next),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
    assert_eq!(
        adapter.compare_and_publish_checkpoint(
            &snapshot,
            Digest32::of_bytes(b"authenticated-read"),
            Digest32::of_bytes(b"stale-tick"),
            next,
            Digest32::of_bytes(b"stale-checkpoint"),
        ),
        Err(NduReadVerificationErrorV1::CheckpointPublicationUnavailable)
    );
    assert_eq!(owner.current().unwrap().1, next);
}
