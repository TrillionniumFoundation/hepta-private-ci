use super::*;

#[cfg(unix)]
#[test]
fn adapter_uses_same_durable_control_owner_for_reads_and_checkpoint_publication() {
    use codex_hepta_types::Generation;
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().expect("private root");
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("Control WAL parent must be owner-only");
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

    // The public single-phase CNS cutover port is always unavailable. A
    // caller-supplied dummy success callback is NOT proof of the original
    // signed runtime effect. The candidate's real physical port remains
    // denied until a separately reviewed authenticated handoff is wired.
    let mut successor = snapshot.clone();
    successor.route_fence += 1;
    let original_control_bytes =
        std::fs::read(dir.path().join("ndu-control.wal")).expect("original durable Control WAL");
    #[allow(deprecated)]
    let denied = owner.publish_cutover(&snapshot, next, successor, next);
    assert_eq!(
        denied,
        Err(codex_hepta_control_plane::NduPublicationErrorV1::Unsupported)
    );
    assert_eq!(
        std::fs::read(dir.path().join("ndu-control.wal")).expect("denied direct C leaves WAL"),
        original_control_bytes
    );
    assert_eq!(adapter.latest(&scope).unwrap(), snapshot);
    assert_eq!(adapter.check_checkpoint_publisher(&snapshot, next), Ok(()));
    let subsequent = Digest32::of_bytes(b"second-model-checkpoint");
    assert!(adapter
        .compare_and_publish_checkpoint(
            &snapshot,
            Digest32::of_bytes(b"another-authenticated-read"),
            Digest32::of_bytes(b"second-tick"),
            next,
            subsequent,
        )
        .is_ok());
    assert_eq!(owner.current().unwrap().1, subsequent);
}
