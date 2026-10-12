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
