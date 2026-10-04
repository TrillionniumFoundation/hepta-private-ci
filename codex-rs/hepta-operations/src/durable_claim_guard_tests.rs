use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct Fixture {
    store: DurableOperationStore,
    claim: DispatchClaim,
    _directory: tempfile::TempDir,
}

impl Fixture {
    async fn new() -> TestResult<Self> {
        let directory = tempfile::tempdir()?;
        let store =
            DurableOperationStore::open(&directory.path().join("operations.sqlite3")).await?;
        let operation = intent(b"original payload");
        store.prepare_intent(&operation).await?;
        let claim = store
            .claim_operation(
                &operation.scope_id,
                &operation.operation_id,
                &stable_id("worker:claim-guard"),
                generation(/*value*/ 1),
                Duration::from_secs(60),
            )
            .await?
            .ok_or("prepared operation must be claimable")?;
        Ok(Self {
            store,
            claim,
            _directory: directory,
        })
    }

    async fn rows(&self) -> TestResult<(Option<DurableOperationRecord>, Option<OutboxStatusV1>)> {
        let operation = &self.claim.intent;
        Ok((
            self.store
                .operation(&operation.scope_id, &operation.operation_id)
                .await?,
            self.store
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await?,
        ))
    }
}

#[tokio::test]
async fn renewal_rejects_intent_drift_and_preserves_the_live_claim() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut predecessor = intent(b"predecessor");
    predecessor.operation_id = stable_id("operation:predecessor");
    fixture.store.prepare_intent(&predecessor).await?;

    let mut payload = fixture.claim.clone();
    payload.intent.payload_digest = Digest32::of_bytes(b"changed payload");
    let mut lineage = fixture.claim.clone();
    lineage.intent.expected_predecessor = Some(predecessor.operation_id);
    let mut owner = fixture.claim.clone();
    owner.intent.owner_generation = generation(/*value*/ 2);
    // The logical digest deliberately excludes the current writer generation.
    assert_eq!(
        owner.intent.semantic_digest(),
        fixture.claim.intent.semantic_digest()
    );
    let before = fixture.rows().await?;
    for changed in [payload, lineage, owner] {
        assert!(matches!(
            fixture
                .store
                .renew_claim(&changed, Duration::from_secs(60))
                .await,
            Err(DurableOperationError::StaleLease)
        ));
        assert_eq!(fixture.rows().await?, before);
    }

    let renewed = fixture
        .store
        .renew_claim(&fixture.claim, Duration::from_secs(60))
        .await?;
    assert_eq!(
        renewed,
        DispatchClaim {
            fence: fixture.claim.fence + 1,
            expires_at_unix_ms: renewed.expires_at_unix_ms,
            ..fixture.claim.clone()
        }
    );
    let after = fixture.rows().await?;
    assert!(matches!(
        fixture
            .store
            .renew_claim(&fixture.claim, Duration::from_secs(60))
            .await,
        Err(DurableOperationError::StaleLease)
    ));
    assert_eq!(fixture.rows().await?, after);
    let next = fixture
        .store
        .renew_claim(&renewed, Duration::from_secs(60))
        .await?;
    assert_eq!(next.fence, renewed.fence + 1);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn renewal_rejects_clock_rollback_without_changing_either_row() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut other = intent(b"another active operation");
    other.scope_id = stable_id("scope:other");
    let original = fixture.store.prepare_intent(&other).await?.record;
    let future = now_millis()? + 3_600_000;
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ? WHERE scope_id = ?")
        .bind(future)
        .bind(other.scope_id.as_str())
        .execute(&fixture.store.pool)
        .await?;
    let before = fixture.rows().await?;
    let other_before = fixture
        .store
        .operation(&other.scope_id, &other.operation_id)
        .await?;
    assert!(matches!(
        fixture
            .store
            .renew_claim(&fixture.claim, Duration::from_secs(60))
            .await,
        Err(DurableOperationError::ClockRollback)
    ));
    assert_eq!(fixture.rows().await?, before);
    assert_eq!(
        fixture
            .store
            .operation(&other.scope_id, &other.operation_id)
            .await?,
        other_before
    );
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ? WHERE scope_id = ?")
        .bind(to_i64(original.updated_at_unix_ms)?)
        .bind(other.scope_id.as_str())
        .execute(&fixture.store.pool)
        .await?;
    fixture
        .store
        .renew_claim(&fixture.claim, Duration::from_secs(60))
        .await?;
    fixture.store.close().await;
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn dispatch_rejects_a_changed_intent_even_with_a_matching_signed_grant() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut changed = fixture.claim.clone();
    changed.intent.payload_digest = Digest32::of_bytes(b"different authorized payload");
    let (authority, signed, _authority_directory) =
        authority_fixture(&changed.intent, /*nonce*/ 61);
    let before = fixture.rows().await?;
    assert!(matches!(
        fixture
            .store
            .authorize_dispatch(&authority, &signed, &changed)
            .await,
        Err(DurableOperationError::StaleLease)
    ));
    assert_eq!(fixture.rows().await?, before);

    let (authority, signed, _valid_directory) =
        authority_fixture(&fixture.claim.intent, /*nonce*/ 62);
    let authorized = fixture
        .store
        .authorize_dispatch(&authority, &signed, &fixture.claim)
        .await?;
    let mut calls = 0;
    fixture
        .store
        .execute_authorized(authorized, |delivered| {
            calls += 1;
            assert_eq!(delivered, &fixture.claim.intent);
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"dispatched original"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"ack original")),
            }
        })
        .await?;
    assert_eq!(calls, 1);
    fixture.store.close().await;
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn renewal_cannot_invalidate_an_authorized_dispatch() -> TestResult {
    let fixture = Fixture::new().await?;
    let (authority, signed, _authority_directory) =
        authority_fixture(&fixture.claim.intent, /*nonce*/ 63);
    let authorized = fixture
        .store
        .authorize_dispatch(&authority, &signed, &fixture.claim)
        .await?;
    let before = fixture.rows().await?;
    assert!(matches!(
        fixture
            .store
            .renew_claim(&fixture.claim, Duration::from_secs(60))
            .await,
        Err(DurableOperationError::InvalidTransition {
            from: DurableOperationState::Dispatching,
            to: "renew_claim",
        })
    ));
    assert_eq!(fixture.rows().await?, before);
    fixture
        .store
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: (),
            dispatch_digest: Digest32::of_bytes(b"authorized dispatch completed"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"acknowledged")),
        })
        .await?;
    let (operation, outbox) = fixture.rows().await?;
    assert_eq!(
        operation.ok_or("operation")?.state,
        DurableOperationState::Dispatched
    );
    assert_eq!(
        outbox.ok_or("outbox")?.state,
        DurableOutboxState::Acknowledged
    );
    fixture.store.close().await;
    Ok(())
}
