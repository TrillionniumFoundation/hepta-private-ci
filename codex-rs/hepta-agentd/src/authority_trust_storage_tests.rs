#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test fixtures fail immediately on invalid setup; production lints remain enforced"
)]

use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn fifo_trust_snapshot_is_rejected_without_waiting_for_a_writer() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = File::open(directory.path()).unwrap();
    rustix::fs::mknodat(
        &root,
        TRUST_STATE_FILE,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender
            .send(open_private(&root, TRUST_STATE_FILE, Access::Read).is_err())
            .unwrap();
        drop(directory);
    });
    assert!(
        receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("FIFO trust open blocked")
    );
    worker.join().unwrap();
}

#[test]
fn delegated_final_use_owner_rejects_symlink_without_mutating_target() {
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseRevocations;
    use ed25519_dalek::SigningKey;
    use std::collections::BTreeSet;

    let directory = tempfile::tempdir().unwrap();
    let target = directory.path().join("unrelated-owner");
    std::fs::create_dir(&target).unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o755)).unwrap();
    let sentinel = target.join("preserve.txt");
    std::fs::write(&sentinel, b"unrelated owner data").unwrap();
    let authority_root = directory.path().join("final-use-authority");
    std::os::unix::fs::symlink(&target, &authority_root).unwrap();
    let signing_key = SigningKey::from_bytes(&[47; 32]);
    assert!(
        FinalUseAuthority::open_state_dir(
            &authority_root,
            "owner".into(),
            signing_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .is_err()
    );
    assert_eq!(
        std::fs::metadata(&target).unwrap().permissions().mode() & 0o777,
        0o755
    );
    assert_eq!(std::fs::read(sentinel).unwrap(), b"unrelated owner data");
    assert_eq!(std::fs::read_dir(target).unwrap().count(), 1);
}
