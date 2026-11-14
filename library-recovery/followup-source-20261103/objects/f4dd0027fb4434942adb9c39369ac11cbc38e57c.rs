use super::*;
use codex_hepta_cognitive_store::ProductionWriterError;
use codex_hepta_memory::LocalLeaseOutboxError;

#[tokio::test]
async fn cancellation_of_real_bao_entry_preserves_holds_and_releases_exclusion() {
    let (client, server, accepted, release) = tls_server(true).await.unwrap();
    let f = Arc::new(fixture(client, false, false).await);
    let dispatch_fixture = Arc::clone(&f);
    let dispatch = tokio::spawn(async move {
        dispatch_fixture
            .dispatcher
            .dispatch(
                &dispatch_fixture.writer,
                &dispatch_fixture.owner_grant,
                &dispatch_fixture.owner_binding,
                dispatch_fixture.queued.clone(),
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), accepted)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        f.writer.release().await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::LeaseEntryInProgress { .. }
        ))
    ));
    assert!(matches!(
        f.writer
            .apply("operation:registered-bao", "fixture premature outcome")
            .await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::EntryInProgress { .. }
        ))
    ));
    dispatch.abort();
    assert!(dispatch.await.unwrap_err().is_cancelled());
    assert_eq!(
        f.writer.status("operation:registered-bao").await.unwrap(),
        LocalOutcomeState::Indeterminate
    );
    let quota = f.authbus.read().quota_snapshot(&f.quota).await.unwrap();
    assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
    assert_eq!(f.delivered.load(Ordering::SeqCst), 0);
    assert!(
        f.dispatcher
            .dispatch(
                &f.writer,
                &f.owner_grant,
                &f.owner_binding,
                f.queued.clone()
            )
            .await
            .is_err()
    );
    // The canceled provider cannot receive a new owner grant/dispatch attempt.
    // Releasing the pause only lets the fixture server observe the closed peer.
    let _ = release.send(());
    let _ = server.await.unwrap();
    assert_eq!(f.delivered.load(Ordering::SeqCst), 0);
    // The active entry is gone, so closure reaches the independent durable
    // unresolved-occurrence fence. Cancellation cannot make that effect safe.
    assert!(matches!(
        f.writer.release().await,
        Err(ProductionWriterError::Local(LocalLeaseOutboxError::IllegalTransition(reason)))
            if reason == "cannot terminalize lease with unresolved local occurrences: operation:registered-bao"
    ));
    assert_eq!(
        f.writer.status("operation:registered-bao").await.unwrap(),
        LocalOutcomeState::Indeterminate
    );
}
