use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchAuthority;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::observe_redaction;
use super::observe_send;
use super::prepare_send;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const ROOM: &str = "!room:example.org";
const USER: &str = "@agent:example.org";

fn digest(byte: char) -> String {
    byte.to_string().repeat(64)
}

fn agent() -> TestResult<AgentId> {
    Ok(AgentId::parse(AGENT)?)
}

fn room() -> TestResult<MatrixRoomId> {
    Ok(MatrixRoomId::parse(ROOM)?)
}

fn user() -> TestResult<MatrixUserId> {
    Ok(MatrixUserId::parse(USER)?)
}

fn event(value: &str) -> TestResult<MatrixEventId> {
    Ok(MatrixEventId::parse(value)?)
}

fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<HeptaAgentLayout> {
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    Ok(HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(agent_id))
}

async fn store_and_outbox(
    temp: &TempDir,
) -> TestResult<(HeptaAgentLayout, MatrixDurableStore, OutboxRecord)> {
    let agent_id = agent()?;
    let layout = layout(temp, &agent_id)?;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room_id = room()?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user()?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let logical_id = outbox_id(&agent_id, &room_id, "thread", "turn", "item", "final");
    let txn_id = transaction_id(&logical_id, 1)?;
    let outbox = match store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical_id,
            revision: 1,
            txn_id,
            room_id,
            kind: OutboxKind::Final,
            payload: b"durable reply".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 10,
        })
        .await?
    {
        OutboxDisposition::Enqueued(record) => record,
        other => return Err(format!("unexpected outbox disposition: {other:?}").into()),
    };
    let mut claimed = store.claim_outbox(10, 30, 1).await?;
    let claimed = claimed.pop().ok_or("outbox was not claimed")?;
    assert_eq!(claimed.stable_txn_id, outbox.stable_txn_id);
    Ok((layout, store, claimed))
}

#[tokio::test]
async fn transport_acceptance_is_not_terminal_until_sync_observation() -> TestResult {
    let temp = TempDir::new()?;
    let (_layout, store, claimed) = store_and_outbox(&temp).await?;
    let authority = MatrixDispatchAuthority::owner_local(&claimed.stable_txn_id);

    let prepared = prepare_send(&store, &claimed, &authority, 10).await?;
    assert_eq!(prepared.state, MatrixDispatchState::Prepared);
    store
        .mark_matrix_dispatch_dispatched(&claimed.stable_txn_id, claimed.attempts, &digest('1'), 11)
        .await?;
    let event_id = event("$accepted:example.org")?;
    let accepted = store
        .mark_matrix_dispatch_accepted(
            &claimed.stable_txn_id,
            claimed.attempts,
            &event_id,
            &digest('2'),
            12,
        )
        .await?;
    assert_eq!(accepted.state, MatrixDispatchState::Accepted);
    let outbox = store
        .outbox_for_txn(&claimed.stable_txn_id)
        .await?
        .ok_or("outbox disappeared")?;
    assert_eq!(outbox.state, OutboxState::InFlight);
    assert_eq!(outbox.sent_event_id, None);

    let terminal = observe_send(
        &store,
        Some(&claimed.stable_txn_id),
        &event_id,
        &claimed.room_id,
        &digest('3'),
        13,
    )
    .await?
    .ok_or("dispatch observation did not match")?;
    assert_eq!(terminal.state, MatrixDispatchState::ObservedSucceeded);
    assert_eq!(terminal.send_observation_digest, Some(digest('3')));
    let outbox = store
        .outbox_for_txn(&claimed.stable_txn_id)
        .await?
        .ok_or("outbox disappeared after observation")?;
    assert_eq!(outbox.state, OutboxState::Sent);
    assert_eq!(outbox.sent_event_id, Some(event_id));
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn indeterminate_dispatch_survives_reopen_and_reuses_only_stable_txn() -> TestResult {
    let temp = TempDir::new()?;
    let (layout, store, claimed) = store_and_outbox(&temp).await?;
    let authority = MatrixDispatchAuthority::owner_local(&claimed.stable_txn_id);
    prepare_send(&store, &claimed, &authority, 10).await?;
    store
        .mark_matrix_dispatch_dispatched(&claimed.stable_txn_id, claimed.attempts, &digest('1'), 11)
        .await?;
    store
        .mark_matrix_dispatch_indeterminate(
            &claimed.stable_txn_id,
            claimed.attempts,
            &digest('2'),
            12,
        )
        .await?;
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let pending = reopened
        .matrix_dispatch(&claimed.stable_txn_id)
        .await?
        .ok_or("dispatch did not survive reopen")?;
    assert_eq!(pending.state, MatrixDispatchState::Indeterminate);

    let mut reclaimed = reopened.claim_outbox(41, 30, 1).await?;
    let reclaimed = reclaimed.pop().ok_or("expired uncertain send was not reclaimed")?;
    assert_eq!(reclaimed.stable_txn_id, claimed.stable_txn_id);
    assert_eq!(reclaimed.attempts, claimed.attempts + 1);
    prepare_send(&reopened, &reclaimed, &authority, 41).await?;
    reopened
        .mark_matrix_dispatch_dispatched(
            &reclaimed.stable_txn_id,
            reclaimed.attempts,
            &digest('4'),
            41,
        )
        .await?;

    let event_id = event("$reconciled:example.org")?;
    let terminal = observe_send(
        &reopened,
        Some(&reclaimed.stable_txn_id),
        &event_id,
        &reclaimed.room_id,
        &digest('3'),
        42,
    )
    .await?
    .ok_or("reopened dispatch did not reconcile")?;
    assert_eq!(terminal.state, MatrixDispatchState::ObservedSucceeded);
    assert_eq!(terminal.attempt, reclaimed.attempts);
    let outbox = reopened
        .outbox_for_txn(&reclaimed.stable_txn_id)
        .await?
        .ok_or("reconciled outbox disappeared")?;
    assert_eq!(outbox.state, OutboxState::Sent);
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn crash_after_dispatch_prepare_reuses_only_stable_txn() -> TestResult {
    let temp = TempDir::new()?;
    let (layout, store, claimed) = store_and_outbox(&temp).await?;
    let authority = MatrixDispatchAuthority::owner_local(&claimed.stable_txn_id);
    prepare_send(&store, &claimed, &authority, 10).await?;
    store
        .mark_matrix_dispatch_dispatched(&claimed.stable_txn_id, claimed.attempts, &digest('1'), 11)
        .await?;
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let mut reclaimed = reopened.claim_outbox(41, 30, 1).await?;
    let reclaimed = reclaimed
        .pop()
        .ok_or("crashed dispatched send was not reclaimed")?;
    assert_eq!(reclaimed.stable_txn_id, claimed.stable_txn_id);
    assert_eq!(reclaimed.attempts, claimed.attempts + 1);
    prepare_send(&reopened, &reclaimed, &authority, 41).await?;
    let retried = reopened
        .mark_matrix_dispatch_dispatched(
            &reclaimed.stable_txn_id,
            reclaimed.attempts,
            &digest('2'),
            41,
        )
        .await?;
    assert_eq!(retried.state, MatrixDispatchState::Dispatched);
    assert_eq!(retried.attempt, reclaimed.attempts);
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn redaction_keeps_original_send_evidence_and_uses_separate_digest() -> TestResult {
    let temp = TempDir::new()?;
    let (_layout, store, claimed) = store_and_outbox(&temp).await?;
    let authority = MatrixDispatchAuthority::owner_local(&claimed.stable_txn_id);
    prepare_send(&store, &claimed, &authority, 10).await?;
    store
        .mark_matrix_dispatch_dispatched(&claimed.stable_txn_id, claimed.attempts, &digest('1'), 11)
        .await?;
    let event_id = event("$redacted:example.org")?;
    store
        .mark_matrix_dispatch_accepted(
            &claimed.stable_txn_id,
            claimed.attempts,
            &event_id,
            &digest('2'),
            12,
        )
        .await?;
    observe_send(
        &store,
        Some(&claimed.stable_txn_id),
        &event_id,
        &claimed.room_id,
        &digest('3'),
        13,
    )
    .await?
    .ok_or("send observation missing")?;
    let redacted = observe_redaction(&store, &event_id, &digest('4'), 14)
        .await?
        .ok_or("redaction observation missing")?;
    assert_eq!(redacted.state, MatrixDispatchState::Redacted);
    assert_eq!(redacted.send_observation_digest, Some(digest('3')));
    assert_eq!(redacted.redaction_observation_digest, Some(digest('4')));

    let replay = observe_redaction(&store, &event_id, &digest('4'), 15)
        .await?
        .ok_or("idempotent redaction replay missing")?;
    assert_eq!(replay, redacted);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn terminal_dispatch_can_be_archived_without_losing_evidence() -> TestResult {
    let temp = TempDir::new()?;
    let (_layout, store, claimed) = store_and_outbox(&temp).await?;
    let authority = MatrixDispatchAuthority::owner_local(&claimed.stable_txn_id);
    prepare_send(&store, &claimed, &authority, 10).await?;
    store
        .mark_matrix_dispatch_dispatched(&claimed.stable_txn_id, claimed.attempts, &digest('1'), 11)
        .await?;
    let event_id = event("$archive:example.org")?;
    observe_send(
        &store,
        Some(&claimed.stable_txn_id),
        &event_id,
        &claimed.room_id,
        &digest('3'),
        13,
    )
    .await?
    .ok_or("terminal observation missing")?;

    assert_eq!(
        store.archive_terminal_matrix_dispatches(13, 20, 10).await?,
        1
    );
    let archived = store
        .matrix_dispatch(&claimed.stable_txn_id)
        .await?
        .ok_or("archived dispatch disappeared")?;
    assert_eq!(archived.archived_at_ms, Some(20));
    assert_eq!(archived.send_observation_digest, Some(digest('3')));
    store.close().await;
    Ok(())
}
