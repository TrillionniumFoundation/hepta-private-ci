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
