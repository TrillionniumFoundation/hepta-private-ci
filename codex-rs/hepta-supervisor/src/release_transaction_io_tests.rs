use super::*;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

fn transaction(target: &str) -> Result<DurableReleaseTransaction, ReleaseTransactionError> {
    DurableReleaseTransaction::new(
        "agent",
        ReleaseTransactionKind::Upgrade,
        "source",
        target,
        /*rollback_predecessor*/ None,
        /*source_binding*/ None,
        /*target_binding*/ None,
        /*expected_release_state_generation*/ 1,
        /*expected_lifecycle_generation*/ 2,
    )
}

#[test]
fn transaction_owner_preserves_full_registered_recovery_fields_and_canonical_bytes() -> TestResult {
    let root = tempfile::tempdir()?;
    let source = ReleaseId::parse("a".repeat(128))?;
    let target = ReleaseId::parse("b".repeat(128))?;
    let predecessor = ReleaseId::parse("c".repeat(128))?;
    let digest = Sha256Digest::for_bytes(b"registered release");
    let binding = |release_id| ReleaseBinding {
        release_id,
        manifest_sha256: digest.as_str().to_string(),
        agentd_program_sha256: digest.as_str().to_string(),
        matrixd_program_sha256: Some(digest.as_str().to_string()),
        admission_frontier_sha256: digest.as_str().to_string(),
    };
    // Even the transaction constructor's most expensive permitted agent ID
    // escaping is covered; ordinary AgentId parsing is more restrictive.
    let value = DurableReleaseTransaction::new(
        "\0".repeat(256),
        ReleaseTransactionKind::ExplicitRollback,
        source.as_str(),
        target.as_str(),
        Some(predecessor.to_string()),
        Some(binding(source.clone())),
        Some(binding(target.clone())),
        u64::MAX,
        u64::MAX,
    )?
    .with_authority(Sha256Digest::for_bytes(b"grant"), u64::MAX)?
    .with_recovery_resolution(
        ReleaseTransactionPhase::RolledBack,
        Sha256Digest::for_bytes(b"recovery decision"),
    )?;
    let canonical = serde_json::to_vec(&value)?;
    assert!(canonical.len() < 8 * 1024);
    write_release_transaction(root.path(), &value)?;
    assert_eq!(
        std::fs::read(root.path().join(RELEASE_TRANSACTION_FILE))?,
        canonical
    );
    assert_eq!(read_release_transaction(root.path())?, Some(value));
    Ok(())
}

#[test]
fn transaction_reader_accepts_exact_budget_and_refuses_overflow_or_directory() -> TestResult {
    let root = tempfile::tempdir()?;
    assert_eq!(read_release_transaction(root.path())?, None);
    let value = transaction("target")?;
    let mut bytes = serde_json::to_vec(&value)?;
    bytes.resize(MAX_TRANSACTION_BYTES as usize, b' ');
    let path = root.path().join(RELEASE_TRANSACTION_FILE);
    std::fs::write(&path, &bytes)?;
    assert_eq!(read_release_transaction(root.path())?, Some(value));
    bytes.push(b' ');
    std::fs::write(&path, &bytes)?;
    assert!(matches!(
        read_release_transaction(root.path()),
        Err(ReleaseTransactionError::Io(error)) if error.kind() == ErrorKind::InvalidData
    ));
    assert_eq!(std::fs::read(&path)?, bytes);
    std::fs::remove_file(&path)?;
    std::fs::create_dir(&path)?;
    assert!(read_release_transaction(root.path()).is_err());
    assert!(path.is_dir());
    Ok(())
}

#[test]
fn transaction_write_bounds_encoding_before_any_durable_mutation() -> TestResult {
    let root = tempfile::tempdir()?;
    let base_bytes = serde_json::to_vec(&transaction("t")?)?.len();
    let target_len = MAX_TRANSACTION_BYTES as usize - base_bytes + 1;
    let exact = transaction(&"t".repeat(target_len))?;
    let exact_bytes = serde_json::to_vec(&exact)?;
    assert_eq!(exact_bytes.len(), MAX_TRANSACTION_BYTES as usize);
    write_release_transaction(root.path(), &exact)?;
    assert_eq!(read_release_transaction(root.path())?, Some(exact));

    let overflow = transaction(&"t".repeat(target_len + 1))?;
    assert!(matches!(
        write_release_transaction(root.path(), &overflow),
        Err(ReleaseTransactionError::Serialization(error)) if error.is_io()
    ));
    assert_eq!(
        std::fs::read(root.path().join(RELEASE_TRANSACTION_FILE))?,
        exact_bytes
    );
    let entries = std::fs::read_dir(root.path())?
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(
        entries,
        vec![std::ffi::OsString::from(RELEASE_TRANSACTION_FILE)]
    );
    let absent_root = root.path().join("not-created");
    assert!(write_release_transaction(&absent_root, &overflow).is_err());
    assert!(!absent_root.exists());
    Ok(())
}

#[cfg(unix)]
#[test]
fn transaction_reader_refuses_symlinks_and_fifo_without_waiting_for_a_writer() -> TestResult {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let root = tempfile::tempdir()?;
    let external = root.path().join("external");
    let bytes = serde_json::to_vec(&transaction("target")?)?;
    std::fs::write(&external, &bytes)?;
    let path = root.path().join(RELEASE_TRANSACTION_FILE);
    std::os::unix::fs::symlink(&external, &path)?;
    assert!(read_release_transaction(root.path()).is_err());
    assert_eq!(std::fs::read(&external)?, bytes);
    std::fs::remove_file(&path)?;
    std::os::unix::fs::symlink(root.path().join("absent"), &path)?;
    assert!(read_release_transaction(root.path()).is_err());
    std::fs::remove_file(&path)?;
    assert!(
        std::process::Command::new("mkfifo")
            .arg(&path)
            .status()?
            .success()
    );
    let run_root = root.path().to_path_buf();
    let (sender, receiver) = mpsc::channel();
    let worker =
        std::thread::spawn(move || sender.send(read_release_transaction(&run_root)).unwrap());
    let result = receiver.recv_timeout(Duration::from_secs(2));
    if matches!(result, Err(mpsc::RecvTimeoutError::Timeout)) {
        // Release a regressed blocking reader before joining, without turning
        // its timeout into success or leaving a hanging test process behind.
        let rescue = OpenOptions::new()
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(&path)?;
        drop(rescue);
        worker.join().unwrap();
        panic!("transaction read waited for a FIFO writer");
    }
    worker.join().unwrap();
    assert!(matches!(
        result?,
        Err(ReleaseTransactionError::Io(error)) if error.kind() == ErrorKind::InvalidData
    ));
    Ok(())
}

#[cfg(unix)]
#[test]
fn transaction_directory_sync_refuses_non_directory_and_symlink_endpoints() -> TestResult {
    let root = tempfile::tempdir()?;
    sync_directory(root.path())?;
    let link = root.path().join("link");
    std::os::unix::fs::symlink(root.path(), &link)?;
    assert!(sync_directory(&link).is_err());
    let regular = root.path().join("regular");
    std::fs::write(&regular, b"retained")?;
    assert!(sync_directory(&regular).is_err());
    assert_eq!(std::fs::read(&regular)?, b"retained");
    Ok(())
}
