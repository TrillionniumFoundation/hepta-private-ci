use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
#[cfg(unix)]
use std::fs::OpenOptions;

/// A production Control WAL rejects directories writable by group/others.
/// TempDir creation is influenced by the host umask; make these *test* roots
/// private explicitly rather than relaxing the real original-owner check.
#[cfg(unix)]
fn private_control_dir() -> tempfile::TempDir {
    use std::os::unix::fs::PermissionsExt as _;

    // Some Unix platforms expose the system temp root through an alias
    // (for example /var -> /private/var on macOS). All original Control WAL
    // fixtures must exercise an explicitly canonical production path.
    let canonical_temp = std::env::temp_dir()
        .canonicalize()
        .expect("canonical OS temp directory");
    let root = tempfile::Builder::new()
        .tempdir_in(canonical_temp)
        .expect("isolated canonical Control root");
    assert_eq!(
        root.path().canonicalize().expect("fixture path"),
        root.path(),
        "test owner must start from canonical path"
    );
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private Control fixture");
    assert_eq!(
        std::fs::symlink_metadata(root.path())
            .expect("original directory")
            .permissions()
            .mode()
            & 0o077,
        0,
        "never relax original Control WAL privacy"
    );
    root
}

#[cfg(unix)]
fn test_only_original_runtime_receipt() -> Result<((), Vec<u8>), &'static str> {
    // Test-only owner bytes are not a production signature or a real runtime
    // receipt. Production still needs independently verified owner readback.
    Ok(((), vec![0x52; 96]))
}

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
    let dir = private_control_dir();
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
#[allow(deprecated)]
fn direct_single_phase_cns_publication_is_always_denied_and_never_appends() {
    let dir = private_control_dir();
    let path = dir.path().join("legacy-cutover.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("Control owner");
    let before = std::fs::read(&path).expect("original WAL");
    assert_eq!(
        owner.publish_cutover(
            &original,
            Digest32::ZERO,
            snapshot(4),
            Digest32::of_bytes(b"fake-successor"),
        ),
        Err(NduPublicationErrorV1::Unsupported)
    );
    assert_eq!(owner.current().unwrap(), (original, Digest32::ZERO));
    assert_eq!(std::fs::read(&path).expect("unchanged WAL"), before);
}

#[cfg(unix)]
#[test]
fn valid_hash_chain_cannot_replay_direct_cns_commit_without_prior_begin() {
    let dir = private_control_dir();
    let path = dir.path().join("unprepared-cutover.wal");
    let prior = snapshot(3);
    {
        let control = NduPublicationOwnerV1::open_production(&path, prior.clone(), Digest32::ZERO)
            .expect("protected genesis");
        assert_eq!(control.current().unwrap().0, prior);
    }
    let genesis_bytes = std::fs::read_to_string(&path).expect("genesis");
    let genesis = decode(genesis_bytes.lines().last().expect("genesis row"))
        .expect("authentic ledger record");
    let mut forged = Event {
        sequence: genesis.sequence + 1,
        previous: genesis.head,
        head: Digest32::ZERO,
        kind: 'C',
        snapshot: snapshot(4).semantic_digest().expect("successor digest"),
        before: Digest32::ZERO,
        after: Digest32::of_bytes(b"forged-migration"),
        read: Digest32::ZERO,
        tick: Digest32::ZERO,
    };
    forged.head = event_hash(&forged);
    let frame = format!(
        "N1|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
        forged.sequence,
        forged.previous,
        forged.head,
        forged.kind,
        forged.snapshot,
        forged.before,
        forged.after,
        forged.read,
        forged.tick,
    );
    let mut writer = OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("append only to simulate tamper");
    writer.write_all(frame.as_bytes()).expect("inject frame");
    writer.sync_all().expect("force forged durable suffix");
    drop(writer);
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, snapshot(4), forged.after,),
        Err(NduPublicationErrorV1::Corrupt)
    ));
    assert_eq!(
        std::fs::read_to_string(&path).expect("original bytes still present"),
        genesis_bytes + &frame,
        "invalid signed-shaped commit must not silently repair the WAL"
    );
}

#[cfg(unix)]
#[test]
fn cutover_and_checkpoint_cas_use_same_exclusive_owner() {
    let dir = private_control_dir();
    let path = dir.path().join("frontier.wal");
    let previous = snapshot(3);
    let migrated = Digest32::of_bytes(b"migrated-checkpoint");
    {
        let owner = NduPublicationOwnerV1::open_production(&path, previous.clone(), Digest32::ZERO)
            .expect("owner");
        let (_, receipt) = owner
            .publish_cutover_with_external_effect(
                &previous,
                Digest32::ZERO,
                snapshot(4),
                migrated,
                test_only_original_runtime_receipt,
            )
            .expect("durable Begin / fixture effect / Commit");
        assert!(!receipt.is_zero());
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
    let dir = private_control_dir();
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
        owner.publish_cutover_with_external_effect(
            &original,
            Digest32::ZERO,
            snapshot(4),
            migrated,
            test_only_original_runtime_receipt,
        ),
        Err(NduPublicationErrorV1::Stale)
    );
    assert_eq!(owner.current().unwrap(), (original.clone(), committed));
    owner
        .publish_cutover_with_external_effect(
            &original,
            committed,
            snapshot(4),
            migrated,
            test_only_original_runtime_receipt,
        )
        .expect("refrozen migration may advance");
    assert_eq!(owner.current().unwrap(), (snapshot(4), migrated));
}

#[cfg(unix)]
#[test]
fn concurrent_model_and_cns_cas_cannot_both_commit_one_predecessor() {
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::thread;

    let dir = private_control_dir();
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
        cns_owner.publish_cutover_with_external_effect(
            &cns_old,
            Digest32::ZERO,
            snapshot(4),
            migrated,
            test_only_original_runtime_receipt,
        )
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
fn guarded_cutover_commits_real_callback_once_and_replays_original_wal() {
    let dir = private_control_dir();
    let path = dir.path().join("guarded-cutover.wal");
    let current = snapshot(3);
    let successor = snapshot(4);
    let migrated = Digest32::of_bytes(b"real-migrated-checkpoint");
    let mut physical_calls = 0;
    {
        let owner = NduPublicationOwnerV1::open_production(&path, current.clone(), Digest32::ZERO)
            .expect("Control owner");
        let (real_receipt, commit) = owner
            .publish_cutover_with_external_effect(
                &current,
                Digest32::ZERO,
                successor.clone(),
                migrated,
                || -> Result<_, &'static str> {
                    physical_calls += 1;
                    assert_eq!(
                        owner.current(),
                        Err(NduPublicationErrorV1::Indeterminate),
                        "the runtime callback must not see a publishable NDU frontier"
                    );
                    assert_eq!(
                        owner.read_original_local_frontier_v1(),
                        Err(NduPublicationErrorV1::Indeterminate),
                        "original Control Observer must not accept unresolved durable Begin"
                    );
                    assert_eq!(
                        owner.verify_original_cns_receipt_binding(&[0x53; 96]),
                        Err(NduPublicationErrorV1::Indeterminate),
                        "durable Begin must fence original CNS receipt joins until Commit"
                    );
                    assert_eq!(
                        owner.compare_and_publish_checkpoint(
                            &current,
                            Digest32::of_bytes(b"signed-read"),
                            Digest32::of_bytes(b"late-model"),
                            Digest32::ZERO,
                            Digest32::of_bytes(b"forbidden-checkpoint"),
                        ),
                        Err(NduPublicationErrorV1::Indeterminate),
                        "a callback must not reenter the Control lane to publish a tick"
                    );
                    Ok(("original-fsynced-runtime-receipt", vec![0x53; 96]))
                },
            )
            .expect("durable Prepare, external original receipt, Commit");
        assert_eq!(real_receipt, "original-fsynced-runtime-receipt");
        assert!(!commit.is_zero());
        assert_eq!(owner.current().unwrap(), (successor.clone(), migrated));
    }
    assert_eq!(physical_calls, 1, "the external effect is not replayable");
    // The fsynced Control C record must commit to the exact original-owner
    // receipt bytes returned from the callback, not merely the next route
    // digest, a bool success or a no-data OK. This fixture is not signed.
    let mut receipt_binding = b"hepta.control.ndu-publication.cns-original-receipt.v1\0".to_vec();
    receipt_binding.extend_from_slice(&(96_u64).to_be_bytes());
    receipt_binding.extend_from_slice(&[0x53; 96]);
    let expected_receipt_digest = Digest32::of_bytes(&receipt_binding).to_string();
    let journal = std::fs::read_to_string(&path).expect("original Control WAL");
    let commit_row = journal
        .lines()
        .find(|line| line.split('|').nth(4) == Some("C"))
        .expect("new guarded cutover must fsync a C event");
    assert_eq!(
        commit_row.split('|').nth(8),
        Some(expected_receipt_digest.as_str())
    );
    let expected_binding = Digest32::of_bytes(&receipt_binding);
    let reopened = NduPublicationOwnerV1::open_production(&path, successor.clone(), migrated)
        .expect("both durable journal phases replay");
    assert_eq!(reopened.current().unwrap(), (successor, migrated));
    assert_eq!(
        reopened.last_cns_original_receipt_binding().unwrap(),
        Some(expected_binding),
        "recovery must retain the exact committed original owner bytes digest"
    );
    assert_eq!(
        reopened.verify_original_cns_receipt_binding(&[0x53; 96]),
        Ok(()),
        "independent original-owner bytes must match the durable Control WAL"
    );
    assert_eq!(
        reopened.verify_original_cns_receipt_binding(&[0x54; 96]),
        Err(NduPublicationErrorV1::Stale),
        "a different externally signed receipt must not match this cutover"
    );
    assert_eq!(
        reopened.verify_original_cns_receipt_binding(&[]),
        Err(NduPublicationErrorV1::Invalid),
        "a missing original receipt cannot satisfy the observer join"
    );
}

#[cfg(unix)]
#[test]
fn missing_or_unbounded_original_cns_receipt_never_commits_control_handoff() {
    for receipt_bytes in [0_usize, 63, 32 * 1024 + 1] {
        let root = private_control_dir();
        let path = root.path().join("ambiguous-original-receipt.wal");
        let original = snapshot(3);
        let mut calls = 0_usize;
        let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
            .expect("original Control owner");
        let result = owner.publish_cutover_with_external_effect(
            &original,
            Digest32::ZERO,
            snapshot(4),
            Digest32::of_bytes(b"migrated-child-state"),
            || -> Result<((), Vec<u8>), &'static str> {
                calls += 1;
                Ok(((), vec![0x55; receipt_bytes]))
            },
        );
        assert_eq!(result, Err(NduPublicationErrorV1::Indeterminate));
        assert_eq!(calls, 1, "unknown external effect cannot be retried");
        assert_eq!(owner.current(), Err(NduPublicationErrorV1::Poisoned));
        assert_eq!(
            owner.last_cns_original_receipt_binding(),
            Err(NduPublicationErrorV1::Poisoned)
        );
        drop(owner);

        let durable = std::fs::read_to_string(&path).expect("durable prepared WAL");
        assert!(
            durable
                .lines()
                .any(|line| line.split('|').nth(4) == Some("B")),
            "original Begin must remain for independent recovery"
        );
        assert!(
            !durable
                .lines()
                .any(|line| line.split('|').nth(4) == Some("C")),
            "a fake original-owner acknowledgement cannot issue Control Commit"
        );
        assert_eq!(
            NduPublicationOwnerV1::open_production(&path, original, Digest32::ZERO)
                .expect_err("orphan Begin must quarantine restart"),
            NduPublicationErrorV1::Indeterminate
        );
    }
}

#[cfg(unix)]
#[test]
fn unsigned_ndu_owner_or_policy_change_is_denied_before_durable_begin() {
    let dir = private_control_dir();
    let path = dir.path().join("untrusted-handoff.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("owner");
    let original_bytes = std::fs::read(&path).expect("recorded frontier");

    let mut different_owner = snapshot(4);
    different_owner.owner_id = StableId::new("different-ndu-issuer").unwrap();
    let mut different_policy = snapshot(4);
    different_policy.policy_digest = Digest32::of_bytes(b"unsigned-new-policy");
    for successor in [different_owner, different_policy] {
        let mut effects = 0;
        assert!(matches!(
            owner.publish_cutover_with_external_effect(
                &original,
                Digest32::ZERO,
                successor,
                Digest32::of_bytes(b"migrated"),
                || -> Result<((), Vec<u8>), &'static str> {
                    effects += 1;
                    Ok(((), vec![0x54; 96]))
                },
            ),
            Err(NduPublicationErrorV1::Stale)
        ));
        assert_eq!(effects, 0, "no unchecked trust-root effect may run");
    }
    assert_eq!(owner.current().unwrap(), (original, Digest32::ZERO));
    assert_eq!(std::fs::read(&path).unwrap(), original_bytes);
}

#[cfg(unix)]
#[test]
fn insufficient_space_for_commit_denies_before_durable_begin_or_model() {
    let dir = private_control_dir();
    let path = dir.path().join("bounded-control.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("Control owner");
    // The capacity fixture deliberately changes an in-memory length but
    // does NOT append that many bytes to the real fsynced original WAL.
    // Restore this test-only override before using a live public readback:
    // production correctly refuses a fabricated length as Indeterminate.
    let authentic_bytes = {
        let mut state = owner.state.lock().expect("fixture owner");
        let actual = state.bytes;
        state.bytes = MAX_BYTES - MAX_ROW as u64;
        actual
    };
    let before = std::fs::read(&path).expect("authentic Control history");
    assert_eq!(authentic_bytes, before.len() as u64);
    let mut external_calls = 0;
    assert!(matches!(
        owner.publish_cutover_with_external_effect(
            &original,
            Digest32::ZERO,
            snapshot(4),
            Digest32::of_bytes(b"successor-state"),
            || -> Result<((), Vec<u8>), &'static str> {
                external_calls += 1;
                Ok(((), vec![0x55; 96]))
            },
        ),
        Err(NduPublicationErrorV1::Capacity)
    ));
    assert_eq!(external_calls, 0, "do not enter the external effect");
    assert_eq!(std::fs::read(&path).unwrap(), before);
    {
        let mut state = owner.state.lock().expect("fixture owner");
        assert_eq!(state.bytes, MAX_BYTES - MAX_ROW as u64);
        assert!(
            !state.pending_cutover,
            "capacity denial may not stage Begin"
        );
        assert!(
            !state.poisoned,
            "no disk IO or ambiguous effect has occurred"
        );
        // Restore the original physical length, not a fabricated success.
        state.bytes = authentic_bytes;
    }
    assert_eq!(owner.current().unwrap(), (original, Digest32::ZERO));
}

#[cfg(unix)]
#[test]
fn fabricated_control_wal_length_poisoned_by_real_owner_readback() {
    let dir = private_control_dir();
    let path = dir.path().join("mismatched-original-length.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original fsynced Control WAL");
    let authentic = std::fs::read(&path).expect("original Control data");
    {
        let mut state = owner.state.lock().expect("fault injection only");
        state.bytes = state.bytes.checked_add(1).expect("small fixture WAL");
    }
    assert_eq!(
        owner.current(),
        Err(NduPublicationErrorV1::Indeterminate),
        "fabricated in-memory length is not a valid original WAL frontier",
    );
    assert_eq!(
        owner.current(),
        Err(NduPublicationErrorV1::Poisoned),
        "an integrity mismatch is sticky within the serving owner",
    );
    assert_eq!(std::fs::read(&path).unwrap(), authentic);
    drop(owner);
    let recovered = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("cold replay may revalidate the untouched original WAL");
    assert_eq!(recovered.current().unwrap(), (original, Digest32::ZERO));
}

#[cfg(unix)]
#[test]
fn lost_wal_during_real_callback_never_publishes_success_or_recreates_history() {
    let dir = private_control_dir();
    let path = dir.path().join("lost-mid-effect.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("Control owner");
    let mut external_calls = 0;
    assert!(matches!(
        owner.publish_cutover_with_external_effect(
            &original,
            Digest32::ZERO,
            snapshot(4),
            Digest32::of_bytes(b"successor-state"),
            || -> Result<((), Vec<u8>), &'static str> {
                external_calls += 1;
                std::fs::remove_file(&path).expect("simulate physical WAL loss");
                Ok(((), vec![0x55; 96]))
            },
        ),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert_eq!(external_calls, 1, "an uncertain effect cannot be replayed");
    assert_eq!(owner.current(), Err(NduPublicationErrorV1::Poisoned));
    drop(owner);
    assert!(!path.exists(), "no silent replacement of original WAL");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, original, Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert!(
        !path.exists(),
        "recovery does not invent replacement history"
    );
}

#[cfg(unix)]
#[test]
fn original_pending_begin_inspector_fifo_marker_is_nonblocking_and_denied() {
    let dir = private_control_dir();
    let directory = std::fs::File::open(dir.path()).expect("private directory FD");
    rustix::fs::mkfifoat(
        &directory,
        "pending-fifo-marker.wal.owner-lock",
        rustix::fs::Mode::from_bits_truncate(0o600),
    )
    .expect("actual FIFO owner-lock injection");
    let denied = NduPublicationOwnerV1::inspect_original_pending_begin_v1(
        &dir.path().join("pending-fifo-marker.wal"),
        &snapshot(3),
        Digest32::ZERO,
    );
    assert!(matches!(denied, Err(NduPublicationErrorV1::Indeterminate)));
}

#[cfg(unix)]
#[test]
fn original_pending_begin_inspector_fifo_wal_is_nonblocking_and_denied() {
    use std::io::Write as _;
    use std::os::unix::fs::MetadataExt as _;
    use std::os::unix::fs::OpenOptionsExt as _;

    let dir = private_control_dir();
    let path = dir.path().join("pending-fifo-journal.wal");
    let marker = dir.path().join("pending-fifo-journal.wal.owner-lock");
    let directory = std::fs::File::open(dir.path()).expect("private directory FD");
    rustix::fs::mkfifoat(
        &directory,
        "pending-fifo-journal.wal",
        rustix::fs::Mode::from_bits_truncate(0o600),
    )
    .expect("actual FIFO WAL injection");
    // Bind an otherwise valid original marker to the *FIFO's* real inode.
    // Without this setup the inspection fails on the empty marker before
    // ever attempting the potentially blocking WAL open, a hollow test.
    let fifo_metadata = std::fs::symlink_metadata(&path).expect("injected FIFO inode");
    let mut marker_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(&marker)
        .expect("real private ordinary marker");
    write!(
        marker_file,
        "NDUW1|{}|{}\\n",
        fifo_metadata.dev(),
        fifo_metadata.ino()
    )
    .expect("original marker bound to FIFO inode");
    marker_file.sync_all().expect("durable original marker bytes");
    let denied = NduPublicationOwnerV1::inspect_original_pending_begin_v1(
        &path,
        &snapshot(3),
        Digest32::ZERO,
    );
    assert!(matches!(denied, Err(NduPublicationErrorV1::Indeterminate)));
}

#[cfg(unix)]
#[test]
fn original_pending_begin_inspector_reads_only_fsynced_wal_after_crash() {
    let dir = private_control_dir();
    let path = dir.path().join("observed-orphan.wal");
    let original = snapshot(3);
    let successor = snapshot(4);
    let migrated = Digest32::of_bytes(b"orphan-migrated-checkpoint");
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original durable Control owner");
    let effect = owner.publish_cutover_with_external_effect(
        &original,
        Digest32::ZERO,
        successor.clone(),
        migrated,
        || -> Result<((), Vec<u8>), &'static str> {
            Err("CNS effect is ambiguous after durable Begin")
        },
    );
    assert_eq!(effect, Err(NduPublicationErrorV1::Indeterminate));
    assert!(matches!(
        NduPublicationOwnerV1::inspect_original_pending_begin_v1(&path, &original, Digest32::ZERO,),
        Err(NduPublicationErrorV1::WriterUnavailable)
    ));
    drop(owner);
    let wal_before = std::fs::read(&path).expect("immutable original WAL");
    let marker = path.with_file_name("observed-orphan.wal.owner-lock");
    let marker_before = std::fs::read(&marker).expect("original owner marker");
    let observed =
        NduPublicationOwnerV1::inspect_original_pending_begin_v1(&path, &original, Digest32::ZERO)
            .expect("read-only recovery observation of the original pending Begin");
    assert_eq!(
        observed.predecessor_semantic_digest,
        original.semantic_digest().unwrap()
    );
    assert_eq!(
        observed.successor_semantic_digest,
        successor.semantic_digest().unwrap()
    );
    assert_eq!(observed.previous_checkpoint, Digest32::ZERO);
    assert_eq!(observed.migrated_checkpoint, migrated);
    assert_eq!(observed.sequence, 2, "genesis plus fsynced Begin only");
    assert_eq!(observed.wal_bytes, wal_before.len() as u64);
    assert!(!observed.head.is_zero());
    assert_eq!(
        observed,
        NduPublicationOwnerV1::inspect_original_pending_begin_v1(&path, &original, Digest32::ZERO,)
            .expect("second read from exactly the same original history")
    );
    assert_eq!(std::fs::read(&path).unwrap(), wal_before);
    assert_eq!(std::fs::read(&marker).unwrap(), marker_before);
    assert!(
        matches!(
            NduPublicationOwnerV1::open_production(&path, original, Digest32::ZERO),
            Err(NduPublicationErrorV1::Indeterminate)
        ),
        "observation cannot resolve quarantine or mint Control Commit"
    );
}

#[cfg(unix)]
#[test]
fn original_pending_begin_inspector_refuses_non_orphan_or_mutated_prefix() {
    use std::io::Write as _;

    let dir = private_control_dir();
    let path = dir.path().join("pending-probe-denial.wal");
    let original = snapshot(3);
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original Control WAL genesis");
    drop(owner);
    assert!(matches!(
        NduPublicationOwnerV1::inspect_original_pending_begin_v1(&path, &original, Digest32::ZERO,),
        Err(NduPublicationErrorV1::Stale)
    ));
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original re-open");
    let _ = owner.publish_cutover_with_external_effect(
        &original,
        Digest32::ZERO,
        snapshot(4),
        Digest32::of_bytes(b"orphan"),
        || -> Result<((), Vec<u8>), &'static str> { Err("missing original CNS receipt") },
    );
    drop(owner);
    assert!(
        matches!(
            NduPublicationOwnerV1::inspect_original_pending_begin_v1(
                &path,
                &snapshot(8),
                Digest32::ZERO,
            ),
            Err(NduPublicationErrorV1::Indeterminate)
        ),
        "wrong frozen predecessor cannot describe a pending Begin"
    );

    // Corrupt the first history row, leaving the actual last Begin in place.
    // A last-hash-only probe would falsely accept this tampered prefix.
    let mut wal = std::fs::read(&path).expect("durable WAL");
    assert!(wal.len() > 300, "genesis and Begin");
    wal[1] ^= 1;
    let mut original_fd = std::fs::OpenOptions::new()
        .write(true)
        .open(&path)
        .expect("test-only original inode tamper");
    original_fd
        .write_all(&wal)
        .expect("overwrite original inode");
    original_fd.sync_all().expect("fsync original tamper");
    assert!(matches!(
        NduPublicationOwnerV1::inspect_original_pending_begin_v1(&path, &original, Digest32::ZERO,),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
}

#[cfg(unix)]
#[test]
fn orphaned_durable_prepare_fences_model_and_cutover_after_restart() {
    let dir = private_control_dir();
    let path = dir.path().join("unknown-physical-effect.wal");
    let original = snapshot(3);
    let mut calls = 0;
    {
        let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
            .expect("Control owner");
        assert!(matches!(
            owner.publish_cutover_with_external_effect(
                &original,
                Digest32::ZERO,
                snapshot(4),
                Digest32::of_bytes(b"unknown-migrated"),
                || -> Result<((), Vec<u8>), &'static str> {
                    calls += 1;
                    Err("runtime already entered but original receipt unavailable")
                },
            ),
            Err(NduPublicationErrorV1::Indeterminate)
        ));
        assert_eq!(owner.current(), Err(NduPublicationErrorV1::Poisoned));
        assert_eq!(
            owner.compare_and_publish_checkpoint(
                &original,
                Digest32::of_bytes(b"signed-read"),
                Digest32::of_bytes(b"tick"),
                Digest32::ZERO,
                Digest32::of_bytes(b"new-checkpoint"),
            ),
            Err(NduPublicationErrorV1::Poisoned)
        );
    }
    let recorded = std::fs::read(&path).expect("durable unresolved history");
    assert_eq!(
        calls, 1,
        "the model/router must never replay an unknown effect"
    );
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, original, Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert_eq!(
        std::fs::read(&path).expect("journal preserved"),
        recorded,
        "no stale-startup write may erase or upgrade an orphan Begin"
    );
}

#[cfg(unix)]
#[test]
fn concurrent_model_checkpoint_and_guarded_runtime_cutover_have_one_winner() {
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use std::thread;

    let dir = private_control_dir();
    let path = dir.path().join("guarded-race.wal");
    let old = snapshot(3);
    let model_checkpoint = Digest32::of_bytes(b"model-winner");
    let migrated = Digest32::of_bytes(b"runtime-winner");
    let owner = Arc::new(
        NduPublicationOwnerV1::open_production(&path, old.clone(), Digest32::ZERO)
            .expect("durable Control owner"),
    );
    let physical_calls = Arc::new(AtomicUsize::new(0));
    let barrier = Arc::new(Barrier::new(3));

    let model_owner = Arc::clone(&owner);
    let model_barrier = Arc::clone(&barrier);
    let model_old = old.clone();
    let model = thread::spawn(move || {
        model_barrier.wait();
        model_owner.compare_and_publish_checkpoint(
            &model_old,
            Digest32::of_bytes(b"signed-model-read"),
            Digest32::of_bytes(b"model-tick"),
            Digest32::ZERO,
            model_checkpoint,
        )
    });

    let cns_owner = Arc::clone(&owner);
    let cns_barrier = Arc::clone(&barrier);
    let cns_calls = Arc::clone(&physical_calls);
    let cns_old = old.clone();
    let cns = thread::spawn(move || {
        cns_barrier.wait();
        cns_owner.publish_cutover_with_external_effect(
            &cns_old,
            Digest32::ZERO,
            snapshot(4),
            migrated,
            || -> Result<((), Vec<u8>), &'static str> {
                cns_calls.fetch_add(1, Ordering::SeqCst);
                Ok(((), vec![0x54; 96]))
            },
        )
    });
    barrier.wait();
    let model_ok = model.join().expect("model join").is_ok();
    let cns_ok = cns.join().expect("CNS join").is_ok();
    assert_ne!(model_ok, cns_ok, "one frozen predecessor can commit once");
    assert_eq!(
        physical_calls.load(Ordering::SeqCst),
        usize::from(cns_ok),
        "a stale CNS route must not perform the external effect"
    );
    let (live, checkpoint) = owner.current().expect("single surviving frontier");
    if model_ok {
        assert_eq!((live.clone(), checkpoint), (old, model_checkpoint));
    } else {
        assert_eq!((live.clone(), checkpoint), (snapshot(4), migrated));
    }
    drop(owner);
    let restored = NduPublicationOwnerV1::open_production(&path, live.clone(), checkpoint)
        .expect("winner's exact original WAL must replay");
    assert_eq!(restored.current().unwrap(), (live, checkpoint));
}

#[cfg(unix)]
#[test]
fn deleted_control_wal_cannot_bootstrap_a_fresh_history() {
    let dir = private_control_dir();
    let path = dir.path().join("lost-control.wal");
    let original = snapshot(3);
    {
        let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
            .expect("first durable Control owner");
        assert_eq!(owner.current().unwrap(), (original.clone(), Digest32::ZERO));
    }
    let mut marker = path.as_os_str().to_os_string();
    marker.push(".owner-lock");
    let marker_path = PathBuf::from(marker);
    assert!(
        marker_path.exists(),
        "writer history must survive owner exit"
    );
    let frozen_marker = std::fs::read(&marker_path).expect("pinned original inode");
    std::fs::remove_file(&path).expect("simulate lost canonical WAL");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, original, Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert!(
        !path.exists(),
        "reopening cannot silently recreate an empty WAL"
    );
    assert_eq!(std::fs::read(&marker_path).unwrap(), frozen_marker);
}

#[cfg(unix)]
#[test]
fn lost_writer_marker_or_replaced_wal_cannot_adopt_old_signed_state() {
    let dir = private_control_dir();
    let path = dir.path().join("pinned-control.wal");
    let original = snapshot(3);
    {
        let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
            .expect("first durable owner");
        assert!(owner.current().is_ok());
    }
    let mut marker = path.as_os_str().to_os_string();
    marker.push(".owner-lock");
    let marker_path = PathBuf::from(marker);
    let genuine = std::fs::read(&path).expect("original WAL bytes");
    std::fs::remove_file(&marker_path).expect("simulate deleted owner lock");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert_eq!(std::fs::read(&path).unwrap(), genuine);

    // A fresh isolated fixture can demonstrate atomic rename/substitution
    // while the original Unix file lock remains held by the first owner.
    let other = dir.path().join("replaced-control.wal");
    let owner = NduPublicationOwnerV1::open_production(&other, original.clone(), Digest32::ZERO)
        .expect("active original Control writer");
    let former_path = dir.path().join("former-control.wal");
    std::fs::rename(&other, &former_path).expect("unlink original journal name");
    std::fs::copy(&former_path, &other).expect("replacement with valid bytes");
    assert_eq!(
        owner.current(),
        Err(NduPublicationErrorV1::Indeterminate),
        "valid-looking replacement must not become live owner state"
    );
    // An independently valid-looking WAL inode cannot clear the same-process
    // poison latch on a later read or on the read-only CNS receipt join.
    assert_eq!(
        owner.current(),
        Err(NduPublicationErrorV1::Poisoned),
        "original Control WAL read remains permanently fenced"
    );
    assert_eq!(
        owner.last_cns_original_receipt_binding(),
        Err(NduPublicationErrorV1::Poisoned)
    );
    assert_eq!(
        owner.verify_original_cns_receipt_binding(&[7_u8; 128]),
        Err(NduPublicationErrorV1::Poisoned)
    );
    assert!(matches!(
        owner.compare_and_publish_checkpoint(
            &original,
            Digest32::of_bytes(b"fresh-read"),
            Digest32::of_bytes(b"fresh-tick"),
            Digest32::ZERO,
            Digest32::of_bytes(b"forbidden-success"),
        ),
        Err(NduPublicationErrorV1::Poisoned)
    ));
    drop(owner);
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&other, original, Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
    assert!(std::fs::read(&other).is_ok());
}

#[cfg(unix)]
#[test]
fn inplace_wal_truncate_and_equal_length_tail_rewrite_fence_live_observer() {
    use std::os::unix::fs::MetadataExt as _;

    for fault in ["truncate", "same_length_rewrite"] {
        let root = private_control_dir();
        let path = root.path().join("owner.wal");
        let previous = snapshot(3);
        let migrated = Digest32::of_bytes(b"migrated-checkpoint");
        let owner = NduPublicationOwnerV1::open_production(&path, previous.clone(), Digest32::ZERO)
            .expect("durable owner");
        owner
            .publish_cutover_with_external_effect(
                &previous,
                Digest32::ZERO,
                snapshot(4),
                migrated,
                || -> Result<((), Vec<u8>), &'static str> { Ok(((), vec![0x64; 96])) },
            )
            .expect("fixture original bytes bound by Control Commit");
        assert_eq!(
            owner.verify_original_cns_receipt_binding(&[0x64; 96]),
            Ok(())
        );
        let bytes = std::fs::read(&path).expect("durable control WAL");
        let inode = std::fs::metadata(&path).expect("original inode").ino();
        match fault {
            "truncate" => {
                let file = OpenOptions::new()
                    .write(true)
                    .open(&path)
                    .expect("original WAL inode");
                file.set_len(0).expect("truncate original file");
                file.sync_all().expect("durably corrupt original file");
            }
            "same_length_rewrite" => {
                let mut damaged = bytes.clone();
                let pos = damaged.len() - 2;
                damaged[pos] = if damaged[pos] == b'0' { b'1' } else { b'0' };
                std::fs::write(&path, damaged).expect("same inode rewritten");
                assert_eq!(
                    std::fs::metadata(&path).expect("same length").len(),
                    bytes.len() as u64
                );
            }
            _ => unreachable!("fixed fault cases"),
        }
        assert_eq!(
            std::fs::metadata(&path)
                .expect("still original inode")
                .ino(),
            inode
        );
        assert_eq!(
            owner.last_cns_original_receipt_binding(),
            Err(NduPublicationErrorV1::Indeterminate),
            "corrupt original WAL cannot provide the cached positive evidence"
        );
        assert_eq!(
            owner.verify_original_cns_receipt_binding(&[0x64; 96]),
            Err(NduPublicationErrorV1::Poisoned)
        );
        assert_eq!(
            owner.compare_and_publish_checkpoint(
                &previous,
                Digest32::of_bytes(b"read"),
                Digest32::of_bytes(b"tick"),
                Digest32::ZERO,
                Digest32::of_bytes(b"forbidden-checkpoint"),
            ),
            Err(NduPublicationErrorV1::Poisoned)
        );
        drop(owner);
        assert!(matches!(
            NduPublicationOwnerV1::open_production(&path, snapshot(4), migrated),
            Err(NduPublicationErrorV1::Corrupt) | Err(NduPublicationErrorV1::Indeterminate)
        ));
    }
}

#[cfg(unix)]
#[test]
fn fixed_stack_original_control_wal_tail_protects_short_and_multirow_histories() {
    use std::os::unix::fs::MetadataExt as _;

    // Exercise both the short-tail and MAX_ROW-clamped positional read.
    // A corrupted terminal row must poison the original owner regardless
    // of whether the durable WAL spans several bounded read windows.
    for ticks in [1_usize, 8] {
        let root = private_control_dir();
        let path = root.path().join("stack-tail.wal");
        let frozen = snapshot(3);
        let owner = NduPublicationOwnerV1::open_production(&path, frozen.clone(), Digest32::ZERO)
            .expect("original private Control owner");
        let mut previous = Digest32::ZERO;
        for i in 0..ticks {
            let next = Digest32::of_bytes(format!("checkpoint-{i}").as_bytes());
            owner
                .compare_and_publish_checkpoint(
                    &frozen,
                    Digest32::of_bytes(format!("signed-read-{i}").as_bytes()),
                    Digest32::of_bytes(format!("signed-tick-{i}").as_bytes()),
                    previous,
                    next,
                )
                .expect("actual fsynced Control checkpoint");
            previous = next;
        }

        let original = std::fs::read(&path).expect("original WAL");
        if ticks == 1 {
            assert!(original.len() < MAX_ROW, "single P must fit a short tail");
        } else {
            assert!(
                original.len() > MAX_ROW,
                "multi-P history must cross the fixed tail buffer size"
            );
        }
        assert_eq!(owner.current(), Ok((frozen.clone(), previous)));
        let replayed = owner
            .read_original_local_frontier_v1()
            .expect("original full prefix must replay");
        assert_eq!(replayed.sequence, ticks as u64 + 1);
        assert_eq!(replayed.wal_bytes, original.len() as u64);
        let inode = std::fs::metadata(&path).expect("original WAL inode").ino();

        let mut tampered = original.clone();
        let last_value_byte = tampered.len() - 2;
        tampered[last_value_byte] = if tampered[last_value_byte] == b'0' {
            b'1'
        } else {
            b'0'
        };
        std::fs::write(&path, tampered).expect("rewrite same WAL inode");
        OpenOptions::new()
            .write(true)
            .open(&path)
            .expect("existing original WAL")
            .sync_all()
            .expect("durably record terminal tamper");
        assert_eq!(
            std::fs::metadata(&path).expect("still same WAL").ino(),
            inode
        );
        assert_eq!(
            std::fs::metadata(&path).expect("unchanged WAL size").len(),
            original.len() as u64
        );
        assert_eq!(
            owner.current(),
            Err(NduPublicationErrorV1::Indeterminate),
            "fixed stack tail cannot treat equal-size terminal hash corruption as current"
        );
        assert_eq!(
            owner.current(),
            Err(NduPublicationErrorV1::Poisoned),
            "a failed original Control verification must remain poisoned"
        );
    }
}

#[cfg(unix)]
#[test]
fn truncated_journal_is_rejected_without_mutating_history() {
    let dir = private_control_dir();
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
    let dir = private_control_dir();
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

#[cfg(unix)]
#[test]
fn original_control_actor_replays_fsynced_history_without_moving_writer_offset() {
    use std::io::Seek as _;
    use std::os::unix::fs::MetadataExt as _;

    let dir = private_control_dir();
    let path = dir.path().join("original-actor.wal");
    let original = snapshot(3);
    let first = Digest32::of_bytes(b"actor-checkpoint-1");
    let second = Digest32::of_bytes(b"actor-checkpoint-2");
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original Control writer");
    let first_head = owner
        .compare_and_publish_checkpoint(
            &original,
            Digest32::of_bytes(b"actor-read-1"),
            Digest32::of_bytes(b"actor-tick-1"),
            Digest32::ZERO,
            first,
        )
        .expect("first original fsync");
    let second_head = owner
        .compare_and_publish_checkpoint(
            &original,
            Digest32::of_bytes(b"actor-read-2"),
            Digest32::of_bytes(b"actor-tick-2"),
            first,
            second,
        )
        .expect("second original fsync");
    assert_ne!(first_head, second_head);
    let original_bytes = std::fs::read(&path).expect("original WAL bytes");
    let before_offset = {
        let mut state = owner.state.lock().expect("original writer lock");
        state.file.stream_position().expect("append cursor")
    };
    let observed = owner
        .read_original_local_frontier_v1()
        .expect("real original-inode, full-history readback");
    let after_offset = {
        let mut state = owner.state.lock().expect("original writer lock");
        state
            .file
            .stream_position()
            .expect("unchanged append cursor")
    };
    assert_eq!(
        before_offset, after_offset,
        "Observer must use positional reads"
    );
    assert_eq!(std::fs::read(&path).unwrap(), original_bytes);
    assert_eq!(observed.snapshot, original);
    assert_eq!(observed.checkpoint, second);
    assert_eq!(observed.sequence, 3, "G and two persisted P records");
    assert_eq!(observed.head, second_head);
    assert_eq!(observed.wal_bytes, original_bytes.len() as u64);
    assert_eq!(observed.original_cns_receipt_binding, None);
    assert_eq!(observed.wal_inode, std::fs::metadata(&path).unwrap().ino());
    let marker = PathBuf::from(format!("{}.owner-lock", path.display()));
    assert_eq!(
        observed.marker_inode,
        std::fs::metadata(&marker).unwrap().ino()
    );
    assert_ne!(observed.wal_inode, observed.marker_inode);
}

#[cfg(unix)]
#[test]
fn original_control_cns_join_poisoned_by_earlier_same_inode_wal_corruption() {
    use std::os::unix::fs::MetadataExt as _;

    let dir = private_control_dir();
    let path = dir.path().join("control-prefix.wal");
    let original = snapshot(3);
    let successor = snapshot(4);
    let migrated = Digest32::of_bytes(b"control-prefix-migrated");
    let after = Digest32::of_bytes(b"control-prefix-model");
    let owner = NduPublicationOwnerV1::open_production(&path, original.clone(), Digest32::ZERO)
        .expect("original Control owner");
    owner
        .publish_cutover_with_external_effect(
            &original,
            Digest32::ZERO,
            successor.clone(),
            migrated,
            || -> Result<((), Vec<u8>), &'static str> { Ok(((), vec![0x68; 96])) },
        )
        .expect("fsynced original B, reference effect and C");
    owner
        .compare_and_publish_checkpoint(
            &successor,
            Digest32::of_bytes(b"prefix-read"),
            Digest32::of_bytes(b"prefix-tick"),
            migrated,
            after,
        )
        .expect("later original checkpoint");
    assert!(owner.read_original_local_frontier_v1().is_ok());
    assert_eq!(
        owner.verify_original_cns_receipt_binding(&[0x68; 96]),
        Ok(())
    );

    let mut bytes = std::fs::read(&path).expect("original WAL");
    let inode = std::fs::metadata(&path).unwrap().ino();
    let first_end = bytes.iter().position(|&byte| byte == b'\n').unwrap();
    let changed = first_end - 2;
    bytes[changed] = if bytes[changed] == b'0' { b'1' } else { b'0' };
    let final_row = bytes.rsplit(|&byte| byte == b'\n').nth(1).unwrap().to_vec();
    std::fs::write(&path, &bytes).expect("same original inode, earlier prefix changed");
    assert_eq!(std::fs::metadata(&path).unwrap().ino(), inode);
    assert_eq!(std::fs::metadata(&path).unwrap().len(), bytes.len() as u64);
    let persisted = std::fs::read(&path).unwrap();
    assert_eq!(
        persisted.rsplit(|&byte| byte == b'\n').nth(1).unwrap(),
        final_row.as_slice(),
        "terminal row is intact; digest-only/tail-only verification is insufficient"
    );
    assert_eq!(
        owner.verify_original_cns_receipt_binding(&[0x68; 96]),
        Err(NduPublicationErrorV1::Indeterminate),
        "original CNS Control join must replay the entire actual WAL prefix"
    );
    assert_eq!(
        owner.read_original_local_frontier_v1(),
        Err(NduPublicationErrorV1::Poisoned)
    );
    assert_eq!(owner.current(), Err(NduPublicationErrorV1::Poisoned));
    assert_eq!(
        std::fs::read(&path).unwrap(),
        bytes,
        "Observer does not rewrite WAL"
    );
    drop(owner);
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&path, successor, after),
        Err(NduPublicationErrorV1::Corrupt) | Err(NduPublicationErrorV1::Indeterminate)
    ));
}

#[cfg(unix)]
#[test]
fn signed_original_receipt_binding_does_not_mask_a_later_checkpoint_frontier() {
    let dir = private_control_dir();
    let path = dir.path().join("control-cns-checkpoint-race.wal");
    let predecessor = snapshot(3);
    let successor = snapshot(4);
    let migrated = Digest32::of_bytes(b"checkpoint-race-migrated");
    let next_checkpoint = Digest32::of_bytes(b"checkpoint-race-next");
    let owner = NduPublicationOwnerV1::open_production(&path, predecessor.clone(), Digest32::ZERO)
        .expect("original signed Control owner");
    owner
        .publish_cutover_with_external_effect(
            &predecessor,
            Digest32::ZERO,
            successor.clone(),
            migrated,
            || -> Result<((), Vec<u8>), &'static str> { Ok(((), vec![0x6a; 96])) },
        )
        .expect("test-only original receipt, durable B and C");
    let before = owner
        .verify_original_cns_receipt_frontier_v1(&[0x6a; 96])
        .expect("full Control replay at signed readback start");
    assert_eq!(before.sequence, 3);
    owner
        .compare_and_publish_checkpoint(
            &successor,
            Digest32::of_bytes(b"checkpoint-race-read"),
            Digest32::of_bytes(b"checkpoint-race-tick"),
            migrated,
            next_checkpoint,
        )
        .expect("Neuron CAS can advance independently between Observer reads");
    let after = owner
        .verify_original_cns_receipt_frontier_v1(&[0x6a; 96])
        .expect("identical original CNS bytes but a different Control revision");
    assert_eq!(
        before.original_cns_receipt_binding, after.original_cns_receipt_binding,
        "digest-only original CNS receipt binding cannot detect intervening P"
    );
    assert_eq!(after.sequence, before.sequence + 1);
    assert_ne!(before.head, after.head);
    assert_ne!(before.checkpoint, after.checkpoint);
    assert_ne!(
        before, after,
        "Runtime Observer must refuse a cross-revision signed CNS/Control join"
    );
    assert_eq!(owner.current().unwrap(), (successor, next_checkpoint));
}

#[cfg(unix)]
#[test]
fn symlink_in_ancestor_cannot_alias_or_bootstrap_original_control_owner() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let dir = private_control_dir();
    let actual_ancestor = dir.path().join("actual");
    let actual_parent = actual_ancestor.join("private");
    std::fs::create_dir_all(&actual_parent).expect("real private Control directory");
    std::fs::set_permissions(&actual_ancestor, std::fs::Permissions::from_mode(0o700))
        .expect("private ancestor");
    std::fs::set_permissions(&actual_parent, std::fs::Permissions::from_mode(0o700))
        .expect("private original owner directory");

    let canonical_path = actual_parent.join("control.wal");
    let canonical_lock = actual_parent.join("control.wal.owner-lock");
    let frozen = snapshot(3);
    {
        let owner =
            NduPublicationOwnerV1::open_production(&canonical_path, frozen.clone(), Digest32::ZERO)
                .expect("canonical owner must open");
        assert!(owner.current().is_ok());
    }
    let journal_before = std::fs::read(&canonical_path).expect("canonical WAL");
    let marker_before = std::fs::read(&canonical_lock).expect("original owner lock marker");

    // Only the ancestor is a symlink. The immediate parent itself is a
    // genuine private directory, so checking symlink_metadata(parent) alone
    // would have incorrectly accepted this second spelling of the SAME WAL.
    let alias_ancestor = dir.path().join("alias");
    symlink(&actual_ancestor, &alias_ancestor).expect("private alias");
    let alias_path = alias_ancestor.join("private").join("control.wal");
    assert!(
        std::fs::symlink_metadata(alias_path.parent().expect("parent"))
            .expect("actual final parent")
            .is_dir()
    );
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&alias_path, frozen.clone(), Digest32::ZERO),
        Err(NduPublicationErrorV1::UnsafePath)
    ));

    // An alias cannot initialize a different durable transaction either.
    let new_alias = alias_ancestor.join("private").join("new.wal");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&new_alias, frozen.clone(), Digest32::ZERO),
        Err(NduPublicationErrorV1::UnsafePath)
    ));
    assert!(!actual_parent.join("new.wal").exists());
    assert!(!actual_parent.join("new.wal.owner-lock").exists());
    assert_eq!(std::fs::read(&canonical_path).unwrap(), journal_before);
    assert_eq!(std::fs::read(&canonical_lock).unwrap(), marker_before);

    let reopened = NduPublicationOwnerV1::open_production(&canonical_path, frozen, Digest32::ZERO)
        .expect("real owner stays readable under the canonical path");
    assert!(reopened.current().is_ok());
}

#[cfg(unix)]
#[test]
fn pinned_dirfd_keeps_original_wal_bootstrap_out_of_rebound_directory() {
    use std::os::unix::fs::PermissionsExt;

    let dir = private_control_dir();
    let parent = dir.path().join("original");
    let moved = dir.path().join("detached-original");
    std::fs::create_dir(&parent).expect("private original parent");
    std::fs::set_permissions(&parent, std::fs::Permissions::from_mode(0o700))
        .expect("private parent permissions");
    let journal = parent.join("ndu.wal");
    let marker = parent.join("ndu.wal.owner-lock");

    // Deterministic rebind AFTER the private canonical directory FD is
    // verified but BEFORE either journal or owner-lock is opened. An old
    // path-based OpenOptions would create both files in the substitute.
    let result = NduPublicationOwnerV1::open_production_with_directory_hook(
        &journal,
        snapshot(3),
        Digest32::ZERO,
        || {
            std::fs::rename(&parent, &moved).expect("detach original dir");
            std::fs::create_dir(&parent).expect("install empty substitute");
            std::fs::set_permissions(&parent, std::fs::Permissions::from_mode(0o700))
                .expect("private substitute");
        },
    );
    assert!(
        matches!(
            result,
            Err(NduPublicationErrorV1::Indeterminate) | Err(NduPublicationErrorV1::UnsafePath)
        ),
        "path rebind must never be interpreted as a committed Control owner"
    );
    assert!(!journal.exists(), "substitute must not receive a WAL");
    assert!(
        !marker.exists(),
        "substitute must not receive an owner marker"
    );
    assert!(
        moved.join("ndu.wal.owner-lock").exists(),
        "new reservation, if created, must remain in the pinned original directory"
    );
    assert!(
        !moved.join("ndu.wal").exists(),
        "bootstrap must fail before the original WAL is created"
    );

    // An interrupted reservation remains a durable ambiguity after the
    // original directory is put back. No automatic fresh genesis or reuse.
    std::fs::remove_dir(&parent).expect("empty substitute");
    std::fs::rename(&moved, &parent).expect("restore original name");
    assert!(matches!(
        NduPublicationOwnerV1::open_production(&journal, snapshot(3), Digest32::ZERO),
        Err(NduPublicationErrorV1::Indeterminate)
    ));
}

#[cfg(unix)]
#[test]
fn fixed_stack_control_owner_marker_matches_original_decimal_grammar() {
    // An original marker is persisted by the bootstrap using format! but
    // checked on every Neuron CAS/Observer read with a bounded stack buffer.
    // Assert byte-for-byte equality across decimal carry and full u64 range.
    for (device, inode) in [
        (0_u64, 0_u64),
        (1, 9),
        (9, 10),
        (10, 99),
        (99, 100),
        (u32::MAX as u64, u64::MAX),
        (u64::MAX, u32::MAX as u64),
        (u64::MAX, u64::MAX),
    ] {
        let (marker, length) =
            encode_control_owner_marker_v1(device, inode).expect("bounded stack marker");
        let original = format!("NDUW1|{device}|{inode}\n");
        assert_eq!(&marker[..length], original.as_bytes());
        assert!(
            length <= MAX_CONTROL_OWNER_MARKER_BYTES,
            "no original marker may exceed fixed bounded storage"
        );
        assert!(
            marker[length..].iter().all(|byte| *byte == 0),
            "unused stack bytes must not be exposed as a marker"
        );
    }
}

#[cfg(unix)]
#[test]
fn live_control_owner_rejects_same_bytes_rebound_marker_after_identity_check() {
    use std::io::Seek as _;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let dir = private_control_dir();
    let wal = dir.path().join("original-live.wal");
    let marker = dir.path().join("original-live.wal.owner-lock");
    let detached_marker = dir.path().join("detached-original.owner-lock");
    let frozen = snapshot(3);
    let checkpoint = Digest32::of_bytes(b"marker-race-checkpoint");
    let owner = NduPublicationOwnerV1::open_production(&wal, frozen.clone(), Digest32::ZERO)
        .expect("original writer");
    owner
        .compare_and_publish_checkpoint(
            &frozen,
            Digest32::of_bytes(b"original-read"),
            Digest32::of_bytes(b"original-tick"),
            Digest32::ZERO,
            checkpoint,
        )
        .expect("original fsynced WAL checkpoint");

    let original_frontier = owner
        .read_original_local_frontier_v1()
        .expect("original full-prefix Observer readback");
    let original_wal_bytes = std::fs::read(&wal).expect("original WAL bytes");
    let original_marker_bytes = std::fs::read(&marker).expect("original marker");
    let original_inode = std::fs::metadata(&marker).unwrap().ino();

    // One deterministic attack occurs AFTER the initial real marker and
    // WAL inode check but BEFORE marker content is read. A copied marker
    // has exactly the original contents yet is not the original locked inode.
    // The source must read through the pinned original FD, then revalidate
    // both original names before publishing any success or append.
    {
        let mut state = owner.state.lock().expect("original Control owner");
        let old_cursor = state.owner_lock.stream_position().expect("marker offset");
        let result = state.verify_original_paths_with_identity_hook(
            state.bytes,
            state.sequence,
            state.head,
            || {
                std::fs::rename(&marker, &detached_marker)
                    .expect("detach only original locked marker name");
                std::fs::write(&marker, &original_marker_bytes)
                    .expect("same-content impostor marker");
                std::fs::set_permissions(&marker, std::fs::Permissions::from_mode(0o600))
                    .expect("private impostor");
            },
        );
        assert_eq!(result, Err(NduPublicationErrorV1::Indeterminate));
        assert_eq!(
            state.owner_lock.stream_position().unwrap(),
            old_cursor,
            "positional original marker read cannot move shared descriptor offset"
        );
    }
    assert_ne!(
        std::fs::metadata(&marker).unwrap().ino(),
        original_inode,
        "same bytes are never proof of original owner inode identity"
    );
    assert_eq!(std::fs::read(&marker).unwrap(), original_marker_bytes);
    assert_eq!(std::fs::read(&wal).unwrap(), original_wal_bytes);
    assert_eq!(owner.current(), Err(NduPublicationErrorV1::Indeterminate));
    assert_eq!(owner.current(), Err(NduPublicationErrorV1::Poisoned));
    assert_eq!(
        owner.compare_and_publish_checkpoint(
            &frozen,
            Digest32::of_bytes(b"forbidden-read"),
            Digest32::of_bytes(b"forbidden-tick"),
            checkpoint,
            Digest32::of_bytes(b"forbidden-checkpoint"),
        ),
        Err(NduPublicationErrorV1::Poisoned)
    );
    drop(owner);
    std::fs::remove_file(&marker).expect("remove impostor marker only");
    std::fs::rename(&detached_marker, &marker).expect("restore original locked name");

    // Restoring the exact same original inode and fsynced bytes does not
    // create a second genesis or a new rollback frontier.
    let reopened = NduPublicationOwnerV1::open_production(&wal, frozen, checkpoint)
        .expect("reopen exact original Control state");
    assert_eq!(
        reopened.read_original_local_frontier_v1().unwrap(),
        original_frontier
    );
    assert_eq!(std::fs::read(&wal).unwrap(), original_wal_bytes);
    assert_eq!(std::fs::read(&marker).unwrap(), original_marker_bytes);
}

#[cfg(unix)]
#[test]
fn original_control_wal_requires_effective_uid_for_private_owner_and_reopen() {
    use std::os::unix::fs::MetadataExt;

    let dir = private_control_dir();
    let path = dir.path().join("principal-owned.wal");
    let marker = dir.path().join("principal-owned.wal.owner-lock");
    let effective_uid = rustix::process::geteuid().as_raw();
    let foreign_uid = effective_uid.wrapping_add(1);

    let dir_meta = std::fs::symlink_metadata(dir.path()).expect("original private owner root");
    assert_eq!(dir_meta.uid(), effective_uid);
    assert!(control_original_owner_uid_matches_euid(
        dir_meta.uid(),
        dir_meta.uid()
    ));

    // Deterministic foreign-UID denial without requiring chown, privileges
    // or a forged root process. Both a replaced path and a replaced open
    // descriptor's owner must be rejected, even with private 0700 modes.
    assert!(!control_original_owner_uid_matches_euid(
        foreign_uid,
        foreign_uid
    ));
    assert!(!control_original_owner_uid_matches_euid(
        effective_uid,
        foreign_uid
    ));
    assert!(!control_original_owner_uid_matches_euid(
        foreign_uid,
        effective_uid
    ));

    let frozen = snapshot(3);
    let checkpoint = Digest32::of_bytes(b"original-principal-checkpoint");
    let original_frontier;
    {
        let owner = NduPublicationOwnerV1::open_production(&path, frozen.clone(), Digest32::ZERO)
            .expect("actual principal opens original Control owner");
        owner
            .compare_and_publish_checkpoint(
                &frozen,
                Digest32::of_bytes(b"principal-read"),
                Digest32::of_bytes(b"principal-tick"),
                Digest32::ZERO,
                checkpoint,
            )
            .expect("original WAL fsync");
        original_frontier = owner
            .read_original_local_frontier_v1()
            .expect("original full-prefix readback");

        let wal_meta = std::fs::symlink_metadata(&path).expect("actual original WAL");
        let marker_meta = std::fs::symlink_metadata(&marker).expect("actual original marker");
        assert_eq!(wal_meta.uid(), effective_uid);
        assert_eq!(marker_meta.uid(), effective_uid);
        assert!(control_original_owner_uid_matches_euid(
            wal_meta.uid(),
            wal_meta.uid()
        ));
        assert!(control_original_owner_uid_matches_euid(
            marker_meta.uid(),
            marker_meta.uid()
        ));
    }

    // The ownership fence must not reject legitimate same-principal
    // recovery or mint another Genesis when original G/P history exists.
    let reopened = NduPublicationOwnerV1::open_production(&path, frozen.clone(), checkpoint)
        .expect("same-principal original Control recovery");
    assert_eq!(
        reopened.read_original_local_frontier_v1().unwrap(),
        original_frontier
    );
    assert_eq!(reopened.current().unwrap(), (frozen, checkpoint));
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
