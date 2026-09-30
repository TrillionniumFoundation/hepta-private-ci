use super::*;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

#[tokio::test]
async fn waiting_stream_replacement_cannot_starve_another_room_with_claim_limit_one() -> TestResult
{
    let temp = TempDir::new()?;
    let owner = agent(FIRST_AGENT)?;
    let store =
        MatrixDurableStore::open(&layout(&temp, &owner)?, MatrixDurableConfig::default()).await?;
    let waiting_room = room("!waiting:example.test")?;
    let independent_room = room("!independent:example.test")?;
    for room_id in [&waiting_room, &independent_room] {
        bind_room(
            &store,
            room_id,
            &user("@agent:example.test")?,
            /*at_ms*/ 10,
        )
        .await?;
    }
    let root = outbox_draft(
        &owner,
        &waiting_room,
        "waiting-stream",
        OutboxKind::TextDelta,
        b"root",
        /*created_at_ms*/ 10,
    )?;
    store.enqueue_outbox(&root).await?;
    let claimed = store
        .claim_outbox(/*now_ms*/ 160, /*lease_ms*/ 30, /*limit*/ 1)
        .await?;
    assert_eq!(claimed.len(), 1);
    store
        .mark_outbox_retry(
            &root.txn_id,
            claimed[0].attempts,
            /*now_ms*/ 161,
            /*next_attempt_at_ms*/ 1_000,
        )
        .await?;
    let replacement = OutboxDraft {
        revision: 2,
        txn_id: transaction_id(&root.logical_outbox_id, /*revision*/ 2)?,
        payload: b"replacement".to_vec(),
        created_at_ms: 170,
        ..root.clone()
    };
    store.enqueue_outbox(&replacement).await?;
    let independent = outbox_draft(
        &owner,
        &independent_room,
        "independent",
        OutboxKind::Final,
        b"ready",
        /*created_at_ms*/ 330,
    )?;
    store.enqueue_outbox(&independent).await?;
    let ready = store
        .claim_outbox(/*now_ms*/ 400, /*lease_ms*/ 30, /*limit*/ 1)
        .await?;
    assert_eq!(ready.len(), 1);
    assert_eq!(ready[0].stable_txn_id, independent.txn_id);
    assert_eq!(ready[0].room_id, independent_room);
    assert_eq!(
        store
            .outbox_for_txn(&replacement.txn_id)
            .await?
            .ok_or("replacement missing")?
            .state,
        OutboxState::Pending
    );
    store
        .mark_outbox_sent(
            &independent.txn_id,
            ready[0].attempts,
            &event("$independent-sent")?,
            /*now_ms*/ 401,
        )
        .await?;
    let root_retry = store
        .claim_outbox(
            /*now_ms*/ 1_000, /*lease_ms*/ 30, /*limit*/ 1,
        )
        .await?;
    assert_eq!(root_retry.len(), 1);
    assert_eq!(root_retry[0].stable_txn_id, root.txn_id);
    let root_event = event("$waiting-root-sent")?;
    store
        .mark_outbox_sent(
            &root.txn_id,
            root_retry[0].attempts,
            &root_event,
            /*now_ms*/ 1_001,
        )
        .await?;
    let unblocked = store
        .claim_outbox(
            /*now_ms*/ 1_002, /*lease_ms*/ 30, /*limit*/ 1,
        )
        .await?;
    assert_eq!(unblocked.len(), 1);
    assert_eq!(unblocked[0].stable_txn_id, replacement.txn_id);
    assert_eq!(unblocked[0].replaces_event_id.as_ref(), Some(&root_event));
    Ok(())
}

#[tokio::test]
async fn coalescing_full_stream_prefix_rejects_one_byte_over_cap_without_mutation() -> TestResult {
    let temp = TempDir::new()?;
    let owner = agent(FIRST_AGENT)?;
    let batch_bytes = 64 * 1024;
    let store = MatrixDurableStore::open(
        &layout(&temp, &owner)?,
        MatrixDurableConfig {
            max_delta_batch_bytes: batch_bytes,
            ..MatrixDurableConfig::default()
        },
    )
    .await?;
    let room_id = room("!prefix-cap:example.test")?;
    bind_room(
        &store,
        &room_id,
        &user("@agent:example.test")?,
        /*at_ms*/ 10,
    )
    .await?;
    let root = outbox_draft(
        &owner,
        &room_id,
        "prefix-cap",
        OutboxKind::TextDelta,
        b"x",
        /*created_at_ms*/ 20,
    )?;
    for revision in 1..=16 {
        store
            .enqueue_outbox(&OutboxDraft {
                revision,
                txn_id: transaction_id(&root.logical_outbox_id, revision)?,
                payload: vec![
                    b'x';
                    if revision == 16 {
                        batch_bytes - 1
                    } else {
                        batch_bytes
                    }
                ],
                created_at_ms: 20 + 300 * revision,
                ..root.clone()
            })
            .await?;
    }
    let at_cap = OutboxDraft {
        revision: 17,
        txn_id: transaction_id(&root.logical_outbox_id, /*revision*/ 17)?,
        created_at_ms: 5_120,
        ..root.clone()
    };
    store.enqueue_outbox(&at_cap).await?;
    let before = store
        .outbox_for_txn(&at_cap.txn_id)
        .await?
        .ok_or("capped row missing")?;
    assert_eq!(before.payload.len(), 1024 * 1024);
    let over_cap = OutboxDraft {
        revision: 18,
        txn_id: transaction_id(&root.logical_outbox_id, /*revision*/ 18)?,
        created_at_ms: 5_121,
        ..root.clone()
    };
    assert!(matches!(
        store.enqueue_outbox(&over_cap).await,
        Err(MatrixDurableError::Invalid)
    ));
    assert_eq!(
        store
            .outbox_for_txn(&at_cap.txn_id)
            .await?
            .ok_or("capped row lost")?,
        before
    );
    assert_eq!(
        store.next_outbox_revision(&root.logical_outbox_id).await?,
        18
    );
    assert!(store.outbox_for_txn(&over_cap.txn_id).await?.is_none());
    Ok(())
}

#[tokio::test]
async fn legacy_oversize_or_empty_outbox_payload_cannot_be_read_or_claimed() -> TestResult {
    for payload in [vec![b'x'; 1024 * 1024 + 1], Vec::new()] {
        let temp = TempDir::new()?;
        let owner = agent(FIRST_AGENT)?;
        let store =
            MatrixDurableStore::open(&layout(&temp, &owner)?, MatrixDurableConfig::default())
                .await?;
        let room_id = room("!legacy-payload:example.test")?;
        bind_room(
            &store,
            &room_id,
            &user("@agent:example.test")?,
            /*at_ms*/ 10,
        )
        .await?;
        let draft = outbox_draft(
            &owner,
            &room_id,
            "legacy",
            OutboxKind::Final,
            b"valid",
            /*created_at_ms*/ 20,
        )?;
        store.enqueue_outbox(&draft).await?;
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(SqliteConnectOptions::new().filename(store.path()))
            .await?;
        sqlx::query(
            "UPDATE outbox_messages SET payload = ?, payload_sha256 = ? WHERE stable_txn_id = ?",
        )
        .bind(&payload)
        .bind(codex_hepta_contracts::Sha256Digest::for_bytes(&payload).as_str())
        .bind(draft.txn_id.as_str())
        .execute(&pool)
        .await?;
        assert!(matches!(
            store.outbox_for_txn(&draft.txn_id).await,
            Err(MatrixDurableError::Corrupt)
        ));
        assert!(matches!(
            store.pending_outbox(/*limit*/ 1).await,
            Err(MatrixDurableError::Corrupt)
        ));
        assert!(matches!(
            store
                .claim_outbox(/*now_ms*/ 30, /*lease_ms*/ 30, /*limit*/ 1)
                .await,
            Err(MatrixDurableError::Corrupt)
        ));
        let attempts: i64 =
            sqlx::query_scalar("SELECT attempts FROM outbox_messages WHERE stable_txn_id = ?")
                .bind(draft.txn_id.as_str())
                .fetch_one(&pool)
                .await?;
        assert_eq!(attempts, 0);
        pool.close().await;
    }
    Ok(())
}
