use std::fs;

use ed25519_dalek::SigningKey;

use super::*;

struct VerifiedOriginalMinimum {
    allow: bool,
    checks: usize,
}

impl CellSplitSupervisorMinimumAdmissionPortV1 for VerifiedOriginalMinimum {
    type Error = &'static str;

    fn verify_original_minimum(
        &mut self,
        _subject: &CellSplitSupervisorMinimumSubjectV1,
    ) -> Result<(), Self::Error> {
        self.checks += 1;
        if self.allow {
            Ok(())
        } else {
            Err("external journal and Selector minimum unavailable")
        }
    }
}

fn subject() -> CellSplitSupervisorMinimumSubjectV1 {
    CellSplitSupervisorMinimumSubjectV1 {
        split_id: "split.migration.original".into(),
        target_host_id: "external.observer.host".into(),
        target_host_nonce: "host-nonce-001".into(),
        plan_digest: "11".repeat(32),
        host_evidence_digest: "22".repeat(32),
        journal_domain_id: "decision-cell.scope".into(),
        journal_idempotency_key: "33".repeat(32),
        journal_authority_epoch: 7,
        journal_revision: 10,
        original_checkpoint_bytes_digest: "44".repeat(32),
        minimum_checkpoint_digest: "55".repeat(32),
    }
}

fn private_root() -> tempfile::TempDir {
    let root = tempfile::tempdir().expect("separately administered fixture");
    use std::os::unix::fs::PermissionsExt as _;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
        .expect("isolated owner permissions");
    root
}

fn replace_held_lock_path(root: &Path) {
    use std::os::unix::fs::OpenOptionsExt as _;

    let lock = root.join(crate::durable::SIDECAR_LOCK_FILE);
    fs::remove_file(&lock).expect("unlink held lock path");
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&lock)
        .expect("create independent unlocked inode");
}

#[test]
fn detached_minimum_lock_cannot_publish_or_sign_current_state() {
    let root = private_root();
    let signer = SigningKey::from_bytes(&[91; 32]);
    let mut admission = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    let mut store = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), signer)
        .expect("first minimum store");
    replace_held_lock_path(root.path());
    assert!(
        store.publish_once(&subject(), &mut admission).is_err(),
        "an unlinked OS lock cannot protect a new durable publication"
    );
    assert_eq!(admission.checks, 0);
    assert!(!root.path().join(STORE_FILE).exists());
}

#[test]
fn detached_minimum_lock_denies_challenge_after_durable_publication() {
    let root = private_root();
    let signer = SigningKey::from_bytes(&[91; 32]);
    let mut store = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), signer)
        .expect("first minimum store");
    let mut admission = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    store
        .publish_once(&subject(), &mut admission)
        .expect("original minimum");
    assert!(store.read_current(&subject(), &"aa".repeat(32)).is_ok());
    replace_held_lock_path(root.path());
    assert!(
        store.read_current(&subject(), &"bb".repeat(32)).is_err(),
        "a valid old record cannot be freshly attested under a detached lock"
    );
    assert!(
        store.publish_once(&subject(), &mut admission).is_err(),
        "idempotent replay also requires the original live writer lock"
    );
}

#[test]
fn external_minimum_admission_cannot_replace_writer_lock_mid_publication() {
    struct RebindDuringAdmission<'a> {
        root: &'a Path,
        checks: usize,
    }

    impl CellSplitSupervisorMinimumAdmissionPortV1 for RebindDuringAdmission<'_> {
        type Error = &'static str;

        fn verify_original_minimum(
            &mut self,
            _subject: &CellSplitSupervisorMinimumSubjectV1,
        ) -> Result<(), Self::Error> {
            self.checks += 1;
            if self.checks == 1 {
                replace_held_lock_path(self.root);
            }
            Ok(())
        }
    }

    let root = private_root();
    let signer = SigningKey::from_bytes(&[91; 32]);
    let mut store = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), signer)
        .expect("first minimum store");
    let mut admission = RebindDuringAdmission {
        root: root.path(),
        checks: 0,
    };
    assert!(store.publish_once(&subject(), &mut admission).is_err());
    assert_eq!(admission.checks, 1);
    assert!(!root.path().join(STORE_FILE).exists());
}

#[test]
fn independent_minimum_requires_durable_publication_and_live_challenge() {
    let root = private_root();
    let key = SigningKey::from_bytes(&[91; 32]);
    let policy_key = key.verifying_key();
    let expected = subject();
    let mut admission = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    {
        let mut store = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), key.clone())
            .expect("independent root");
        assert!(matches!(
            store.read_current(&expected, &"aa".repeat(32)),
            Err(CellSplitSupervisorMinimumErrorV1::Missing)
        ));
        store.publish_once(&expected, &mut admission).expect("first immutable checkpoint minimum");
        store.publish_once(&expected, &mut admission).expect("exact replay is idempotent");
        let original = store.read_current(&expected, &"aa".repeat(32))
            .expect("current minimum proof");
        verify_cell_split_supervisor_minimum_online_v1(
            &expected, &"aa".repeat(32), &original, &policy_key,
        ).expect("challenge signed by pinned store");
        assert!(verify_cell_split_supervisor_minimum_online_v1(
            &expected, &"bb".repeat(32), &original, &policy_key,
        ).is_err(), "a prior valid response must not answer a new challenge");
        assert!(verify_cell_split_supervisor_minimum_online_v1(
            &expected,
            &"aa".repeat(32),
            &original,
            &SigningKey::from_bytes(&[92; 32]).verifying_key(),
        ).is_err(), "a self-selected reader key is not trusted");
        assert!(
            CellSplitSupervisorMinimumFileStoreV1::open(root.path(), key.clone()).is_err(),
            "the independent owner retains its writer lock",
        );
    }
    let mut reopened = CellSplitSupervisorMinimumFileStoreV1::open_existing(root.path(), key)
        .expect("read-only restart with original independent signer");
    let fresh = reopened.read_current(&expected, &"cc".repeat(32))
        .expect("recovered minimum");
    verify_cell_split_supervisor_minimum_online_v1(
        &expected, &"cc".repeat(32), &fresh, &policy_key,
    ).expect("reopened minimum remains valid");
    let mut future = expected.clone();
    future.journal_revision += 1;
    assert!(
        reopened.publish_once(&future, &mut admission).is_err(),
        "no in-place witness replacement"
    );
    assert!(reopened.read_current(&future, &"dd".repeat(32)).is_err());
    let mut other_host = expected;
    other_host.target_host_nonce.push_str("-different");
    assert!(reopened.read_current(&other_host, &"ee".repeat(32)).is_err());
}

#[test]
fn independently_persisted_minimum_tampering_fails_closed() {
    let root = private_root();
    let key = SigningKey::from_bytes(&[91; 32]);
    let mut store = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), key)
        .expect("independent source");
    let expected = subject();
    let mut admission = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    store.publish_once(&expected, &mut admission).expect("durable original");
    let path = root.path().join(STORE_FILE);
    let saved = fs::read(&path).expect("stored bytes");
    assert!(!saved.is_empty());
    fs::write(&path, b"{}").expect("simulated corruption");
    assert!(store.read_current(&expected, &"aa".repeat(32)).is_err());
    assert!(store.publish_once(&expected, &mut admission).is_err());
    fs::write(&path, &saved).expect("restore original for alias test");
    let other = root.path().join("hard-linked-minimum");
    fs::hard_link(&path, &other).expect("simulate untrusted alias");
    assert!(store.read_current(&expected, &"aa".repeat(32)).is_err());
}

#[test]
fn read_only_recovery_rejects_missing_original_without_creating_a_lock() {
    let root = private_root();
    let signer = SigningKey::from_bytes(&[91; 32]);
    assert!(CellSplitSupervisorMinimumFileStoreV1::open_existing(
        root.path(), signer.clone(),
    ).is_err());
    assert!(!root.path().join(crate::durable::SIDECAR_LOCK_FILE).exists());
    assert!(!root.path().join(STORE_FILE).exists());
    {
        let mut store = CellSplitSupervisorMinimumFileStoreV1::open(
            root.path(), signer.clone(),
        ).expect("isolated publisher");
        assert!(CellSplitSupervisorMinimumFileStoreV1::open_existing(
            root.path(), signer.clone(),
        ).is_err(), "read-only query may not contend with a live writer");
        let mut admitted = VerifiedOriginalMinimum {
            allow: true,
            checks: 0,
        };
        store.publish_once(&subject(), &mut admitted)
            .expect("durable admitted original");
    }
    let mut recovered = CellSplitSupervisorMinimumFileStoreV1::open_existing(
        root.path(), signer,
    ).expect("read-only recovery");
    assert!(recovered.read_current(&subject(), &"bb".repeat(32)).is_ok());
}

#[test]
fn signer_replay_cannot_certify_a_different_checkpoint() {
    let root = private_root();
    let key = SigningKey::from_bytes(&[91; 32]);
    let trusted = key.verifying_key();
    let mut source = CellSplitSupervisorMinimumFileStoreV1::open(root.path(), key)
        .expect("signed source");
    let original = subject();
    let mut admission = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    source.publish_once(&original, &mut admission).expect("frozen minimum");
    let proof = source.read_current(&original, &"bb".repeat(32))
        .expect("proof");
    let mut switched = proof.clone();
    switched.subject.journal_authority_epoch = 8;
    assert!(verify_cell_split_supervisor_minimum_online_v1(
        &original, &"bb".repeat(32), &switched, &trusted,
    ).is_err());
    switched = proof.clone();
    switched.original_store_record_digest = "dd".repeat(32);
    assert!(verify_cell_split_supervisor_minimum_online_v1(
        &original, &"bb".repeat(32), &switched, &trusted,
    ).is_err());
}

#[test]
fn minimum_store_denies_publication_without_independent_journal_admission() {
    let root = private_root();
    let mut store = CellSplitSupervisorMinimumFileStoreV1::open(
        root.path(),
        SigningKey::from_bytes(&[91; 32]),
    ).expect("isolated owner");
    let mut admission = VerifiedOriginalMinimum {
        allow: false,
        checks: 0,
    };
    assert!(store.publish_once(&subject(), &mut admission).is_err());
    assert_eq!(admission.checks, 1);
    assert!(!root.path().join(STORE_FILE).exists());
    admission.allow = true;
    store.publish_once(&subject(), &mut admission)
        .expect("independently admitted durable publication");
    assert_eq!(admission.checks, 3);
}

#[test]
fn partial_independent_store_rollback_cannot_reinitialize_minimum() {
    let original = subject();
    for missing in [STORE_FILE, crate::durable::SIDECAR_LOCK_FILE] {
        let root = private_root();
        let signer = SigningKey::from_bytes(&[91; 32]);
        {
            let mut admitted = VerifiedOriginalMinimum {
                allow: true,
                checks: 0,
            };
            let mut store = CellSplitSupervisorMinimumFileStoreV1::open(
                root.path(), signer.clone(),
            ).expect("first independent writer");
            store.publish_once(&original, &mut admitted)
                .expect("real fsync of original minimum");
        }
        fs::remove_file(root.path().join(missing))
            .expect("simulate lost continuity evidence");
        assert!(CellSplitSupervisorMinimumFileStoreV1::open(
            root.path(), signer.clone(),
        ).is_err(), "a missing paired continuity file may not be regenerated");
        assert!(CellSplitSupervisorMinimumFileStoreV1::open_existing(
            root.path(), signer,
        ).is_err(), "read-only recovery must also reject partial restore");
    }
}


/// A complete signed-directory restore is not detectable by local hashes,
/// fsync or an advisory writer lock. This regression documents the exact
/// threat that an independently administered monotonic source must cover.
/// A successful local read here MUST NOT be interpreted as production
/// anti-rollback acceptance or permission to activate the split.
#[test]
fn whole_root_restore_of_signed_minimum_is_not_external_anti_rollback_evidence() {
    let root = private_root();
    let signer = SigningKey::from_bytes(&[91; 32]);
    let current = subject();
    let mut admitted = VerifiedOriginalMinimum {
        allow: true,
        checks: 0,
    };
    let saved_record;
    {
        let mut store = CellSplitSupervisorMinimumFileStoreV1::open(
            root.path(), signer.clone(),
        ).expect("first minimum owner");
        store.publish_once(&current, &mut admitted)
            .expect("fsynced signed checkpoint");
        saved_record = fs::read(root.path().join(STORE_FILE))
            .expect("original signed record");
        assert!(!saved_record.is_empty());
    }
    // Both continuity files are removed, as if an external snapshot provider
    // restored the entire store root. A local lock cannot independently
    // distinguish this from the original legitimate directory.
    fs::remove_file(root.path().join(STORE_FILE))
        .expect("remove current record");
    fs::remove_file(root.path().join(crate::durable::SIDECAR_LOCK_FILE))
        .expect("remove continuity lock");
    {
        use std::io::Write as _;
        use std::os::unix::fs::OpenOptionsExt as _;
        let mut restored = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(root.path().join(STORE_FILE))
            .expect("restore private signed bytes");
        restored.write_all(&saved_record).expect("restore bytes");
        restored.sync_all().expect("restore record durability");
    }
    // An unmatched record without the lock must still fail closed.
    assert!(CellSplitSupervisorMinimumFileStoreV1::open_existing(
        root.path(), signer.clone(),
    ).is_err());
    // Restoring both independently valid local files can defeat this
    // *local-only* continuity indicator; that is precisely why an external
    // rollback-resistant witness is a separate production requirement.
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        let lock = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(root.path().join(crate::durable::SIDECAR_LOCK_FILE))
            .expect("restore private local continuity marker");
        lock.sync_all().expect("restore lock marker durability");
    }
    let mut restored = CellSplitSupervisorMinimumFileStoreV1::open_existing(
        root.path(), signer.clone(),
    ).expect("old signed snapshot is locally indistinguishable");
    let proof = restored.read_current(&current, &"ab".repeat(32))
        .expect("historical signed state");
    verify_cell_split_supervisor_minimum_online_v1(
        &current, &"ab".repeat(32), &proof,
        &signer.verifying_key(),
    ).expect("local signature alone cannot detect whole-root rollback");
}


#[test]
fn monotonic_frontier_rejects_validly_signed_old_checkpoint_and_replayed_challenge() {
    use ed25519_dalek::Signer as _;

    let expected = subject();
    let signer = SigningKey::from_bytes(&[95; 32]);
    let store_record_digest = "cc".repeat(32);
    let nonce = "ee".repeat(32);
    let mut proof = CellSplitSupervisorMonotonicFrontierV1 {
        schema: CELL_SPLIT_SUPERVISOR_MONOTONIC_FRONTIER_SCHEMA_V1.into(),
        journal_domain_id: expected.journal_domain_id.clone(),
        journal_authority_epoch: expected.journal_authority_epoch,
        journal_revision: expected.journal_revision,
        minimum_checkpoint_digest: expected.minimum_checkpoint_digest.clone(),
        original_store_record_digest: store_record_digest.clone(),
        challenge_nonce: nonce.clone(),
        signature_bytes: Vec::new(),
    };
    let seal = |proof: &mut CellSplitSupervisorMonotonicFrontierV1| {
        proof.signature_bytes = signer
            .sign(
                &cell_split_supervisor_monotonic_frontier_signing_payload_v1(proof)
                    .expect("monotonic payload"),
            )
            .to_bytes()
            .to_vec();
    };
    seal(&mut proof);
    verify_cell_split_supervisor_monotonic_frontier_v1(
        &expected,
        &store_record_digest,
        &nonce,
        &proof,
        &signer.verifying_key(),
    )
    .expect("fresh independent frontier matches durable minimum");

    let mut rolled_back = proof.clone();
    rolled_back.journal_revision += 1;
    seal(&mut rolled_back);
    assert!(
        verify_cell_split_supervisor_monotonic_frontier_v1(
            &expected,
            &store_record_digest,
            &nonce,
            &rolled_back,
            &signer.verifying_key(),
        )
        .is_err(),
        "a current high-water at revision 11 rejects a restored revision 10 minimum"
    );

    let mut unrelated = proof.clone();
    unrelated.original_store_record_digest = "dd".repeat(32);
    seal(&mut unrelated);
    assert!(
        verify_cell_split_supervisor_monotonic_frontier_v1(
            &expected,
            &store_record_digest,
            &nonce,
            &unrelated,
            &signer.verifying_key(),
        )
        .is_err(),
        "a separately valid signature for another minimum record cannot be adopted"
    );

    assert!(verify_cell_split_supervisor_monotonic_frontier_v1(
        &expected,
        &store_record_digest,
        &"ff".repeat(32),
        &proof,
        &signer.verifying_key(),
    ).is_err(), "a signed old nonce cannot be replayed");

    assert!(verify_cell_split_supervisor_monotonic_frontier_v1(
        &expected,
        &store_record_digest,
        &nonce,
        &proof,
        &SigningKey::from_bytes(&[96; 32]).verifying_key(),
    ).is_err(), "the minimum writer may not self-select the monotonic key");
}
