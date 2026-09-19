use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const ROOM: &str = "!dispatch:example.test";

fn agent() -> TestResult<AgentId> {
    Ok(AgentId::parse(AGENT)?)
}

fn room() -> TestResult<MatrixRoomId> {
    Ok(MatrixRoomId::parse(ROOM)?)
}

fn user() -> TestResult<MatrixUserId> {
    Ok(MatrixUserId::parse("@agent:example.test")?)
}

fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<codex_hepta_paths::HeptaAgentLayout> {
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let canonical = fleet_root.canonicalize()?;
    Ok(HeptaFleetRoot::parse(canonical)?.layout().agent(agent_id))
}

async fn prepared_store(
    temp: &TempDir,
) -> TestResult<(AgentId, codex_hepta_paths::HeptaAgentLayout, MatrixDurableStore)> {
    let agent_id = agent()?;
    let layout = layout(temp, &agent_id)?;
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room()?,
            agent_user_id: user()?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok((agent_id, layout, store))
}

async fn claimed_outbox(
    store: &MatrixDurableStore,
    agent_id: &AgentId,
) -> TestResult<codex_hepta_matrix_store::OutboxRecord> {
    let room_id = room()?;
    let logical_id = outbox_id(agent_id, &room_id, "thread-1", "turn-1", "item-1", "final");
    let txn_id = transaction_id(&logical_id, 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical_id,
            revision: 1,
            txn_id,
            room_id,
            kind: OutboxKind::Final,
            payload: b"durable terminal evidence".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 2,
        })
        .await?;
    Ok(store.claim_outbox(3, 30, 1).await?.remove(0))
}

#[tokio::test]
async fn terminal_and_redaction_evidence_survive_reopen_without_overwrite() -> TestResult {
    let temp = TempDir::new()?;
    let (agent_id, layout, store) = prepared_store(&temp).await?;
    let outbox = claimed_outbox(&store, &agent_id).await?;
    let payload_digest = Sha256Digest::for_bytes(&outbox.payload).as_str().to_string();

    store.prepare_dispatch(&outbox, 3).await?;
    store
        .bind_dispatch_authority(
            &outbox.stable_txn_id,
            "operation.1",
            "https://matrix.example.test",
            "DEVICE1",
            1,
            7,
            "grant.1",
            &payload_digest,
            10_000,
            4,
        )
        .await?;
    store
        .mark_dispatch_dispatched(&outbox.stable_txn_id, 5)
        .await?;
    let transport_event = MatrixEventId::parse("$transport")?;
    store
        .mark_dispatch_transport_accepted(&outbox.stable_txn_id, &transport_event, 6)
        .await?;
    assert_eq!(store.unresolved_dispatch_count().await?, 1);
    store.close().await;

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let terminal_event = MatrixEventId::parse("$terminal")?;
    let send_digest = "a".repeat(64);
    assert!(
        reopened
            .observe_dispatch_terminal_success_if_known(
                &outbox.stable_txn_id,
                &room()?,
                &terminal_event,
                &send_digest,
                7,
            )
            .await?
    );
    assert_eq!(reopened.unresolved_dispatch_count().await?, 0);
    let succeeded = reopened
        .dispatch_record(&outbox.stable_txn_id)
        .await?
        .ok_or("dispatch row missing")?;
    assert_eq!(succeeded.state, MatrixDispatchState::Succeeded);
    assert_eq!(succeeded.send_observation_digest.as_deref(), Some(send_digest.as_str()));
    assert_eq!(succeeded.redaction_observation_digest, None);
    assert_eq!(
        reopened
            .dispatch_archive_segment_count(&outbox.stable_txn_id)
            .await?,
        1
    );

    let redaction_digest = "b".repeat(64);
    assert!(
        reopened
            .observe_dispatch_redaction_if_known(
                &room()?,
                &terminal_event,
                &redaction_digest,
                8,
            )
            .await?
    );
    let redacted = reopened
        .dispatch_record(&outbox.stable_txn_id)
        .await?
        .ok_or("redacted dispatch row missing")?;
    assert_eq!(redacted.state, MatrixDispatchState::Redacted);
    assert_eq!(redacted.send_observation_digest.as_deref(), Some(send_digest.as_str()));
    assert_eq!(
        redacted.redaction_observation_digest.as_deref(),
        Some(redaction_digest.as_str())
    );
    assert_eq!(
        reopened
            .dispatch_archive_segment_count(&outbox.stable_txn_id)
            .await?,
        2
    );
    reopened.close().await;

    let reopened_again =
        MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let durable = reopened_again
        .dispatch_record(&outbox.stable_txn_id)
        .await?
        .ok_or("durable dispatch row missing after second reopen")?;
    assert_eq!(durable.state, MatrixDispatchState::Redacted);
    assert_eq!(durable.send_observation_digest.as_deref(), Some(send_digest.as_str()));
    assert_eq!(
        durable.redaction_observation_digest.as_deref(),
        Some(redaction_digest.as_str())
    );
    assert_eq!(
        reopened_again
            .dispatch_archive_segment_count(&outbox.stable_txn_id)
            .await?,
        2
    );
    reopened_again.close().await;
    Ok(())
}

#[tokio::test]
async fn authority_binding_rejects_payload_drift() -> TestResult {
    let temp = TempDir::new()?;
    let (agent_id, _layout, store) = prepared_store(&temp).await?;
    let outbox = claimed_outbox(&store, &agent_id).await?;
    store.prepare_dispatch(&outbox, 3).await?;
    let error = store
        .bind_dispatch_authority(
            &outbox.stable_txn_id,
            "operation.1",
            "https://matrix.example.test",
            "DEVICE1",
            1,
            7,
            "grant.1",
            &"c".repeat(64),
            10_000,
            4,
        )
        .await
        .expect_err("payload drift must fail");
    assert!(matches!(error, MatrixDurableError::Conflict));
    store.close().await;
    Ok(())
}


#[tokio::test]
async fn transport_exhaustion_does_not_poison_logical_stream_before_terminal_observation() -> TestResult {
    let temp = TempDir::new()?;
    let (agent_id, _layout, store) = prepared_store(&temp).await?;
    let room_id = room()?;
    let logical_id = outbox_id(
        &agent_id,
        &room_id,
        "thread-1",
        "turn-1",
        "logical-stream",
        "final",
    );
    let root_txn = transaction_id(&logical_id, 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical_id.clone(),
            revision: 1,
            txn_id: root_txn.clone(),
            room_id: room_id.clone(),
            kind: OutboxKind::Final,
            payload: b"root".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 2,
        })
        .await?;
    let root = store.claim_outbox(3, 30, 1).await?.remove(0);
    store.prepare_dispatch(&root, 3).await?;
    store.mark_dispatch_dispatched(&root_txn, 4).await?;
    store.mark_dispatch_indeterminate(&root_txn, 5).await?;
    store
        .mark_outbox_permanent_failure(&root_txn, root.attempts, 6)
        .await?;

    let edit_txn = transaction_id(&logical_id, 2)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical_id,
            revision: 2,
            txn_id: edit_txn.clone(),
            room_id: room_id.clone(),
            kind: OutboxKind::Final,
            payload: b"edit".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 7,
        })
        .await?;

    assert!(
        store.claim_outbox(8, 30, 10).await?.is_empty(),
        "dependent revision must wait while root effect remains indeterminate"
    );

    let terminal_event = MatrixEventId::parse("$root-terminal")?;
    store
        .observe_dispatch_terminal_success_if_known(
            &root_txn,
            &room_id,
            &terminal_event,
            &"d".repeat(64),
            9,
        )
        .await?;

    let claimed_edit = store.claim_outbox(10, 30, 10).await?;
    assert_eq!(claimed_edit.len(), 1);
    assert_eq!(claimed_edit[0].stable_txn_id, edit_txn);
    assert_eq!(
        claimed_edit[0].replaces_event_id.as_ref(),
        Some(&terminal_event)
    );
    store.close().await;
    Ok(())
}
