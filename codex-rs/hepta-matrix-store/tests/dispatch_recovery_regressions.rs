//! Real-store regression sources. These tests do not fabricate a homeserver
//! receipt or claim that fixture authorization metadata is a verified grant.
use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixAttemptFailureClass;
use codex_hepta_matrix_store::MatrixDispatchAttemptEventKind;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixFencedOutboxClaim;
use codex_hepta_matrix_store::MatrixOutboxAuthorityWitness;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

async fn fixture() -> TestResult<(TempDir, HeptaAgentLayout, MatrixDurableStore, OutboxRecord)> {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?.layout().agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!allowed:example.test")?;
    store.bind_room(&RoomBindingDraft {
        room_id: room.clone(),
        agent_user_id: MatrixUserId::parse("@agent:example.test")?,
        expected_revision: None,
        generation: 1,
        changed_at_ms: 1,
    }).await?;
    let logical = outbox_id(&agent, &room, "thread", "turn", "item", "final");
    let txn = transaction_id(&logical, /*revision*/ 1)?;
    let OutboxDisposition::Enqueued(record) = store.enqueue_outbox(&OutboxDraft {
        logical_outbox_id: logical,
        revision: 1,
        txn_id: txn,
        room_id: room,
        kind: OutboxKind::Final,
        payload: b"complete".to_vec(),
        binding_revision: 1,
        generation: 1,
        created_at_ms: 2,
    }).await? else {
        return Err("fresh message was not enqueued".into());
    };
    Ok((temp, layout, store, record))
}

async fn claimed(store: &MatrixDurableStore, now: u64) -> TestResult<OutboxRecord> {
    let mut rows = store.claim_outbox(now, /*lease_ms*/ 100, /*limit*/ 1).await?;
    rows.pop().ok_or_else(|| "outbox claim missing".into())
}

async fn fenced(store: &MatrixDurableStore) -> TestResult<MatrixFencedOutboxClaim> {
    let mut claims = store.claim_outbox_fenced(/*now_ms*/ 10, /*lease_ms*/ 100, /*limit*/ 1).await?;
    claims.pop().ok_or_else(|| "fenced claim missing".into())
}

async fn dispatch_intent(store: &MatrixDurableStore, claim: &MatrixFencedOutboxClaim) -> TestResult {
    store.prepare_outbox_dispatch(claim.record(), /*now_ms*/ 11).await?;
    // Store-only phase fixture, deliberately not a success/authority oracle.
    store.record_outbox_authorized(claim, &MatrixOutboxAuthorityWitness {
        authority_epoch: 1,
        revocation_revision: 1,
        grant_id: "store-fixture-only".to_string(),
        verified_use_witness_sha256: "a".repeat(64),
        revocation_head_sha256: "b".repeat(64),
    }, /*recorded_at_ms*/ 12).await?;
    store.record_outbox_dispatching(claim, /*recorded_at_ms*/ 13).await?;
    Ok(())
}

#[tokio::test]
async fn ack_loss_survives_retry_rejection_and_reopen() -> TestResult {
    let (_temp, layout, store, original) = fixture().await?;
    let first = claimed(&store, /*now*/ 10).await?;
    store.prepare_outbox_dispatch(&first, /*now_ms*/ 11).await?;
    store.record_outbox_transport_indeterminate(&first.stable_txn_id, first.attempts, /*now_ms*/ 12).await?;
    store.mark_outbox_retry(&first.stable_txn_id, first.attempts, /*now_ms*/ 13, /*next_attempt_at_ms*/ 20).await?;
    store.close().await;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let second = claimed(&store, /*now*/ 21).await?;
    assert_eq!(second.stable_txn_id, original.stable_txn_id);
    assert_eq!(second.attempts, first.attempts + 1);
    assert_eq!(store.prepare_outbox_dispatch(&second, /*now_ms*/ 22).await?.state, MatrixDispatchState::Indeterminate);
    assert_eq!(store.record_outbox_transport_rejected(&second.stable_txn_id, second.attempts, /*now_ms*/ 23).await?.state,
               MatrixDispatchState::Indeterminate);
    store.close().await;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(store.dispatch_for_txn(&original.stable_txn_id).await?.ok_or("missing dispatch")?.state,
               MatrixDispatchState::Indeterminate);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn crashed_dispatch_without_ack_is_not_erased_by_a_new_attempt() -> TestResult {
    let (_temp, layout, store, original) = fixture().await?;
    let first = claimed(&store, /*now*/ 10).await?;
    store.prepare_outbox_dispatch(&first, /*now_ms*/ 11).await?;
    store.close().await;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let second = claimed(&store, /*now*/ 111).await?;
    assert_eq!(second.stable_txn_id, original.stable_txn_id);
    assert_eq!(store.prepare_outbox_dispatch(&second, /*now_ms*/ 112).await?.state, MatrixDispatchState::Indeterminate);
    assert_eq!(store.record_outbox_transport_rejected(&second.stable_txn_id, second.attempts, /*now_ms*/ 113).await?.state,
               MatrixDispatchState::Indeterminate);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn first_definitive_rejection_remains_a_negative_outcome() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let first = claimed(&store, /*now*/ 10).await?;
    store.prepare_outbox_dispatch(&first, /*now_ms*/ 11).await?;
    assert_eq!(store.record_outbox_transport_rejected(&first.stable_txn_id, first.attempts, /*now_ms*/ 12).await?.state,
               MatrixDispatchState::Failed);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn accepted_event_is_not_replaced_by_a_later_rejection() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let first = claimed(&store, /*now*/ 10).await?;
    store.prepare_outbox_dispatch(&first, /*now_ms*/ 11).await?;
    let event = MatrixEventId::parse("$accepted")?;
    store.record_outbox_transport_accepted(&first.stable_txn_id, first.attempts, &event, /*now_ms*/ 12).await?;
    store.mark_outbox_retry(&first.stable_txn_id, first.attempts, /*now_ms*/ 13, /*next_attempt_at_ms*/ 20).await?;
    let second = claimed(&store, /*now*/ 21).await?;
    store.prepare_outbox_dispatch(&second, /*now_ms*/ 22).await?;
    let result = store.record_outbox_transport_rejected(&second.stable_txn_id, second.attempts, /*now_ms*/ 23).await?;
    assert_eq!(result.state, MatrixDispatchState::Accepted);
    assert_eq!(result.accepted_event_id, Some(event));
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn stale_record_cannot_prepare_a_reclaimed_attempt() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let first = claimed(&store, /*now*/ 10).await?;
    let second = claimed(&store, /*now*/ 111).await?;
    assert_eq!(store.prepare_outbox_dispatch(&first, /*now_ms*/ 112).await,
               Err(MatrixDurableError::Conflict));
    store.prepare_outbox_dispatch(&second, /*now_ms*/ 112).await?;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn post_entry_timeout_can_be_recorded_after_lease_expiry() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let claim = fenced(&store).await?;
    dispatch_intent(&store, &claim).await?;
    store.record_outbox_transport_indeterminate(&claim.record().stable_txn_id, claim.record().attempts, /*now_ms*/ 111).await?;
    store.finish_outbox_indeterminate(&claim, MatrixAttemptFailureClass::ReadTimeout,
                                     /*retry_after_ms*/ None, /*recorded_at_ms*/ 112, /*next_attempt_at_ms*/ 120).await?;
    let events = store.dispatch_attempt_events(&claim.record().stable_txn_id).await?;
    assert!(events.iter().any(|event| event.event_kind == MatrixDispatchAttemptEventKind::Indeterminate));
    let mut next = store.claim_outbox_fenced(/*now_ms*/ 121, /*lease_ms*/ 100, /*limit*/ 1).await?;
    let next = next.pop().ok_or("missing recovered claim")?;
    assert_eq!(next.record().stable_txn_id, claim.record().stable_txn_id);
    assert!(next.lease_epoch() > claim.lease_epoch());
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn post_expiry_old_token_cannot_finalize_the_new_owner() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let old = fenced(&store).await?;
    dispatch_intent(&store, &old).await?;
    let mut next = store.claim_outbox_fenced(/*now_ms*/ 111, /*lease_ms*/ 100, /*limit*/ 1).await?;
    let next = next.pop().ok_or("missing new claim")?;
    assert_eq!(store.finish_outbox_indeterminate(&old, MatrixAttemptFailureClass::ResponseLost,
               /*retry_after_ms*/ None, /*recorded_at_ms*/ 112, /*next_attempt_at_ms*/ 120).await,
               Err(MatrixDurableError::Conflict));
    store.record_outbox_prepared(&next, /*recorded_at_ms*/ 113).await?;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn an_expired_claim_never_authorizes_new_dispatch() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let claim = fenced(&store).await?;
    dispatch_intent(&store, &claim).await?;
    assert_eq!(store.record_outbox_dispatching(&claim, claim.lease_until_ms()).await,
               Err(MatrixDurableError::Conflict));
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn unknown_dispatch_cannot_be_closed_as_permanent_failure() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let claim = fenced(&store).await?;
    dispatch_intent(&store, &claim).await?;
    assert_eq!(store.finish_outbox_permanently_rejected(&claim, /*recorded_at_ms*/ 14).await,
               Err(MatrixDurableError::Conflict));
    assert_eq!(store.close_terminal_outbox_claim(&claim, MatrixDispatchAttemptEventKind::Confirmed,
               /*event_id*/ None, /*recorded_at_ms*/ 14).await,
               Err(MatrixDurableError::Conflict));
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn identical_prepare_is_idempotent_in_the_append_only_history() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let claim = fenced(&store).await?;
    store.record_outbox_prepared(&claim, /*recorded_at_ms*/ 11).await?;
    store.record_outbox_prepared(&claim, /*recorded_at_ms*/ 12).await?;
    let events = store.dispatch_attempt_events(&claim.record().stable_txn_id).await?;
    assert_eq!(events.iter().filter(|event| event.event_kind == MatrixDispatchAttemptEventKind::Prepared).count(), 1);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn expired_but_unreclaimed_pre_entry_claim_can_be_released() -> TestResult {
    let (_temp, _layout, store, _) = fixture().await?;
    let claim = fenced(&store).await?;
    store.release_outbox_claim_canceled(&claim, /*recorded_at_ms*/ 111).await?;
    let next = store.claim_outbox_fenced(/*now_ms*/ 112, /*lease_ms*/ 100, /*limit*/ 1).await?;
    assert_eq!(next.len(), 1);
    assert!(next[0].lease_epoch() > claim.lease_epoch());
    store.close().await;
    Ok(())
}
