//! POSIX lock regression: a separate process probes actual main-file locks.
use super::*;

// SQLite's Unix VFS holds SHARED locks over bytes SHARED_FIRST..+SHARED_SIZE.
// A separate process is essential: POSIX locks are process-owned, not fd-owned.
const LOCK_PROBE: &str = r#"
import errno, fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 510, 0x40000002, os.SEEK_SET)
except OSError as error:
    if error.errno in (errno.EACCES, errno.EAGAIN):
        sys.exit(23)
    raise
else:
    fcntl.lockf(fd, fcntl.LOCK_UN, 510, 0x40000002, os.SEEK_SET)
finally:
    os.close(fd)
"#;

fn main_lock_is_held(path: &Path) -> bool {
    let mut child = Command::new("python3")
        .args(["-c", LOCK_PROBE])
        .arg(path)
        .spawn()
        .expect("independent Python POSIX lock probe");
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 10);
    loop {
        if let Some(status) = child.try_wait().expect("probe status") {
            return match status.code() {
                Some(23) => true,
                Some(0) => false,
                _ => panic!("unexpected lock probe failure: {status}"),
            };
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("independent lock probe exceeded deadline");
        }
        std::thread::sleep(Duration::from_millis(/*millis*/ 10));
    }
}

#[tokio::test]
async fn existing_main_validation_preserves_live_sqlite_posix_locks() {
    // Positive control is a different, disposable DB. Never deliberately lose
    // locks on the actual candidate under test or perform further writes there.
    let control_temp = tempfile::tempdir().expect("control fixture");
    let control_root = control_temp
        .path()
        .canonicalize()
        .expect("canonical control");
    let control = CognitiveStore::open(&layout(&control_root))
        .await
        .expect("control store");
    assert!(
        main_lock_is_held(control.path()),
        "control must initially hold SQLite locks"
    );
    drop(File::open(control.path()).expect("intentional unsafe raw-close control"));
    assert!(
        !main_lock_is_held(control.path()),
        "raw close must demonstrably lose locks"
    );
    control.close().await;
    drop(control);

    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    let first = CognitiveStore::open(&layout(&root))
        .await
        .expect("first pool");
    let expected = first.recovery_anchor().await.expect("initial cut");
    assert!(
        main_lock_is_held(first.path()),
        "first live pool must hold locks"
    );
    let second = CognitiveStore::open(&layout(&root))
        .await
        .expect("independent second pool");
    assert!(
        main_lock_is_held(first.path()),
        "second open must not discard process locks"
    );
    assert_eq!(first.recovery_anchor().await.expect("first cut"), expected);
    assert_eq!(
        second.recovery_anchor().await.expect("second cut"),
        expected
    );
    second.close().await;
    drop(second);
    assert!(
        main_lock_is_held(first.path()),
        "SQLite-owned close must retain first pool locks"
    );
    first.close().await;
    drop(first);
}

#[tokio::test]
async fn competing_first_opens_keep_private_consistent_state_or_fail_closed() {
    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    let owner_layout = layout(&root);
    let (left, right) = tokio::join!(
        CognitiveStore::open(&owner_layout),
        CognitiveStore::open(&owner_layout),
    );
    let mut stores = Vec::new();
    for result in [left, right] {
        match result {
            Ok(store) => stores.push(store),
            // The creation gate is deliberately NOT a migration barrier. A
            // competing migration may fail; never retry or repair to hide it.
            Err(CognitiveStoreError::Unavailable(_) | CognitiveStoreError::Corrupt(_)) => {}
            Err(error) => panic!("unexpected first-open failure: {error}"),
        }
    }
    assert!(!stores.is_empty(), "at least one initializer must finish");
    let expected = stores[0].recovery_anchor().await.expect("winner cut");
    for store in &stores {
        assert_eq!(
            store
                .recovery_anchor()
                .await
                .expect("complete admitted cut"),
            expected
        );
        let integrity: String = sqlx::query_scalar("PRAGMA integrity_check(1)")
            .fetch_one(&store.pool)
            .await
            .expect("integrity result");
        assert_eq!(integrity, "ok");
        for suffix in ["", "-wal", "-shm"] {
            let mut path = store.path().as_os_str().to_os_string();
            path.push(suffix);
            let metadata = fs::symlink_metadata(PathBuf::from(path)).expect("live private bundle");
            assert!(metadata.is_file());
            assert_eq!(metadata.nlink(), 1);
            assert_eq!(metadata.mode() & 0o7777, 0o600);
        }
    }
    for store in stores {
        store.close().await;
        drop(store);
    }
}
