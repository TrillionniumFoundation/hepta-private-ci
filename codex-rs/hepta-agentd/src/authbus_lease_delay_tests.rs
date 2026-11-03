use super::*;

#[tokio::test]
async fn trust_refresh_sqlite_wait_cannot_authorize_transport_with_an_expired_lease() {
    for algorithm in [AuthBusAlgorithm::Ed25519V1, AuthBusAlgorithm::MlDsa65V2] {
        let fixture = Fixture::with_algorithm(algorithm).await;
        let id = submit(&fixture.state, fixture.request(1))
            .await
            .unwrap()
            .delivery_id
            .parse()
            .unwrap();
        let host = attached(&fixture.state).unwrap();
        let issuer = host.trust(&fixture.state).await.unwrap().issuer().unwrap();
        let config = codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &fixture.state.identity().home_root,
            )
            .unwrap(),
        );
        let pool = config
            .open_durable_evidence_pool(
                &config
                    .home()
                    .join(codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE),
            )
            .await
            .unwrap();
        let delivery = host
            .evidence
            .claim_authbus_delivery(
                &issuer,
                AuthBusClaimRequest {
                    delivery_id: id,
                    subject_id: &host.subject,
                    scope_digest: host.scope,
                    worker_id: &StableId::new("fixture:delayed-worker").unwrap(),
                    lease_ms: 50,
                },
            )
            .await
            .unwrap();
        let before = host.evidence.authbus_delivery_status(id).await.unwrap();
        let blocker = pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
        let queue = ReplyLostQueue::default();
        let relay = deliver(&fixture.state, &host, &queue, delivery);
        tokio::pin!(relay);
        tokio::select! {
            result = &mut relay => panic!("relay bypassed the held trust transaction: {result:?}"),
            () = tokio::time::sleep(Duration::from_millis(100)) => {}
        }
        blocker.rollback().await.unwrap();
        assert!(relay.await.is_err());
        assert!(queue.modes.lock().unwrap().is_empty());
        assert!(queue.accepted.lock().unwrap().is_empty());
        assert_eq!(
            host.evidence.authbus_delivery_status(id).await.unwrap(),
            before
        );
    }
}
