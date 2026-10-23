//! Real SQLite durability and reopen tests with an explicit observer fixture.
//! No fixture authority below is a production issuer or native-device proof.

use super::*;
use crate::NotesTargetIdentity;
use crate::notes_operation_intent;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const LEASE: &str = "notes-owner-recovery-fixture";

struct Verifier;
impl ProductionAuthorityVerifier for Verifier {
    fn verify(&self, _lease: &ProductionAuthorityLease, _owner: &AgentId) -> Result<(), String> {
        Ok(())
    }
}

struct Observer {
    destination: String,
    receipt: String,
    observations: AtomicUsize,
    retirements: AtomicUsize,
    lose_first_ack: AtomicBool,
}
impl ProductionOutboxTarget for Observer {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        panic!("recovery must never dispatch an effect")
    }
}
impl FinalUseProductionOutboxTarget for Observer {
    fn destination_id(&self) -> &str {
        &self.destination
    }
    fn observe_terminal<'a>(
        &'a self,
        _request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            ProductionTerminalObservation::Applied {
                receipt: self.receipt.clone(),
            }
        })
    }
    fn retire_notes_receipt(&self, permit: &NotesRetirementPermit) -> Result<(), String> {
        assert_eq!(permit.receipt(), self.receipt);
        assert_eq!(permit.request().operation_destination_id, self.destination);
        self.retirements.fetch_add(1, Ordering::SeqCst);
        if self.lose_first_ack.swap(false, Ordering::SeqCst) {
            return Err("explicit fixture lost retirement acknowledgement".to_string());
        }
        Ok(())
    }
}

fn source(owner: &AgentId, epoch: u64) -> TestResult<ProductionAuthorityLease> {
    Ok(ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(format!("notes-fixture-{epoch}").as_bytes()),
        /*authority_epoch*/ 1,
        epoch,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(
            format!("notes-fixture-token-{epoch}").into_bytes(),
        )?,
    )?)
}

fn fixture() -> TestResult<(String, NotesTargetIdentity, Observer)> {
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json"))?;
    let payload = fixture["request_utf8"]
        .as_str()
        .ok_or("payload")?
        .to_string();
    let request: serde_json::Value = serde_json::from_str(&payload)?;
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone())?;
    let observer = Observer {
        destination: identity.destination_id(),
        receipt: fixture["application_response_utf8"]
            .as_str()
            .ok_or("receipt")?
            .to_string(),
        observations: AtomicUsize::new(0),
        retirements: AtomicUsize::new(0),
        lose_first_ack: AtomicBool::new(true),
    };
    Ok((payload, identity, observer))
}

async fn prepare(
    writer: &ProductionDurableWriter,
    payload: String,
    identity: &NotesTargetIdentity,
) -> TestResult<String> {
    let intent = notes_operation_intent(
        identity,
        &payload,
        StableId::new(writer.owner_agent_id().as_str())?,
        Generation::new(1)?,
    )?;
    let queued = writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    writer
        .mark_indeterminate(
            &queued.occurrence_key,
            "fixture app applied; effect reply lost",
        )
        .await?;
    Ok(queued.occurrence_key)
}

#[tokio::test]
async fn failed_terminal_persistence_never_acks_and_reopened_writer_retries_exact_retirement()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, identity, target) = fixture()?;
    let operation = prepare(&writer, payload, &identity).await?;
    assert!(
        writer
            .retire_notes_receipt(&target, &operation)
            .await
            .is_err()
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    sqlx::query("CREATE TRIGGER notes_fixture_fail_terminal BEFORE INSERT ON cognitive_local_events WHEN NEW.event_kind = 'reconcile_committed' BEGIN SELECT RAISE(ABORT, 'fixture durability failure'); END").execute(&store.pool).await?;
    assert!(
        writer
            .reconcile_target_batch(&target, /*limit*/ 1)
            .await
            .is_err()
    );
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 0);
    sqlx::query("DROP TRIGGER notes_fixture_fail_terminal")
        .execute(&store.pool)
        .await?;
    assert_eq!(
        writer.reconcile_target_batch(&target, /*limit*/ 1).await?,
        1
    );
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    let persisted: String = sqlx::query_scalar("SELECT payload_json FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? AND event_kind = 'reconcile_committed'")
        .bind(LEASE).bind(&operation).fetch_one(&store.pool).await?;
    assert_eq!(persisted, target.receipt);
    drop(writer);
    store.close().await;
    let reopened_store = CognitiveStore::open(&layout).await?;
    let reopened = ProductionDurableWriter::open_with_live_verifier(
        reopened_store,
        authority,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    assert_eq!(
        reopened
            .reconcile_target_batch(&target, /*limit*/ 1)
            .await?,
        0
    );
    assert_eq!(target.retirements.load(Ordering::SeqCst), 2);
    assert_eq!(
        target.observations.load(Ordering::SeqCst),
        2,
        "reopen retries metadata retirement only"
    );
    Ok(())
}

#[tokio::test]
async fn inherited_notes_settlement_preserves_complete_receipt_under_successor_fence() -> TestResult
{
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d17")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, identity, target) = fixture()?;
    let operation = prepare(&writer, payload, &identity).await?;
    // Normal release must not hide the unresolved application effect. Use the
    // existing test clock seam to exercise the separate expiry transition at
    // the persisted deadline, without weakening the production lease fence.
    assert!(matches!(
        writer.release().await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::IllegalTransition(reason)
        )) if reason.contains(&operation)
    ));
    let expiry = writer.authority().lease_expires_at_unix_seconds;
    assert!(matches!(
        writer.lease.expire_lease_at_unix_seconds(expiry - 1).await,
        Err(LocalLeaseOutboxError::StaleFence(_))
    ));
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Indeterminate
    );
    let expired = writer.lease.expire_lease_at_unix_seconds(expiry).await?;
    assert_eq!(expired.state, crate::LocalLeaseState::RolledBack);
    assert_eq!(expired.generation, 1);
    assert_eq!(expired.owner_epoch, Some(1));
    drop(writer);
    let successor = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 2)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 2,
    )
    .await?;
    assert_eq!(successor.generation(), 2);
    assert_eq!(
        successor.status(&operation).await?,
        LocalOutcomeState::Indeterminate
    );
    let request = successor
        .reconciliation_request(&operation, &identity.destination_id())
        .await?;
    successor
        .settle_inherited_dispatch_outcome(
            request,
            &operation,
            "fixture-original-claim".to_string(),
            ProductionTargetOutcome::Committed {
                receipt: target.receipt.clone(),
            },
        )
        .await?;
    let (persisted, generation): (String, i64) = sqlx::query_as("SELECT payload_json, generation FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ? AND event_kind = 'reconcile_committed'")
        .bind(LEASE).bind(operation).fetch_one(&store.pool).await?;
    assert_eq!(persisted, target.receipt);
    assert_eq!(generation, 2);
    Ok(())
}
