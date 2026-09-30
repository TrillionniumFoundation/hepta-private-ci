use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

async fn fixture() -> TestResult<(TempDir, HeptaAgentLayout, MatrixDurableStore, MatrixRoomId)> {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!adversarial-outbox:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok((temp, layout, store, room))
}

fn draft(
    room: &MatrixRoomId,
    stream: &str,
    revision: u64,
    kind: OutboxKind,
    payload: Vec<u8>,
    created_at_ms: u64,
) -> TestResult<OutboxDraft> {
    Ok(OutboxDraft {
        logical_outbox_id: stream.to_string(),
        revision,
        txn_id: transaction_id(stream, revision)?,
        room_id: room.clone(),
        kind,
        payload,
        binding_revision: 1,
        generation: 1,
        created_at_ms,
    })
}

#[tokio::test]
async fn coalescing_checks_the_full_prefix_and_rolls_back_an_oversize_fragment() -> TestResult {
    let (_temp, layout, store, room) = fixture().await?;
    let chunk_bytes = 64 * 1024;
    let max_payload_bytes = 1024 * 1024;
    for revision in 1..=17 {
        let bytes = match revision {
            1..=15 => chunk_bytes,
            16 => chunk_bytes / 2,
            17 => 1,
            _ => unreachable!(),
        };
        store
            .enqueue_outbox(&draft(
                &room,
                "bounded-prefix",
                revision,
                OutboxKind::TextDelta,
                vec![b'x'; bytes],
                revision * 1_000,
            )?)
            .await?;
    }
    let before = store
        .snapshot(/*now_ms*/ 17_001, /*queue_limit*/ 20)
        .await?;
    let mut next = draft(
        &room,
        "bounded-prefix",
        /*revision*/ 18,
        OutboxKind::TextDelta,
        vec![b'x'; chunk_bytes / 2],
        /*created_at_ms*/ 17_001,
    )?;
    assert_eq!(
        store.enqueue_outbox(&next).await,
        Err(MatrixDurableError::Invalid)
    );
    assert_eq!(
        store
            .snapshot(/*now_ms*/ 17_001, /*queue_limit*/ 20)
            .await?,
        before
    );
    assert_eq!(store.next_outbox_revision("bounded-prefix").await?, 18);

    next.payload.pop();
    let OutboxDisposition::Coalesced(full) = store.enqueue_outbox(&next).await? else {
        return Err("exactly bounded prefix was not coalesced".into());
    };
    assert_eq!(full.payload, vec![b'x'; max_payload_bytes]);
    let committed = store
        .snapshot(/*now_ms*/ 17_001, /*queue_limit*/ 20)
        .await?;
    store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened
            .snapshot(/*now_ms*/ 17_001, /*queue_limit*/ 20)
            .await?,
        committed
    );
    assert_eq!(
        reopened
            .enqueue_outbox(&draft(
                &room,
                "bounded-prefix",
                /*revision*/ 19,
                OutboxKind::TextDelta,
                vec![b'x'],
                /*created_at_ms*/ 17_002,
            )?)
            .await,
        Err(MatrixDurableError::Invalid)
    );
    assert_eq!(
        reopened
            .snapshot(/*now_ms*/ 17_001, /*queue_limit*/ 20)
            .await?,
        committed
    );
    Ok(())
}

#[tokio::test]
async fn waiting_replacements_do_not_starve_independent_streams_with_a_one_item_page() -> TestResult
{
    let (_temp, _layout, store, room) = fixture().await?;
    let root_draft = draft(
        &room,
        "blocked-stream",
        /*revision*/ 1,
        OutboxKind::TextDelta,
        b"root".to_vec(),
        /*created_at_ms*/ 20,
    )?;
    store.enqueue_outbox(&root_draft).await?;
    let root = store
        .claim_outbox(
            /*now_ms*/ 170, /*lease_ms*/ 1_000, /*limit*/ 1,
        )
        .await?;
    let [root] = root.as_slice() else {
        return Err("root was not claimed".into());
    };
    let replacement = draft(
        &room,
        "blocked-stream",
        /*revision*/ 2,
        OutboxKind::Final,
        b"final".to_vec(),
        /*created_at_ms*/ 171,
    )?;
    store.enqueue_outbox(&replacement).await?;

    for (stream, at_ms) in [("independent-1", 172), ("independent-2", 175)] {
        let independent = draft(
            &room,
            stream,
            /*revision*/ 1,
            OutboxKind::Terminal,
            b"independent".to_vec(),
            at_ms,
        )?;
        store.enqueue_outbox(&independent).await?;
        let claimed = store
            .claim_outbox(at_ms, /*lease_ms*/ 10, /*limit*/ 1)
            .await?;
        assert_eq!(
            claimed
                .iter()
                .map(|record| &record.stable_txn_id)
                .collect::<Vec<_>>(),
            vec![&independent.txn_id]
        );
        store
            .mark_outbox_sent(
                &independent.txn_id,
                /*expected_attempt*/ 1,
                &MatrixEventId::parse(format!("${stream}"))?,
                at_ms + 1,
            )
            .await?;
        if stream == "independent-1" {
            store
                .mark_outbox_retry(
                    &root.stable_txn_id,
                    root.attempts,
                    /*now_ms*/ 174,
                    /*next_attempt_at_ms*/ 500,
                )
                .await?;
        }
    }
    let retried = store
        .claim_outbox(/*now_ms*/ 500, /*lease_ms*/ 10, /*limit*/ 1)
        .await?;
    assert_eq!(
        retried
            .iter()
            .map(|record| (&record.stable_txn_id, record.attempts))
            .collect::<Vec<_>>(),
        vec![(&root_draft.txn_id, 2)]
    );
    let event = MatrixEventId::parse("$unblocked-root")?;
    store
        .mark_outbox_sent(
            &root_draft.txn_id,
            /*expected_attempt*/ 2,
            &event,
            /*now_ms*/ 501,
        )
        .await?;
    let claimed = store
        .claim_outbox(/*now_ms*/ 501, /*lease_ms*/ 10, /*limit*/ 1)
        .await?;
    assert_eq!(
        claimed
            .iter()
            .map(|record| (&record.stable_txn_id, &record.replaces_event_id))
            .collect::<Vec<_>>(),
        vec![(&replacement.txn_id, &Some(event))]
    );
    Ok(())
}

#[tokio::test]
async fn failed_roots_still_settle_replacements_without_sending_them() -> TestResult {
    let (_temp, _layout, store, room) = fixture().await?;
    let root = draft(
        &room,
        "failed-stream",
        /*revision*/ 1,
        OutboxKind::Final,
        b"root".to_vec(),
        /*created_at_ms*/ 20,
    )?;
    let replacement = draft(
        &room,
        "failed-stream",
        /*revision*/ 2,
        OutboxKind::Final,
        b"replacement".to_vec(),
        /*created_at_ms*/ 21,
    )?;
    store.enqueue_outbox(&root).await?;
    store.enqueue_outbox(&replacement).await?;
    assert_eq!(
        store
            .claim_outbox(/*now_ms*/ 21, /*lease_ms*/ 10, /*limit*/ 1)
            .await?
            .len(),
        1
    );
    store
        .mark_outbox_permanent_failure(
            &root.txn_id,
            /*expected_attempt*/ 1,
            /*now_ms*/ 22,
        )
        .await?;
    assert_eq!(
        store
            .claim_outbox(/*now_ms*/ 22, /*lease_ms*/ 10, /*limit*/ 1)
            .await?,
        vec![]
    );
    let settled = store
        .outbox_for_txn(&replacement.txn_id)
        .await?
        .ok_or("replacement disappeared")?;
    assert_eq!(
        (settled.state, settled.attempts, settled.sent_event_id),
        (OutboxState::PermanentFailure, 0, None)
    );
    Ok(())
}
