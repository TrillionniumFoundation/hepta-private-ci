use super::*;
use codex_hepta_contracts::FinalUseError;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_config_reopens_original_spent_nonce_and_frontier() -> Result<()> {
    let root = tempfile::tempdir()?;
    let (original, mut issuer) =
        independent_ordinary_test_authorizer_v2(root.path(), /*count*/ 2).await?;
    drop(original);
    let path = root.path().join("pq-config.json");
    let authorizer = UnixFinalUseAuthorizer::open(&path)?;
    let clock = authorizer.protected_clock().ok_or("PQ clock missing")?;
    let before = clock.now_unix_ms()?;
    tokio::time::sleep(Duration::from_millis(2)).await;
    assert!(clock.now_unix_ms()? > before);
    let binding = FinalUseBinding {
        subject_id: "ordinary-worker".into(),
        destination_id: "runtime".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let token = authorizer.claim_exact(binding.clone()).await?;
    assert!(token.enter(&binding)?.matches(&binding));
    let replay = issuer.last_grant.lock().unwrap().clone().unwrap();
    let before_reopen = authorizer.authority.frontier()?;
    drop(authorizer);
    let reopened = UnixFinalUseAuthorizer::open(&path)?;
    assert_eq!(reopened.authority.frontier()?, before_reopen);
    assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
    assert!(matches!(
        reopened.authority.claim(&replay, &binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    assert_eq!(reopened.authority.frontier()?, before_reopen);
    let token = reopened.claim_exact(binding.clone()).await?;
    assert!(token.enter(&binding)?.matches(&binding));
    assert_eq!(reopened.authority.capacity()?.used_nonces, 2);
    let stored: FinalUseFrontier =
        serde_json::from_slice(&std::fs::read(root.path().join("external-frontier.json"))?)?;
    assert_eq!(stored, reopened.authority.frontier()?);
    assert!(reopened.claim_exact(binding).await.is_err());
    issuer.finish_owned().await?;
    assert!(clock.now_unix_ms().is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_services_close_on_abort_and_drop() -> Result<()> {
    let root = tempfile::tempdir()?;
    let (authorizer, mut issuer) =
        independent_ordinary_test_authorizer_v2(root.path(), /*count*/ 1).await?;
    issuer.abort_and_join().await?;
    assert!(authorizer.protected_clock().unwrap().now_unix_ms().is_err());
    let root = tempfile::tempdir()?;
    let (authorizer, issuer) =
        independent_ordinary_test_authorizer_v2(root.path(), /*count*/ 0).await?;
    drop(issuer);
    assert!(authorizer.protected_clock().unwrap().now_unix_ms().is_err());
    Ok(())
}
