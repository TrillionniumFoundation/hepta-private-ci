use super::*;

use pretty_assertions::assert_eq;

use crate::signed_intent::SIGNED_INTENT_FILE;
use crate::signed_intent::SIGNED_INTENT_RECOVERY_FILE;
use crate::signed_intent::read_intent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent::write_intent;
use crate::signed_intent::write_recovery_directive;

fn write_valid_journals(root: &Path) {
    let transaction = DurableReleaseTransaction::new(
        "agent",
        ReleaseTransactionKind::Upgrade,
        "v1",
        "v2",
        /*rollback_predecessor*/ None,
        /*source_binding*/ None,
        /*target_binding*/ None,
        /*expected_release_state_generation*/ 1,
        /*expected_lifecycle_generation*/ 2,
    )
    .expect("transaction");
    write_release_transaction(root, &transaction).expect("write transaction");
    let intent = crate::SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"reader-grant"),
        "agent",
        crate::H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        /*expected_control_revision*/ 1,
        /*expected_lifecycle_generation*/ 2,
        /*authority_epoch*/ 3,
        crate::SignedIntentStatus::Queued,
    )
    .expect("intent");
    let directive = crate::SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())
        .expect("directive");
    write_intent(root, &intent).expect("write intent");
    write_recovery_directive(root, &directive).expect("write directive");
    assert_eq!(
        read_release_transaction(root).expect("read transaction"),
        Some(transaction)
    );
    assert_eq!(read_intent(root).expect("read intent"), Some(intent));
    assert_eq!(
        read_recovery_directive(root).expect("read directive"),
        Some(directive)
    );
}

fn assert_readers_reject(root: &Path) {
    assert!(read_release_transaction(root).is_err());
    assert!(read_intent(root).is_err());
    assert!(read_recovery_directive(root).is_err());
}

fn filenames() -> [&'static str; 3] {
    [
        RELEASE_TRANSACTION_FILE,
        SIGNED_INTENT_FILE,
        SIGNED_INTENT_RECOVERY_FILE,
    ]
}

#[test]
fn all_release_readers_reject_oversize_and_non_regular_input() {
    let dir = tempfile::tempdir().expect("temporary directory");
    write_valid_journals(dir.path());
    for name in filenames() {
        let path = dir.path().join(name);
        let mut bytes = std::fs::read(&path).expect("valid input");
        bytes.resize(MAX_RELEASE_JOURNAL_BYTES + 1, b' ');
        // Appended JSON whitespace remains valid: rejection must come from
        // the file bound, not from parsing malformed content.
        std::fs::write(path, bytes).expect("oversize input");
    }
    assert_readers_reject(dir.path());
    for name in filenames() {
        let path = dir.path().join(name);
        std::fs::remove_file(&path).expect("remove oversize input");
        std::fs::create_dir(path).expect("non-regular input");
    }
    assert_readers_reject(dir.path());
}

#[cfg(unix)]
#[test]
fn fifo_input_is_rejected_without_waiting_for_a_writer() {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let dir = tempfile::tempdir().expect("temporary directory");
    for name in filenames() {
        let path = CString::new(dir.path().join(name).as_os_str().as_bytes()).expect("fifo path");
        // SAFETY: path is NUL-terminated and valid for this synchronous call.
        assert_eq!(
            unsafe {
                libc::mkfifo(path.as_ptr(), /*mode*/ 0o600)
            },
            0
        );
    }
    assert_readers_reject(dir.path());
}

#[cfg(unix)]
#[test]
fn all_release_readers_reject_symlinks_hardlinks_and_writable_files() {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir().expect("temporary directory");
    let external = tempfile::tempdir().expect("external directory");
    write_valid_journals(external.path());
    for name in filenames() {
        std::os::unix::fs::symlink(external.path().join(name), dir.path().join(name))
            .expect("symlink");
    }
    assert_readers_reject(dir.path());
    for name in filenames() {
        let path = dir.path().join(name);
        std::fs::remove_file(&path).expect("remove symlink");
        std::fs::hard_link(external.path().join(name), path).expect("hardlink");
    }
    assert_readers_reject(dir.path());
    for name in filenames() {
        let path = dir.path().join(name);
        std::fs::remove_file(&path).expect("remove hardlink");
        std::fs::copy(external.path().join(name), &path).expect("valid regular file");
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(/*mode*/ 0o666))
            .expect("unsafe permissions");
    }
    assert_readers_reject(dir.path());
}
