use super::*;

use sqlx::Row;
use sqlx::TypeInfo;
use sqlx::ValueRef;
use sqlx::sqlite::SqliteRow;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

#[derive(Debug, Eq, PartialEq)]
enum StoredCell {
    Null,
    Integer(i64),
    Text(String),
    Blob(Vec<u8>),
}

#[derive(Debug, Eq, PartialEq)]
struct OwnerRows {
    ledger: Vec<Vec<StoredCell>>,
    outbox: Vec<Vec<StoredCell>>,
    tombstones: Vec<Vec<StoredCell>>,
}

fn raw_cells(row: SqliteRow) -> TestResult<Vec<StoredCell>> {
    (0..row.len())
        .map(|index| {
            let raw = row.try_get_raw(index)?;
            if raw.is_null() {
                return Ok(StoredCell::Null);
            }
            match raw.type_info().name() {
                "INTEGER" => Ok(StoredCell::Integer(row.try_get(index)?)),
                "TEXT" => Ok(StoredCell::Text(row.try_get(index)?)),
                "BLOB" => Ok(StoredCell::Blob(row.try_get(index)?)),
                other => Err(format!("unexpected owner snapshot storage type: {other}").into()),
            }
        })
        .collect()
}

struct RenewalFixture {
    store: DurableOperationStore,
    claim: DispatchClaim,
    predecessor: OperationIntentV1,
    // Retain the private directory until the store handle has been dropped.
    _directory: tempfile::TempDir,
}

impl RenewalFixture {
    async fn new() -> TestResult<Self> {
        let directory = tempfile::tempdir()?;
        let store =
            DurableOperationStore::open(&directory.path().join("operations.sqlite3")).await?;
        let mut predecessor = intent(b"already prepared predecessor");
        predecessor.operation_id = stable_id("operation:existing-predecessor");
        predecessor.destination = stable_id("destination:predecessor");
        store.prepare_intent(&predecessor).await?;
        let target = intent(b"renewal owner payload");
        store.prepare_intent(&target).await?;
        let claim = store
            .claim_operation(
                &target.scope_id,
                &target.operation_id,
                &stable_id("worker:renewal-guard"),
                generation(/*value*/ 1),
                Duration::from_secs(60),
            )
            .await?
            .ok_or("exact prepared target must be claimable")?;
        Ok(Self {
            store,
            claim,
            predecessor,
            _directory: directory,
        })
    }

    fn assert_original_lease_is_live(&self) -> TestResult<()> {
        assert!(
            to_u64(now_millis()?)? < self.claim.expires_at_unix_ms,
            "fixture must remain inside its original lease window"
        );
        Ok(())
    }

    async fn rows(&self) -> TestResult<OwnerRows> {
        let ledger = sqlx::query("SELECT * FROM operation_ledger ORDER BY scope_id, operation_id")
            .fetch_all(&self.store.pool)
            .await?
            .into_iter()
            .map(raw_cells)
            .collect::<TestResult<_>>()?;
        let outbox = sqlx::query(
            "SELECT * FROM cross_owner_outbox ORDER BY destination, scope_id, operation_id",
        )
        .fetch_all(&self.store.pool)
        .await?
        .into_iter()
        .map(raw_cells)
        .collect::<TestResult<_>>()?;
        let tombstones =
            sqlx::query("SELECT * FROM operation_tombstones ORDER BY scope_id, operation_id")
                .fetch_all(&self.store.pool)
                .await?
                .into_iter()
                .map(raw_cells)
                .collect::<TestResult<_>>()?;
        Ok(OwnerRows {
            ledger,
            outbox,
            tombstones,
        })
    }

    async fn assert_intent_drift_is_rejected(&self, changed: &DispatchClaim) -> TestResult<()> {
        self.assert_original_lease_is_live()?;
        let before = self.rows().await?;
        let result = self
            .store
            .renew_claim(changed, Duration::from_secs(60))
            .await;
        self.assert_original_lease_is_live()?;
        // This proposal deliberately chooses StaleLease for a lease whose
        // complete current intent no longer matches, rather than accepting
        // unrelated database/unavailability errors as a passing refusal.
        assert!(
            matches!(&result, Err(DurableOperationError::StaleLease)),
            "intent drift must be refused semantically: {result:?}"
        );
        assert_eq!(self.rows().await?, before);
        let renewed = self
            .store
            .renew_claim(&self.claim, Duration::from_secs(60))
            .await?;
        assert_eq!(renewed.intent, self.claim.intent);
        assert_eq!(renewed.fence, self.claim.fence + 1);
        self.store.close().await;
        Ok(())
    }
}

#[tokio::test]
async fn renewal_accepts_the_exact_live_intent_and_advances_one_fence() -> TestResult<()> {
    let fixture = RenewalFixture::new().await?;
    fixture.assert_original_lease_is_live()?;
    let before = fixture
        .store
        .operation(
            &fixture.claim.intent.scope_id,
            &fixture.claim.intent.operation_id,
        )
        .await?
        .ok_or("target ledger row")?;
    let before_idempotent_prepare = fixture.rows().await?;
    let prepared = fixture.store.prepare_intent(&fixture.claim.intent).await?;
    assert_eq!(prepared.disposition, PrepareDisposition::AlreadyPresent);
    assert_eq!(fixture.rows().await?, before_idempotent_prepare);
    let before_clock = to_u64(now_millis()?)?;
    let renewed = fixture
        .store
        .renew_claim(&fixture.claim, Duration::from_secs(60))
        .await?;
    let after_clock = to_u64(now_millis()?)?;
    assert_eq!(
        renewed,
        DispatchClaim {
            intent: fixture.claim.intent.clone(),
            worker_id: fixture.claim.worker_id.clone(),
            owner_generation: fixture.claim.owner_generation,
            fence: fixture.claim.fence + 1,
            attempts: fixture.claim.attempts,
            expires_at_unix_ms: renewed.expires_at_unix_ms,
        }
    );
    assert!((before_clock + 60_000..=after_clock + 60_000).contains(&renewed.expires_at_unix_ms));
    let after = fixture
        .store
        .operation(
            &fixture.claim.intent.scope_id,
            &fixture.claim.intent.operation_id,
        )
        .await?
        .ok_or("renewed ledger row")?;
    let outbox = fixture
        .store
        .outbox_status(
            &fixture.claim.intent.destination,
            &fixture.claim.intent.scope_id,
            &fixture.claim.intent.operation_id,
        )
        .await?
        .ok_or("renewed outbox row")?;
    assert_eq!(after.intent, before.intent);
    assert_eq!(after.state, before.state);
    assert_eq!(after.revision, before.revision + 1);
    assert_eq!(after.writer_fence, renewed.fence);
    assert!(after.updated_at_unix_ms >= before.updated_at_unix_ms);
    assert_eq!(outbox.intent, fixture.claim.intent);
    assert_eq!(outbox.worker_id, Some(fixture.claim.worker_id.clone()));
    assert_eq!(
        (outbox.fence, outbox.attempts, outbox.lease_until_unix_ms),
        (
            renewed.fence,
            fixture.claim.attempts,
            Some(renewed.expires_at_unix_ms)
        )
    );
    let after_renewal = fixture.rows().await?;
    assert!(matches!(
        fixture
            .store
            .renew_claim(&fixture.claim, Duration::from_secs(60))
            .await,
        Err(DurableOperationError::StaleLease)
    ));
    assert_eq!(fixture.rows().await?, after_renewal);
    let next = fixture
        .store
        .renew_claim(&renewed, Duration::from_secs(60))
        .await?;
    assert_eq!(next.intent, fixture.claim.intent);
    assert_eq!(next.fence, renewed.fence + 1);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn renewal_rejects_future_nonterminal_ledger_frontier_without_mutation() -> TestResult<()> {
    let fixture = RenewalFixture::new().await?;
    let mut donor = intent(b"different scope clock frontier");
    donor.scope_id = stable_id("scope:clock-frontier-witness");
    donor.operation_id = stable_id("operation:clock-frontier-witness");
    donor.destination = stable_id("destination:clock-frontier-witness");
    let donor_record = fixture.store.prepare_intent(&donor).await?.record;
    let before_future_frontier = fixture.rows().await?;
    let future = now_millis()? + 3_600_000;
    let updated = sqlx::query(
        "UPDATE operation_ledger SET updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(future)
    .bind(donor.scope_id.as_str())
    .bind(donor.operation_id.as_str())
    .execute(&fixture.store.pool)
    .await?;
    assert_eq!(updated.rows_affected(), 1);
    let witness = fixture
        .store
        .operation(&donor.scope_id, &donor.operation_id)
        .await?
        .ok_or("future ledger witness exists")?;
    assert_eq!(witness.updated_at_unix_ms, to_u64(future)?);
    assert!(witness.terminal_at_unix_ms.is_none());
    fixture.assert_original_lease_is_live()?;
    let before = fixture.rows().await?;
    let result = fixture
        .store
        .renew_claim(&fixture.claim, Duration::from_secs(60))
        .await;
    fixture.assert_original_lease_is_live()?;
    assert!(
        now_millis()? < future,
        "fixture frontier must still be in the future"
    );
    assert!(
        matches!(&result, Err(DurableOperationError::ClockRollback)),
        "future global frontier must be refused: {result:?}"
    );
    assert_eq!(fixture.rows().await?, before);
    let restored = sqlx::query(
        "UPDATE operation_ledger SET updated_at_ms = ? WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(to_i64(donor_record.updated_at_unix_ms)?)
    .bind(donor.scope_id.as_str())
    .bind(donor.operation_id.as_str())
    .execute(&fixture.store.pool)
    .await?;
    assert_eq!(restored.rows_affected(), 1);
    assert_eq!(fixture.rows().await?, before_future_frontier);
    fixture.assert_original_lease_is_live()?;
    let renewed = fixture
        .store
        .renew_claim(&fixture.claim, Duration::from_secs(60))
        .await?;
    assert_eq!(renewed.intent, fixture.claim.intent);
    assert_eq!(renewed.fence, fixture.claim.fence + 1);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn renewal_rejects_payload_drift_without_consuming_the_live_lease() -> TestResult<()> {
    let fixture = RenewalFixture::new().await?;
    let mut changed = fixture.claim.clone();
    changed.intent.payload_digest = Digest32::of_bytes(b"different nonzero payload");
    fixture.assert_intent_drift_is_rejected(&changed).await
}

#[tokio::test]
async fn renewal_rejects_existing_predecessor_drift_without_consuming_the_live_lease()
-> TestResult<()> {
    let fixture = RenewalFixture::new().await?;
    let mut changed = fixture.claim.clone();
    changed.intent.expected_predecessor = Some(fixture.predecessor.operation_id.clone());
    fixture.assert_intent_drift_is_rejected(&changed).await
}

#[tokio::test]
async fn renewal_rejects_inner_generation_drift_without_consuming_the_live_lease() -> TestResult<()>
{
    let fixture = RenewalFixture::new().await?;
    let mut changed = fixture.claim.clone();
    changed.intent.owner_generation = generation(/*value*/ 2);
    assert_eq!(
        changed.intent.semantic_digest(),
        fixture.claim.intent.semantic_digest()
    );
    fixture.assert_intent_drift_is_rejected(&changed).await
}
