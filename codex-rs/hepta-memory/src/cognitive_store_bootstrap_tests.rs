use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test]
async fn fresh_cognitive_bootstrap_protects_live_database_and_both_sidecars() -> TestResult {
    let temp = tempfile::tempdir()?;
    let owner = crate::cognitive_test_support::agent_id(193);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await?;
    store.recovery_anchor().await?;
    for suffix in ["", "-wal", "-shm"] {
        let path = PathBuf::from(format!("{}{suffix}", store.path().display()));
        let metadata = fs::symlink_metadata(&path)?;
        assert!(metadata.is_file());
        assert_eq!((metadata.mode() & 0o7777, metadata.nlink()), (0o600, 1));
    }
    store.pool.close().await;
    Ok(())
}

#[tokio::test]
async fn explicit_close_keeps_original_guard_until_checked_out_sqlite_connection_returns() -> TestResult {
    use std::future::Future;
    use std::task::Poll;

    let temp = tempfile::tempdir()?;
    let owner = crate::cognitive_test_support::agent_id(194);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await?;
    let pool = store.pool.clone();
    let connection = pool.acquire().await?;
    let closing = store.close();
    tokio::pin!(closing);
    std::future::poll_fn(|context| {
        assert!(closing.as_mut().poll(context).is_pending());
        Poll::Ready(())
    }).await;
    assert!(pool.is_closed());
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(layout.cognitive_root()).is_err());
    drop(connection);
    closing.await;
    let _exclusive = CognitiveStoreOpenGuard::acquire_exclusive(layout.cognitive_root())?;
    Ok(())
}

#[tokio::test]
async fn closed_pool_does_not_drop_another_store_clones_original_guard() -> TestResult {
    let temp = tempfile::tempdir()?;
    let owner = crate::cognitive_test_support::agent_id(195);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await?;
    let other = store.clone();
    store.close().await;
    assert!(other.pool.is_closed());
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(layout.cognitive_root()).is_err());
    drop(other);
    let _exclusive = CognitiveStoreOpenGuard::acquire_exclusive(layout.cognitive_root())?;
    Ok(())
}
