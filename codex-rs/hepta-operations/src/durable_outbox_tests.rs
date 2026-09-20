use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::DurableOutboxState;
use crate::DurableOperationBinding;
use crate::DurableOperationLedger;
use crate::OperationError;
use crate::OperationKey;
use crate::OperationState;
use crate::OutboxIntent;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn binding() -> DurableOperationBinding {
    DurableOperationBinding {
        key: OperationKey {
            id: stable_id("operation:ui:outbox:1"),
            payload_digest: digest(b"ui-request-semantics"),
        },
        destination_id: stable_id("runtime.agentd.ui-control"),
        context_digest: digest(b"ui-request-provenance"),
    }
}

fn intent() -> OutboxIntent {
    OutboxIntent {
        intent_id: stable_id("outbox:ui:1"),
        operation_id: stable_id("operation:ui:outbox:1"),
        destination: stable_id("runtime.agentd.ui-control"),
        payload_digest: digest(b"owner-dispatch-intent"),
    }
}

#[tokio::test]
async fn operation_and_outbox_are_one_reopenable_local_transaction() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let owner_generation = generation(3);
    let ledger = DurableOperationLedger::open(&path).await.expect("open");

    let (operation, outbox) = ledger
        .begin_bound_with_outbox(binding(), owner_generation, intent())
        .await
        .expect("atomic operation + outbox");
    assert!(matches!(operation.operation.state, OperationState::Pending));
    assert!(matches!(outbox.state, DurableOutboxState::Pending));

    let repeated = ledger
        .begin_bound_with_outbox(binding(), owner_generation, intent())
        .await
        .expect("same semantics are idempotent");
    assert_eq!(repeated.0.operation.revision.get(), 1);
    assert!(matches!(repeated.1.state, DurableOutboxState::Pending));

    let mut changed = intent();
    changed.payload_digest = digest(b"changed-dispatch");
    assert!(matches!(
        ledger
            .begin_bound_with_outbox(binding(), owner_generation, changed)
            .await
            .expect_err("changed outbox semantics conflict"),
        OperationError::Conflict(_)
    ));

    ledger.close().await;

    let reopened = DurableOperationLedger::open(&path).await.expect("reopen");
    let operation = reopened
        .get(&stable_id("operation:ui:outbox:1"))
        .await
        .expect("query operation")
        .expect("operation");
    let outbox = reopened
        .get_outbox(&stable_id("outbox:ui:1"))
        .await
        .expect("query outbox")
        .expect("outbox");
    assert!(matches!(operation.operation.state, OperationState::Pending));
    assert!(matches!(outbox.state, DurableOutboxState::Pending));
}

#[tokio::test]
async fn expired_claim_requires_higher_generation_and_ack_is_fenced() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let ledger = DurableOperationLedger::open(&path).await.expect("open");
    ledger
        .begin_bound_with_outbox(binding(), generation(4), intent())
        .await
        .expect("seed");

    let first = ledger
        .claim_outbox(&stable_id("outbox:ui:1"), generation(10), 1_000, 500)
        .await
        .expect("first claim");
    assert!(matches!(
        first.state,
        DurableOutboxState::Claimed {
            owner_generation,
            lease_expires_at_ms: 1_500,
            attempts: 1
        } if owner_generation == generation(10)
    ));

    assert_eq!(
        ledger
            .claim_outbox(&stable_id("outbox:ui:1"), generation(11), 1_499, 500)
            .await
            .expect_err("live lease cannot be stolen"),
        OperationError::StaleGeneration
    );

    let takeover = ledger
        .claim_outbox(&stable_id("outbox:ui:1"), generation(11), 1_500, 500)
        .await
        .expect("expired claim takeover");
    assert!(matches!(
        takeover.state,
        DurableOutboxState::Claimed {
            owner_generation,
            lease_expires_at_ms: 2_000,
            attempts: 2
        } if owner_generation == generation(11)
    ));

    assert_eq!(
        ledger
            .acknowledge_outbox(
                &stable_id("outbox:ui:1"),
                generation(10),
                digest(b"stale-ack"),
            )
            .await
            .expect_err("stale claimant cannot acknowledge"),
        OperationError::StaleGeneration
    );

    let ack_digest = digest(b"dispatch-accepted-not-terminal");
    let acknowledged = ledger
        .acknowledge_outbox(
            &stable_id("outbox:ui:1"),
            generation(11),
            ack_digest,
        )
        .await
        .expect("current claim acknowledgement");
    assert!(matches!(
        acknowledged.state,
        DurableOutboxState::Acknowledged {
            owner_generation,
            acknowledgement_digest,
            attempts: 2
        } if owner_generation == generation(11) && acknowledgement_digest == ack_digest
    ));

    let operation = ledger
        .get(&stable_id("operation:ui:outbox:1"))
        .await
        .expect("query operation")
        .expect("operation");
    assert!(
        !operation.operation.state.is_terminal(),
        "outbox acknowledgement must never imply external terminal success"
    );

    ledger.close().await;

    let reopened = DurableOperationLedger::open(&path).await.expect("reopen");
    let persisted = reopened
        .get_outbox(&stable_id("outbox:ui:1"))
        .await
        .expect("query ack")
        .expect("ack record");
    assert!(matches!(
        persisted.state,
        DurableOutboxState::Acknowledged {
            owner_generation,
            acknowledgement_digest,
            attempts: 2
        } if owner_generation == generation(11) && acknowledgement_digest == ack_digest
    ));
}

#[tokio::test]
async fn equal_claim_is_idempotent_but_expired_same_generation_cannot_self_takeover() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let ledger = DurableOperationLedger::open(&path).await.expect("open");
    ledger
        .begin_bound_with_outbox(binding(), generation(6), intent())
        .await
        .expect("seed");

    let first = ledger
        .claim_outbox(&stable_id("outbox:ui:1"), generation(20), 10_000, 1_000)
        .await
        .expect("claim");
    let same = ledger
        .claim_outbox(&stable_id("outbox:ui:1"), generation(20), 10_500, 1_000)
        .await
        .expect("same owner live claim");
    assert_eq!(same, first);

    assert_eq!(
        ledger
            .claim_outbox(&stable_id("outbox:ui:1"), generation(20), 11_000, 1_000)
            .await
            .expect_err("same generation cannot resurrect expired ownership"),
        OperationError::StaleGeneration
    );
}
