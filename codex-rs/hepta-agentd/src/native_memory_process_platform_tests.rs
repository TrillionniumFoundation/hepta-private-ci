#![cfg(all(test, not(unix)))]

use super::execute;

#[tokio::test]
async fn native_memory_refuses_unsupported_process_group_platform_before_io() {
    let temp = tempfile::tempdir().unwrap();
    let config = crate::native_memory_test_support::config(temp.path());
    let error = execute(
        &config,
        b"unspawned".to_vec(),
        &tokio_util::sync::CancellationToken::new(),
        || Ok(()),
    )
    .await
    .unwrap_err();
    assert!(error.contains("process-group ownership is unavailable"));
    assert!(std::fs::read_dir(temp.path()).unwrap().next().is_none());
}
