use std::process::Command;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use super::*;
use crate::ReconciliationOutcome;

const CRASH_HOME_ENV: &str = "HEPTA_OPERATIONS_CRASH_HOME";

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn config(path: &std::path::Path) -> SqliteConfig {
    let home = AbsolutePathBuf::try_from(path.to_path_buf()).expect("absolute test path");
    SqliteConfig::new_for_testing(home)
}

fn request(operation_id: &str) -> PrepareOperationIntent {
    PrepareOperationIntent {
        scope: stable_id("scope:fault"),
        operation_id: stable_id(operation_id),
        predecessor_digest: Some(Digest32::of_bytes(b"fault-predecessor")),
        payload_digest: Digest32::of_bytes(b"fault-payload"),
        destination: stable_id("destination:fault"),
        owner_generation: generation(3),
        authority_epoch: generation(9),
    }
}

#[tokio::test]
async fn two_independent_handles_serialize_one_live_claim() {
    let temp = tempfile::tempdir().expect("tempdir");
    let sqlite = config(temp.path());
    let first = DurableOperationStore::open(&sqlite).await.expect("first handle");
    let second = DurableOperationStore::open(&sqlite).await.expect("second handle");
    let request = request("operation:multi-writer");
    first.prepare_intent(&request).await.expect("prepare");
    let left_worker = stable_id("worker:left");
    let right_worker = stable_id("worker:right");
    let (left, right) = tokio::join!(
        first.claim_outbox(
            &request.scope,
            &request.operation_id,
            &left_worker,
            generation(3),
            60_000,
        ),
        second.claim_outbox(
            &request.scope,
            &request.operation_id,
            &right_worker,
            generation(3),
            60_000,
        )
    );
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let loser = if left.is_ok() { right } else { left };
    assert!(matches!(loser, Err(DurableOperationError::StaleLease)));
}

#[tokio::test]
async fn bounded_attempt_budget_quarantines_instead_of_retrying_forever() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .expect("store");
    let request = request("operation:attempt-budget");
    store.prepare_intent(&request).await.expect("prepare");
    let worker = stable_id("worker:attempt-budget");
    for attempt in 0..MAX_OPERATION_ATTEMPTS {
        let lease = store
            .claim_outbox(
                &request.scope,
                &request.operation_id,
                &worker,
                generation(3),
                60_000,
            )
            .await
            .unwrap_or_else(|error| panic!("claim {attempt} failed: {error}"));
        store
            .retry_outbox(&lease, 0, Digest32::of_bytes(format!("retry-{attempt}").as_bytes()))
            .await
            .unwrap_or_else(|error| panic!("retry {attempt} failed: {error}"));
    }
    assert!(matches!(
        store
            .claim_outbox(
                &request.scope,
                &request.operation_id,
                &worker,
                generation(3),
                60_000,
            )
            .await,
        Err(DurableOperationError::UnavailableState)
    ));
    let operation = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    let outbox = store
        .outbox_status(&request.scope, &request.operation_id)
        .await
        .expect("outbox")
        .expect("outbox row");
    assert_eq!(operation.state, DurableOperationState::Quarantined);
    assert_eq!(outbox.state, DurableOutboxState::Quarantined);
    assert_eq!(outbox.attempts, MAX_OPERATION_ATTEMPTS);
}

#[tokio::test]
async fn injected_disk_full_during_atomic_publish_exposes_neither_half() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .expect("store");
    sqlx::query(
        "CREATE TRIGGER fixture_disk_full BEFORE INSERT ON cross_owner_outbox
         BEGIN SELECT RAISE(ABORT, 'database or disk is full'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install disk-full failpoint");
    let request = request("operation:disk-full");
    assert!(store.prepare_intent(&request).await.is_err());
    assert!(
        store
            .get_operation(&request.scope, &request.operation_id)
            .await
            .expect("lookup")
            .is_none()
    );
    assert!(
        store
            .outbox_status(&request.scope, &request.operation_id)
            .await
            .expect("outbox lookup")
            .is_none()
    );
}

#[tokio::test]
#[ignore = "subprocess crash fixture"]
async fn crash_after_pre_dispatch_claim_child() {
    let home = std::path::PathBuf::from(std::env::var_os(CRASH_HOME_ENV).expect("crash home"));
    let store = DurableOperationStore::open(&config(&home)).await.expect("store");
    let request = request("operation:crash-claim");
    store.prepare_intent(&request).await.expect("prepare");
    let lease = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:crash-child"),
            generation(3),
            1,
        )
        .await
        .expect("claim");
    std::fs::write(home.join("claim-fence"), lease.fence.to_string()).expect("write fence");
    std::process::exit(73);
}

#[tokio::test]
async fn actual_process_crash_before_dispatch_recovers_same_identity_with_new_fence() {
    let temp = tempfile::tempdir().expect("tempdir");
    let status = Command::new(std::env::current_exe().expect("current exe"))
        .args([
            "--exact",
            "durable::fault_tests::crash_after_pre_dispatch_claim_child",
            "--ignored",
            "--nocapture",
        ])
        .env(CRASH_HOME_ENV, temp.path())
        .status()
        .expect("run child");
    assert_eq!(status.code(), Some(73));
    tokio::time::sleep(Duration::from_millis(5)).await;
    let old_fence: u64 = std::fs::read_to_string(temp.path().join("claim-fence"))
        .expect("read fence")
        .parse()
        .expect("parse fence");
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .expect("reopen");
    let request = request("operation:crash-claim");
    let lease = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:crash-recovery"),
            generation(4),
            60_000,
        )
        .await
        .expect("recovery claim");
    assert!(lease.fence > old_fence);
    assert_eq!(lease.owner_generation, generation(4));
    assert_eq!(lease.attempts, 2);
}

#[tokio::test]
#[ignore = "subprocess crash fixture"]
async fn crash_after_durable_dispatch_child() {
    let home = std::path::PathBuf::from(std::env::var_os(CRASH_HOME_ENV).expect("crash home"));
    let store = DurableOperationStore::open(&config(&home)).await.expect("store");
    let request = request("operation:crash-dispatched");
    let prepared = store.prepare_intent(&request).await.expect("prepare");
    let lease = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:dispatch-child"),
            generation(3),
            60_000,
        )
        .await
        .expect("claim");
    store
        .mark_dispatched(&lease, Digest32::of_bytes(b"dispatch-crossed"))
        .await
        .expect("persist dispatched");
    std::fs::write(
        home.join("semantic-digest"),
        prepared.semantic_digest.to_string(),
    )
    .expect("write semantic digest");
    std::process::exit(74);
}

#[tokio::test]
async fn actual_process_crash_after_dispatch_never_blindly_reclaims_and_can_reconcile() {
    let temp = tempfile::tempdir().expect("tempdir");
    let status = Command::new(std::env::current_exe().expect("current exe"))
        .args([
            "--exact",
            "durable::fault_tests::crash_after_durable_dispatch_child",
            "--ignored",
            "--nocapture",
        ])
        .env(CRASH_HOME_ENV, temp.path())
        .status()
        .expect("run child");
    assert_eq!(status.code(), Some(74));
    let store = DurableOperationStore::open(&config(temp.path()))
        .await
        .expect("reopen");
    let request = request("operation:crash-dispatched");
    assert!(
        store.pending_outbox(16).await.expect("pending").is_empty(),
        "a may-have-crossed effect must not re-enter the dispatch queue"
    );
    assert!(matches!(
        store
            .claim_outbox(
                &request.scope,
                &request.operation_id,
                &stable_id("worker:unsafe-retry"),
                generation(4),
                60_000,
            )
            .await,
        Err(DurableOperationError::ReconciliationRequired)
    ));
    let operation = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(operation.state, DurableOperationState::Dispatched);
    store
        .record_destination_outcome(
            &request.destination,
            &request.operation_id,
            operation.semantic_digest,
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"observed-applied-after-crash"),
        )
        .await
        .expect("destination receipt");
    let settled = store
        .reconcile_from_destination(
            &store,
            &request.scope,
            &request.operation_id,
            generation(4),
        )
        .await
        .expect("new-generation reconcile takeover");
    assert_eq!(settled.owner_generation, generation(4));
    assert_eq!(settled.state, DurableOperationState::Applied);
}
