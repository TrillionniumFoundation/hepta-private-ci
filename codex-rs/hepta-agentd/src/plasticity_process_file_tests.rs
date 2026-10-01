use std::fs;
use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::objective_runtime::tests::run_start_owner_fixture;

const LIMIT: u64 = 4096;
const LABEL: &str = "independently pinned bootstrap file";

#[test]
fn mutable_bootstrap_files_reject_group_or_world_write_before_owner_callback() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("mutable-journal");
    fs::write(&path, b"retained owner bytes").expect("existing journal");
    for mode in [0o620, 0o602, 0o666] {
        fs::set_permissions(&path, fs::Permissions::from_mode(mode))
            .expect("unsafe mutable permissions");
        let mut owner_called = false;
        let result = open_existing_rw(&path, LABEL).map(|_file| owner_called = true);
        assert!(result.is_err(), "unsafe mutable mode {mode:o}");
        assert!(!owner_called);
        assert_eq!(
            fs::read(&path).expect("untouched journal"),
            b"retained owner bytes"
        );
    }
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))
        .expect("private mutable permissions");
    drop(open_existing_rw(&path, LABEL).expect("private mutable owner file"));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644))
        .expect("read-only input compatibility");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("ordinary read-only owner input"),
        b"retained owner bytes"
    );
}

#[test]
fn hardlinked_mutable_bootstrap_file_is_rejected_before_owner_callback() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("mutable-registry");
    let alias = identity.home_root.join("registry-alias");
    fs::write(&path, b"retained registry bytes").expect("existing registry");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private registry");
    fs::hard_link(&path, &alias).expect("second registry link");
    let mut owner_called = false;
    let result = open_existing_rw(&path, LABEL).map(|_file| owner_called = true);
    assert!(result.is_err());
    assert!(!owner_called);
    assert_eq!(
        fs::read(&alias).expect("untouched registry alias"),
        b"retained registry bytes"
    );
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644))
        .expect("read-only input compatibility");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("read-only linked input retains owner contract"),
        b"retained registry bytes"
    );
    fs::remove_file(alias).expect("remove second mutable link");
    drop(open_existing_rw(&path, LABEL).expect("single-link mutable registry"));
}

#[test]
fn unsafe_ancestor_rejects_descriptor_reads_rw_open_and_new_registry_creation() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("bootstrap.json");
    fs::write(&path, b"pinned bytes").expect("installed bootstrap bytes");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private bootstrap file");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("bounded read"),
        b"pinned bytes"
    );
    drop(open_existing_rw(&path, LABEL).expect("existing owner file"));
    let registry = identity.home_root.join("new-registry");
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(read_bounded(&path, LIMIT, LABEL).is_err());
    assert!(open_existing_rw(&path, LABEL).is_err());
    assert!(create_new_rw(&registry, LABEL).is_err());
    assert!(!registry.exists());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("trusted sticky read"),
        b"pinned bytes"
    );
    drop(open_existing_rw(&path, LABEL).expect("trusted sticky reopen"));
    drop(create_new_rw(&registry, LABEL).expect("trusted sticky new registry"));
    assert_eq!(
        fs::metadata(registry)
            .expect("registry metadata")
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

#[test]
fn unsafe_immediate_parent_rejects_descriptor_read_and_existing_journal_open() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("journal");
    fs::write(&path, b"retained owner bytes").expect("existing journal");
    fs::set_permissions(&identity.home_root, fs::Permissions::from_mode(0o777))
        .expect("unsafe parent");
    assert!(read_bounded(&path, LIMIT, LABEL).is_err());
    assert!(open_existing_rw(&path, LABEL).is_err());
    assert_eq!(
        fs::read(path).expect("untouched journal"),
        b"retained owner bytes"
    );
}

#[test]
fn native_snapshot_callback_cannot_accept_same_length_path_substitution() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("snapshot");
    let replacement = identity.home_root.join("replacement");
    fs::write(&path, b"trusted").expect("existing snapshot");
    fs::write(&replacement, b"revoked").expect("substitute snapshot");
    let result = read_existing(&path, LABEL, |mut file| {
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        fs::rename(&replacement, &path)?;
        Ok(bytes)
    });
    assert!(result.is_err());
}

#[test]
fn native_snapshot_callback_rechecks_namespace_before_returning_bytes() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("snapshot");
    fs::write(&path, b"trusted").expect("existing snapshot");
    let result = read_existing(&path, LABEL, |mut file| {
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777))?;
        Ok(bytes)
    });
    assert!(result.is_err());
}

#[test]
fn inspected_bootstrap_fifo_replacement_is_rejected_for_both_access_modes() {
    use std::os::unix::fs::OpenOptionsExt;
    use std::process::Command;
    use std::sync::mpsc;
    use std::time::Duration;

    for access in [ExistingAccess::ReadOnly, ExistingAccess::ReadWrite] {
        let (_temp, identity) = run_start_owner_fixture();
        let path = identity.home_root.join("bootstrap");
        fs::write(&path, b"trusted").expect("bootstrap file");
        let inspected =
            BootstrapFilePreflight::inspect(&path, access, LABEL).expect("regular preflight");
        fs::remove_file(&path).expect("replace inspected file");
        assert!(
            Command::new("mkfifo")
                .args(["-m", "600"])
                .arg(&path)
                .status()
                .expect("POSIX mkfifo")
                .success()
        );
        let (done, received) = mpsc::channel();
        let worker = std::thread::spawn(move || {
            let _ = done.send(inspected.open(LABEL).is_err());
        });
        let first = received.recv_timeout(Duration::from_secs(/*secs*/ 1));
        let timely = first.is_ok();
        // ReadWrite FIFO opens may already be finite; descriptor admission
        // must still reject that type. ReadOnly must not wait for a writer.
        let _cleanup = (!timely).then(|| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW)
                .open(&path)
                .expect("FIFO cleanup keeper")
        });
        let rejected = first.unwrap_or_else(|_| {
            received
                .recv_timeout(Duration::from_secs(/*secs*/ 1))
                .expect("FIFO cleanup releases worker")
        });
        worker.join().expect("open worker");
        assert!(timely, "replacement FIFO waited for a writer");
        assert!(
            rejected,
            "replacement FIFO was admitted as a bootstrap file"
        );
    }
}

#[test]
fn inspected_bootstrap_symlink_replacement_is_rejected_for_both_access_modes() {
    for access in [ExistingAccess::ReadOnly, ExistingAccess::ReadWrite] {
        let (_temp, identity) = run_start_owner_fixture();
        let path = identity.home_root.join("bootstrap");
        let retained = identity.home_root.join("retained");
        fs::write(&path, b"trusted").expect("bootstrap file");
        let inspected =
            BootstrapFilePreflight::inspect(&path, access, LABEL).expect("regular preflight");
        fs::rename(&path, &retained).expect("retain original inode");
        std::os::unix::fs::symlink(&retained, &path).expect("replacement final symlink");
        match inspected
            .open(LABEL)
            .err()
            .expect("reject replacement symlink")
        {
            AgentdError::Io(error) => assert_eq!(error.raw_os_error(), Some(libc::ELOOP)),
            error => panic!("expected the real no-follow open to reject the symlink: {error}"),
        }
    }
}

#[test]
fn protected_bootstrap_open_retains_read_write_access() {
    use std::io::Seek;
    use std::io::Write;

    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("bootstrap");
    fs::write(&path, b"trusted").expect("bootstrap file");
    let mut file = open_existing_rw(&path, LABEL).expect("read-write owner file");
    file.write_all(b"updated").expect("owner write");
    file.rewind().expect("owner read position");
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).expect("owner read");
    assert_eq!(bytes, b"updated");
}
