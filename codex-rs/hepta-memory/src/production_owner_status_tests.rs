use super::*;
use crate::cognitive_test_support::agent_id;
use codex_hepta_paths::HeptaFleetRoot;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

struct Fixture {
    _temp: tempfile::TempDir,
    store: CognitiveStore,
    writer: Arc<ProductionDurableWriter>,
    verifier_calls: Arc<AtomicUsize>,
}

async fn fixture() -> Fixture {
    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let owner = agent_id(/*suffix*/ 246);
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("existing owner");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner,
        Sha256Digest::for_bytes(b"owner-status-grant"),
        /*authority_epoch*/ 7,
        /*owner_epoch*/ 11,
        u64::try_from(i64::MAX).expect("positive expiry"),
        ProductionAuthorityToken::from_verified_bytes(b"never-export-this-fence".to_vec())
            .expect("fixture token"),
    )
    .expect("fixture authority");
    let verifier_calls = Arc::new(AtomicUsize::new(/*v*/ 0));
    let calls = Arc::clone(&verifier_calls);
    let verifier = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| {
            calls.fetch_add(/*val*/ 1, Ordering::SeqCst);
            if &lease.agent_id == expected {
                Ok(())
            } else {
                Err("fixture owner mismatch".into())
            }
        },
    );
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority,
            verifier,
            "owner-status",
            /*generation*/ 1,
        )
        .await
        .expect("bound writer"),
    );
    Fixture {
        _temp: temp,
        store,
        writer,
        verifier_calls,
    }
}

#[tokio::test]
async fn observation_is_pure_token_free_and_does_not_reverify_authority() {
    let f = fixture().await;
    let before = f.store.recovery_anchor().await.expect("before cut");
    let calls = f.verifier_calls.load(Ordering::SeqCst);
    let observation = f.writer.inspect_lease_head().await.expect("observation");
    assert_eq!(observation.generation, Some(1));
    assert_eq!(observation.disposition, ProductionLeaseDisposition::Active);
    assert_eq!(f.verifier_calls.load(Ordering::SeqCst), calls);
    assert_eq!(f.store.recovery_anchor().await.expect("after cut"), before);
    let debug = format!("{observation:?}");
    assert!(!debug.contains(f.writer.lease.fencing_token()));
    assert!(!debug.contains("never-export-this-fence"));
    assert!(!debug.contains("fencing_token"));
    let weak = Arc::downgrade(&f.writer);
    drop(f.writer);
    assert!(weak.upgrade().is_none());
    assert_eq!(observation.generation, Some(1));
}

#[tokio::test]
async fn terminal_lease_transitions_are_observed_without_writability_claims() {
    let released = fixture().await;
    released.writer.release().await.expect("release");
    assert_eq!(
        released
            .writer
            .inspect_lease_head()
            .await
            .expect("released"),
        ProductionLeaseHeadObservation {
            generation: Some(1),
            disposition: ProductionLeaseDisposition::Released,
        }
    );
    let successor_authority = ProductionAuthorityLease::from_verified_parts(
        released.writer.owner_agent_id().clone(),
        Sha256Digest::for_bytes(b"successor-owner-status-grant"),
        /*authority_epoch*/ 8,
        /*owner_epoch*/ 12,
        u64::try_from(i64::MAX).expect("positive expiry"),
        ProductionAuthorityToken::from_verified_bytes(b"successor-private-fence".to_vec())
            .expect("successor token"),
    )
    .expect("successor authority");
    let verifier = released
        .writer
        .live_verifier
        .as_ref()
        .expect("live verifier")
        .clone();
    drop(released.writer);
    let successor = ProductionDurableWriter::open_with_live_verifier(
        released.store.clone(),
        successor_authority,
        verifier,
        "owner-status",
        /*generation*/ 2,
    )
    .await
    .expect("explicit successor");
    assert_eq!(
        successor
            .inspect_lease_head()
            .await
            .expect("successor observation")
            .generation,
        Some(2)
    );
    let rolled_back = fixture().await;
    rolled_back.writer.rollback_lease().await.expect("rollback");
    assert_eq!(
        rolled_back
            .writer
            .inspect_lease_head()
            .await
            .expect("rolled back"),
        ProductionLeaseHeadObservation {
            generation: Some(1),
            disposition: ProductionLeaseDisposition::RolledBack,
        }
    );
}

#[tokio::test]
async fn corrupt_lease_chain_remains_an_error() {
    let f = fixture().await;
    let mut transaction = f.store.pool.begin().await.expect("tamper fixture");
    sqlx::query("DROP TRIGGER cognitive_local_leases_no_update")
        .execute(&mut *transaction)
        .await
        .expect("fixture trigger removal");
    sqlx::query("UPDATE cognitive_local_leases SET generation = generation + 1 WHERE lease_id = ?")
        .bind(f.writer.lease_id())
        .execute(&mut *transaction)
        .await
        .expect("fixture hash mismatch");
    transaction
        .commit()
        .await
        .expect("commit malformed fixture");
    assert!(matches!(
        f.writer.inspect_lease_head().await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::Corrupt(_)
        ))
    ));
}

#[tokio::test]
async fn cancelled_waiting_read_leaves_the_durable_cut_unchanged() {
    let f = fixture().await;
    let before = f.store.recovery_anchor().await.expect("before cut");
    let mut held = Vec::new();
    for _ in 0..f.store.pool.options().get_max_connections() {
        held.push(f.store.pool.acquire().await.expect("reserve connection"));
    }
    let (entered, entered_rx) = tokio::sync::oneshot::channel();
    let writer = Arc::clone(&f.writer);
    let task = tokio::spawn(async move {
        entered.send(()).expect("signal read start");
        writer.inspect_lease_head().await
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 5), entered_rx)
        .await
        .expect("bounded read start")
        .expect("read task alive");
    assert!(!task.is_finished());
    task.abort();
    assert!(task.await.expect_err("cancelled read").is_cancelled());
    drop(held);
    assert_eq!(f.store.recovery_anchor().await.expect("after cut"), before);
    assert_eq!(
        f.writer
            .inspect_lease_head()
            .await
            .expect("subsequent read")
            .disposition,
        ProductionLeaseDisposition::Active
    );
}
