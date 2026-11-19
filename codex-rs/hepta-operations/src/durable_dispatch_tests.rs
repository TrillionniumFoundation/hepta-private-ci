//! Native filesystem markers verify that refusal precedes callback entry.
//! Local fixture signatures exercise control flow, not deployment custody.

use super::*;

struct DispatchFixture {
    directory: tempfile::TempDir,
    store: DurableOperationStore,
    operation: OperationIntentV1,
    claim: DispatchClaim,
    authority: FinalUseAuthority,
    signed: SignedFinalUseGrant,
    _authority_directory: tempfile::TempDir,
    authorized: AuthorizedDispatch,
}

async fn dispatch_fixture(nonce: u8) -> DispatchFixture {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"final-entry-fence");
    let (authority, signed, authority_directory) = authority_fixture(&operation, nonce);
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:final-entry"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("claim row");
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize");
    DispatchFixture {
        directory,
        store,
        operation,
        claim,
        authority,
        signed,
        _authority_directory: authority_directory,
        authorized,
    }
}

#[derive(Clone, Copy, Debug)]
enum Invalidation {
    Expired,
    Recovered,
    Renewed,
    NewGeneration,
}

#[tokio::test]
async fn stale_dispatch_never_crosses_the_effect_boundary() {
    for invalidation in [
        Invalidation::Expired,
        Invalidation::Recovered,
        Invalidation::Renewed,
        Invalidation::NewGeneration,
    ] {
        let mut fixture = dispatch_fixture(41).await;
        match invalidation {
            Invalidation::Expired | Invalidation::Recovered => {
                // Keep the deadline identical in the row and opaque fixture
                // snapshot so Expired exercises time, not a changed lease ID.
                let expired = now_millis().expect("clock");
                sqlx::query(
                    "UPDATE cross_owner_outbox SET lease_until_ms = ?
                     WHERE destination = ? AND scope_id = ? AND operation_id = ?",
                )
                .bind(expired)
                .bind(fixture.operation.destination.as_str())
                .bind(fixture.operation.scope_id.as_str())
                .bind(fixture.operation.operation_id.as_str())
                .execute(&fixture.store.pool)
                .await
                .expect("expire lease fixture");
                fixture.authorized.claim.expires_at_unix_ms =
                    to_u64(expired).expect("expired deadline");
                if matches!(invalidation, Invalidation::Recovered) {
                    fixture
                        .store
                        .recover_expired_leases()
                        .await
                        .expect("recover");
                }
            }
            Invalidation::Renewed => {
                fixture
                    .store
                    .renew_claim(&fixture.claim, Duration::from_secs(30))
                    .await
                    .expect("renew");
            }
            Invalidation::NewGeneration => {
                fixture
                    .store
                    .adopt_unsettled_generation(
                        &fixture.operation.scope_id,
                        &fixture.operation.operation_id,
                        generation(2),
                    )
                    .await
                    .expect("handoff");
            }
        }
        let marker = fixture.directory.path().join("forbidden-effect");
        let result = fixture
            .store
            .execute_authorized(fixture.authorized, |_| {
                std::fs::write(&marker, b"entered").expect("physical effect marker");
                DispatchEffect::Dispatched {
                    value: (),
                    dispatch_digest: Digest32::of_bytes(b"entered"),
                    acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
                }
            })
            .await;
        assert!(
            matches!(result, Err(DurableOperationError::StaleLease)),
            "stale admission must fail before entry: {invalidation:?}"
        );
        assert!(!marker.exists(), "effect occurred after {invalidation:?}");
        assert!(matches!(
            fixture
                .authority
                .claim(&fixture.signed, &fixture.operation.final_use_binding()),
            Err(codex_hepta_contracts::FinalUseError::AlreadyClaimed)
        ));
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_recovery_cannot_interleave_with_dispatch_and_receipt() {
    let fixture = dispatch_fixture(42).await;
    // An independent native connection makes writer contention observable
    // without timing a sleep or weakening the production busy timeout.
    let contender = DurableOperationStore::open(fixture.store.path())
        .await
        .expect("independent recovery owner");

    // busy_timeout is connection-local. Retain every acquired connection
    // until the complete shim-owned pool has been configured.
    let mut connections = Vec::new();
    for _ in 0..contender.pool.options().get_max_connections() {
        let mut connection = contender
            .pool
            .acquire()
            .await
            .expect("independent recovery connection");
        let timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout = 0")
            .fetch_one(&mut *connection)
            .await
            .expect("configure recovery contention");
        assert_eq!(timeout, 0);
        connections.push(connection);
    }
    drop(connections);
    let (start, ready) = tokio::sync::oneshot::channel();
    let (observed, result) = std::sync::mpsc::channel();
    let competing = tokio::spawn(async move {
        ready.await.expect("dispatch entry");
        observed
            .send(contender.recover_expired_leases().await)
            .expect("recovery result");
        contender
    });
    let marker = fixture.directory.path().join("admitted-effect");
    fixture
        .store
        .execute_authorized(fixture.authorized, |_| {
            std::fs::write(&marker, b"entered-once").expect("physical effect marker");
            start.send(()).expect("start competing recovery");
            // This bounded test barrier holds the synchronous entry open only
            // until the independent zero-timeout writer has attempted recovery.
            assert!(matches!(
                result.recv_timeout(Duration::from_secs(5)).expect("recovery attempted"),
                Err(DurableOperationError::Unavailable(message)) if message.contains("locked")
            ));
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"entered-once"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
            }
        })
        .await
        .expect("dispatch and receipt commit");
    let contender = competing.await.expect("recovery task");
    contender
        .recover_expired_leases()
        .await
        .expect("recovery after commit");
    assert_eq!(
        std::fs::read(marker).expect("effect marker"),
        b"entered-once"
    );
    let record = fixture
        .store
        .operation(&fixture.operation.scope_id, &fixture.operation.operation_id)
        .await
        .expect("lookup")
        .expect("record");
    assert_eq!(record.state, DurableOperationState::Dispatched);
    let outbox = fixture
        .store
        .outbox_status(
            &fixture.operation.destination,
            &fixture.operation.scope_id,
            &fixture.operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("row");
    assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
}

#[tokio::test]
async fn dropped_entry_waiting_for_writer_never_dispatches_or_refunds_nonce() {
    use std::future::Future;
    use std::task::Poll;

    let fixture = dispatch_fixture(43).await;
    let blocker = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("hold independent writer");
    let marker = fixture.directory.path().join("cancelled-effect");
    let mut pending = Box::pin(fixture.store.execute_authorized(fixture.authorized, |_| {
        std::fs::write(&marker, b"entered").expect("physical effect marker");
        DispatchEffect::Dispatched {
            value: (),
            dispatch_digest: Digest32::of_bytes(b"entered"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
        }
    }));
    std::future::poll_fn(|context| {
        assert!(pending.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    drop(pending);
    blocker.rollback().await.expect("release writer");
    assert!(!marker.exists(), "cancelled admission entered the callback");
    assert!(matches!(
        fixture
            .authority
            .claim(&fixture.signed, &fixture.operation.final_use_binding()),
        Err(codex_hepta_contracts::FinalUseError::AlreadyClaimed)
    ));
    let record = fixture
        .store
        .operation(&fixture.operation.scope_id, &fixture.operation.operation_id)
        .await
        .expect("lookup")
        .expect("record");
    assert_eq!(record.state, DurableOperationState::Dispatching);
}

#[tokio::test]
async fn old_database_copy_cannot_consume_another_store_owners_dispatch() {
    let fixture = dispatch_fixture(44).await;
    let snapshot = fixture.directory.path().join("old-operations.sqlite3");
    sqlx::query("VACUUM INTO ?")
        .bind(snapshot.to_str().expect("snapshot path"))
        .execute(&fixture.store.pool)
        .await
        .expect("consistent old database copy");
    let old_owner = DurableOperationStore::open(&snapshot)
        .await
        .expect("old copy");
    let before = old_owner
        .operation(&fixture.operation.scope_id, &fixture.operation.operation_id)
        .await
        .expect("old lookup")
        .expect("old row");
    fixture
        .store
        .adopt_unsettled_generation(
            &fixture.operation.scope_id,
            &fixture.operation.operation_id,
            generation(2),
        )
        .await
        .expect("original owner handoff");
    let marker = fixture.directory.path().join("old-copy-effect");
    let result = old_owner
        .execute_authorized(fixture.authorized, |_| {
            std::fs::write(&marker, b"entered").expect("physical effect marker");
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"entered"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
            }
        })
        .await;
    assert!(matches!(
        result,
        Err(DurableOperationError::Invalid("dispatch source owner"))
    ));
    assert!(
        !marker.exists(),
        "old snapshot accepted a foreign owner token"
    );
    let after = old_owner
        .operation(&fixture.operation.scope_id, &fixture.operation.operation_id)
        .await
        .expect("old lookup")
        .expect("old row");
    assert_eq!(after, before);
    assert!(matches!(
        fixture
            .authority
            .claim(&fixture.signed, &fixture.operation.final_use_binding()),
        Err(codex_hepta_contracts::FinalUseError::AlreadyClaimed)
    ));
}

#[tokio::test]
async fn store_clone_keeps_the_original_dispatch_owner() {
    let fixture = dispatch_fixture(45).await;
    let same_owner = fixture.store.clone();
    let marker = fixture.directory.path().join("clone-effect");
    same_owner
        .execute_authorized(fixture.authorized, |_| {
            std::fs::write(&marker, b"entered-once").expect("physical effect marker");
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"entered-once"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
            }
        })
        .await
        .expect("same owner dispatch");
    assert_eq!(
        std::fs::read(marker).expect("effect marker"),
        b"entered-once"
    );
    let record = fixture
        .store
        .operation(&fixture.operation.scope_id, &fixture.operation.operation_id)
        .await
        .expect("lookup")
        .expect("record");
    assert_eq!(record.state, DurableOperationState::Dispatched);
}
