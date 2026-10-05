use super::*;

#[test]
fn relative_configuration_path_reads_the_selected_regular_file() {
    let current = std::env::current_dir().expect("current directory");
    let temporary = tempfile::tempdir_in(&current).expect("relative path fixture");
    let path = temporary.path().join("host.json");
    let bytes = b"{\"selected\":true}";
    std::fs::write(&path, bytes).expect("host configuration");
    let relative = path.strip_prefix(&current).expect("relative fixture path");
    assert_eq!(
        bounded_file(relative.to_path_buf(), MAX_HOST_CONFIG_BYTES).expect("relative host config"),
        bytes
    );
}

#[test]
fn configuration_reads_reject_bytes_beyond_the_cap_and_accept_the_exact_cap() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let path = temporary.path().join("host.json");
    let bytes = vec![7; MAX_HOST_CONFIG_BYTES as usize];
    std::fs::write(&path, &bytes).expect("exact-cap configuration");
    assert_eq!(
        bounded_file(path.clone(), MAX_HOST_CONFIG_BYTES).expect("exact cap"),
        bytes
    );
    std::fs::write(&path, vec![7; MAX_HOST_CONFIG_BYTES as usize + 1])
        .expect("overflow configuration");
    assert!(bounded_file(path, MAX_HOST_CONFIG_BYTES).is_err());
}

#[cfg(unix)]
#[test]
fn initial_leaf_alias_hard_link_and_readonly_permissions_remain_supported() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let path = temporary.path().join("host.json");
    let bytes = b"readonly selected configuration";
    std::fs::write(&path, bytes).expect("host configuration");
    let linked = temporary.path().join("host-hardlink.json");
    std::fs::hard_link(&path, &linked).expect("initial hard link");
    let alias = temporary.path().join("host-alias.json");
    symlink(&path, &alias).expect("initial leaf alias");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o400))
        .expect("readonly configuration");
    for selected in [path, linked, alias] {
        assert_eq!(
            bounded_file(selected, MAX_HOST_CONFIG_BYTES).expect("compatible input"),
            bytes
        );
    }
}

#[cfg(unix)]
fn make_fifo(path: &std::path::Path) {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let encoded = CString::new(path.as_os_str().as_bytes()).expect("FIFO path");
    // SAFETY: encoded is a live, NUL-terminated pathname and mode is valid.
    let result = unsafe {
        libc::mkfifo(encoded.as_ptr(), /*mode*/ 0o600)
    };
    assert_eq!(
        result,
        0,
        "create FIFO: {}",
        std::io::Error::last_os_error()
    );
}

#[cfg(unix)]
fn rejects_without_a_fifo_writer(fifo: PathBuf, operation: impl FnOnce() -> bool + Send + 'static) {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        sender.send(operation()).expect("report file rejection");
    });
    let outcome = receiver.recv_timeout(Duration::from_secs(1));
    let returned_without_writer = outcome.is_ok();
    let rejected = match outcome {
        Ok(rejected) => rejected,
        Err(_) => {
            // Release a regressed blocking open/read before reporting failure.
            // O_RDWR keeps this cleanup open finite even with no other reader.
            let mut rescue = OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(fifo)
                .expect("FIFO timeout cleanup");
            std::io::Write::write_all(&mut rescue, b"timeout-cleanup")
                .expect("release a blocked FIFO reader");
            drop(rescue);
            receiver
                .recv_timeout(Duration::from_secs(2))
                .expect("FIFO worker must retire after cleanup")
        }
    };
    worker.join().expect("file-read worker");
    assert!(
        returned_without_writer,
        "configuration read waited for a FIFO writer"
    );
    assert!(rejected, "nonregular configuration must be rejected");
}

#[cfg(unix)]
#[test]
fn direct_fifo_configuration_is_rejected_without_waiting_for_a_writer() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let fifo = temporary.path().join("host.json");
    make_fifo(&fifo);
    let selected = fifo.clone();
    rejects_without_a_fifo_writer(fifo, move || {
        bounded_file(selected, MAX_HOST_CONFIG_BYTES).is_err()
    });
}

#[cfg(unix)]
#[test]
fn fifo_replacement_after_real_preflight_cannot_block_the_open() {
    let temporary = tempfile::tempdir().expect("private fixture");
    let path = temporary.path().join("host.json");
    std::fs::write(&path, b"selected configuration").expect("original configuration");
    let preflight = ConfigFilePreflight::capture(path.clone()).expect("real production preflight");
    std::fs::rename(&path, temporary.path().join("parked.json")).expect("retire original inode");
    make_fifo(&path);
    rejects_without_a_fifo_writer(path, move || preflight.read(MAX_HOST_CONFIG_BYTES).is_err());
}

#[cfg(unix)]
#[test]
fn symlink_replacement_after_real_preflight_is_rejected() {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let temporary = tempfile::tempdir().expect("private fixture");
    let path = temporary.path().join("host.json");
    std::fs::write(&path, b"selected configuration").expect("original configuration");
    let preflight = ConfigFilePreflight::capture(path.clone()).expect("real production preflight");
    let target = temporary.path().join("other.json");
    std::fs::write(&target, b"different configuration").expect("different configuration");
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o400))
        .expect("target permissions");
    let before = (
        std::fs::read(&target).expect("original target bytes"),
        std::fs::symlink_metadata(&target)
            .expect("original target metadata")
            .mode(),
    );
    std::fs::rename(&path, temporary.path().join("parked.json")).expect("retire original inode");
    symlink(&target, &path).expect("replacement symlink");
    let error = preflight
        .read(MAX_HOST_CONFIG_BYTES)
        .expect_err("native no-follow rejection");
    assert_eq!(
        error
            .downcast_ref::<std::io::Error>()
            .and_then(std::io::Error::raw_os_error),
        Some(libc::ELOOP)
    );
    assert_eq!(
        (
            std::fs::read(&target).expect("target bytes unchanged"),
            std::fs::symlink_metadata(&target)
                .expect("target metadata unchanged")
                .mode(),
        ),
        before
    );
}
