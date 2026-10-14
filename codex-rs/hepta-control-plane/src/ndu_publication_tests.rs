use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn snapshot(fence: u64) -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        scope_id: StableId::new("scope-1").unwrap(),
        owner_id: StableId::new("ndu-owner").unwrap(),
        generation: Generation::new(3).unwrap(),
        route_fence: fence,
        revocation_epoch: 7,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"projection"),
    }
}

#[cfg(unix)]
#[test]
fn production_owner_replays_checkpoint_and_requires_single_writer() {
    let dir = tempfile::tempdir().expect("owner-only dir");
    let path = dir.path().join("control-ndu.wal");
    let original = snapshot(3);
    let next = Digest32::of_bytes(b"checkpoint-one");
    {
        let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
            .expect("owner");
        assert!(
            NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
                .is_err()
        );
        let head = owner
            .compare_and_publish_checkpoint(
                &original,
                Digest32::of_bytes(b"verified-read"),
                Digest32::of_bytes(b"tick"),
                Digest32::ZERO,
                next,
            )
            .expect("durable publication");
        assert!(!head.is_zero());
        assert!(matches!(
            owner.compare_and_publish_checkpoint(
                &original,
                Digest32::of_bytes(b"verified-read"),
                Digest32::of_bytes(b"tick"),
                Digest32::ZERO,
                next,
            ),
            Err(NduPublicationErrorV1::Stale)
        ));
    }
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO),
        Err(NduPublicationErrorV1::Stale)
    ));
    let recovered = NduPublicationOwnerV1::open_production(&path, original.clone(), next)
        .expect("canonical checkpoint must match");
    assert_eq!(recovered.current().unwrap(), (original, next));
}

#[cfg(unix)]
#[test]
fn cutover_and_checkpoint_cas_use_same_exclusive_owner() {
    let dir = tempfile::tempdir().expect("private directory");
    let path = dir.path().join("frontier.wal");
    let previous = snapshot(3);
    let migrated = Digest32::of_bytes(b"migrated-checkpoint");
    {
        let owner = NduPublicationOwnerV1::open_production(&path, previous.clone(), Digest32::ZERO)
            .expect("owner");
        owner
            .publish_cutover(&previous, Digest32::ZERO, snapshot(4), migrated)
            .expect("cutover fsync");
        assert!(matches!(
            owner.compare_and_publish_checkpoint(
                &previous,
                Digest32::of_bytes(b"read"),
                Digest32::of_bytes(b"old-tick"),
                Digest32::ZERO,
                Digest32::of_bytes(b"old-checkpoint"),
            ),
            Err(NduPublicationErrorV1::Stale)
        ));
        assert_eq!(owner.current().unwrap(), (snapshot(4), migrated));
    }
    let recovered = NduPublicationOwnerV1::open_production(&path, snapshot(4), migrated)
        .expect("cutover replay");
    assert_eq!(recovered.current().unwrap(), (snapshot(4), migrated));
}


#[cfg(unix)]
#[test]
fn checkpoint_advance_invalidates_frozen_cutover_without_losing_new_state() {
    let dir = tempfile::tempdir().expect("private directory");
    let path = dir.path().join("ndu-frontier.wal");
    let original = snapshot(3);
    let committed = Digest32::of_bytes(b"new-neuron-checkpoint");
    let migrated = Digest32::of_bytes(b"stale-migration-checkpoint");
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("durable Control");
    owner
        .compare_and_publish_checkpoint(
            &original,
            Digest32::of_bytes(b"signed-read"),
            Digest32::of_bytes(b"tick"),
            Digest32::ZERO,
            committed,
        )
        .expect("model CAS must commit");
    assert_eq!(
        owner.publish_cutover(&original, Digest32::ZERO, snapshot(4), migrated),
        Err(NduPublicationErrorV1::Stale)
    );
    assert_eq!(owner.current().unwrap(), (original.clone(), committed));
    owner
        .publish_cutover(&original, committed, snapshot(4), migrated)
        .expect("refrozen migration may advance");
    assert_eq!(owner.current().unwrap(), (snapshot(4), migrated));
}

#[cfg(unix)]
#[test]
fn concurrent_model_and_cns_cas_cannot_both_commit_one_predecessor() {
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::thread;

    let dir = tempfile::tempdir().expect("private Control root");
    let path = dir.path().join("competing-ndu-frontier.wal");
    let old = snapshot(3);
    let committed = Digest32::of_bytes(b"concurrent-neuron");
    let migrated = Digest32::of_bytes(b"concurrent-migration");
    let owner = Arc::new(
        NduPublicationOwnerV1::open_production(&path, old.clone(), Digest32::ZERO)
            .expect("exclusive Control owner"),
    );
    let barrier = Arc::new(Barrier::new(3));
    let model_owner = Arc::clone(&owner);
    let model_barrier = Arc::clone(&barrier);
    let model_old = old.clone();
    let model = thread::spawn(move || {
        model_barrier.wait();
        model_owner.compare_and_publish_checkpoint(
            &model_old,
            Digest32::of_bytes(b"verified-read"),
            Digest32::of_bytes(b"model-tick"),
            Digest32::ZERO,
            committed,
        )
    });
    let cns_owner = Arc::clone(&owner);
    let cns_barrier = Arc::clone(&barrier);
    let cns_old = old.clone();
    let cns = thread::spawn(move || {
        cns_barrier.wait();
        cns_owner.publish_cutover(&cns_old, Digest32::ZERO, snapshot(4), migrated)
    });
    barrier.wait();
    let model_ok = model.join().expect("model thread").is_ok();
    let cns_ok = cns.join().expect("CNS thread").is_ok();
    assert_ne!(model_ok, cns_ok, "only one frozen predecessor may win");

    let (latest, checkpoint) = owner.current().expect("single durable winner");
    if model_ok {
        assert_eq!((latest.clone(), checkpoint), (old, committed));
    } else {
        assert_eq!((latest.clone(), checkpoint), (snapshot(4), migrated));
    }
    drop(owner);
    let reopened = NduPublicationOwnerV1::open_production(&path, latest.clone(), checkpoint)
        .expect("winner must replay from original WAL");
    assert_eq!(reopened.current().unwrap(), (latest, checkpoint));
}

#[cfg(unix)]
#[test]
fn truncated_journal_is_rejected_without_mutating_history() {
    let dir = tempfile::tempdir().expect("owner-only");
    let path = dir.path().join("frontier.wal");
    {
        let owner = NduPublicationOwnerV1::open_production(&path, snapshot(3), Digest32::ZERO)
            .expect("opened");
        assert_eq!(owner.current().unwrap().1, Digest32::ZERO);
    }
    let previous = std::fs::read(&path).expect("history");
    let mut file = OpenOptions::new().append(true).open(&path).expect("open");
    file.write_all(b"torn-without-newline")
        .expect("inject torn suffix");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, snapshot(3), Digest32::ZERO),
        Err(NduPublicationErrorV1::Corrupt)
    ));
    assert!(
        std::fs::read(&path)
            .expect("unchanged")
            .starts_with(&previous)
    );
}

#[cfg(unix)]
#[test]
fn symlink_and_world_accessible_directory_cannot_own_frontier() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;
    let dir = tempfile::tempdir().expect("private directory");
    let path = dir.path().join("frontier.wal");
    {
        let _owner = NduPublicationOwnerV1::open_production(&path, snapshot(3), Digest32::ZERO)
            .expect("first owner");
    }
    let alias = dir.path().join("alias.wal");
    symlink(&path, &alias).expect("symlink");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&alias, snapshot(3), Digest32::ZERO),
        Err(NduPublicationErrorV1::UnsafePath)
    ));
    let open_dir = dir.path().join("world");
    std::fs::create_dir(&open_dir).expect("directory");
    std::fs::set_permissions(&open_dir, std::fs::Permissions::from_mode(0o777))
        .expect("permissions");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(
            &open_dir.join("frontier.wal"),
            snapshot(3),
            Digest32::ZERO,
        ),
        Err(NduPublicationErrorV1::UnsafePath)
    ));
}

#[cfg(not(unix))]
#[test]
fn unsupported_platform_denies_frontier_owner() {
    assert!(matches!(
        NduPublicationOwnerV1::open_production(
            Path::new("control.wal"),
            snapshot(3),
            Digest32::ZERO,
        ),
        Err(NduPublicationErrorV1::Unsupported)
    ));
}
