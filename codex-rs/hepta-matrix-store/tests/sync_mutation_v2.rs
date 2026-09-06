use std::error::Error;
use std::fs;
use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationDispositionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use codex_hepta_matrix_protocol::room_project_idempotency_key;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::ChangeKind;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::InboxQueuedDraft;
use codex_hepta_matrix_store::InboxState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixEventId;
use codex_hepta_matrix_store::MatrixRoomId;
use codex_hepta_matrix_store::MatrixUserId;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_matrix_store::RoomThreadBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use sqlx::SqlitePool;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const AGENT_USER_ID: &str = "@hepta:example.test";

fn agent() -> TestResult<AgentId> {
    Ok(AgentId::parse(AGENT_ID)?)
}

fn room(value: &str) -> TestResult<MatrixRoomId> {
    Ok(MatrixRoomId::parse(value)?)
}

fn event(value: &str) -> TestResult<MatrixEventId> {
    Ok(MatrixEventId::parse(value)?)
}

fn user(value: &str) -> TestResult<MatrixUserId> {
    Ok(MatrixUserId::parse(value)?)
}

fn layout(temp: &TempDir, agent_id: &AgentId) -> TestResult<HeptaAgentLayout> {
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    Ok(HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(agent_id))
}

async fn store_and_room(temp: &TempDir, room_id: &MatrixRoomId) -> TestResult<MatrixDurableStore> {
    let agent_id = agent()?;
    let store =
        MatrixDurableStore::open(&layout(temp, &agent_id)?, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok(store)
}

async fn open_hostile_fixture_pool(path: &Path) -> TestResult<SqlitePool> {
    // These tests own the temporary database and deliberately inject hostile
    // rows/schema after closing its owner. This is not a recovery backend;
    // production path-based SQLite recovery must continue to fail closed.
    assert!(fs::symlink_metadata(path)?.file_type().is_file());
    let parent = path
        .parent()
        .ok_or_else(|| std::io::Error::other("fixture parent missing"))?;
    let parent = AbsolutePathBuf::try_from(parent.to_path_buf())?;
    Ok(SqliteConfig::new_for_testing(parent)
        .open_durable_evidence_pool(path)
        .await?)
}

fn mutation(
    source_event_id: MatrixEventId,
    room_id: MatrixRoomId,
    body: MatrixSyncMutationBodyV2,
    at_ms: u64,
) -> TestResult<MatrixSyncMutationV2> {
    Ok(MatrixSyncMutationV2 {
        source_event_id,
        room_id,
        sender: user("@owner:example.test")?,
        binding_revision: 1,
        generation: 1,
        origin_server_ts_ms: at_ms,
        received_at_ms: at_ms + 1,
        body,
    })
}

fn inbox_draft(
    event_id: MatrixEventId,
    room_id: MatrixRoomId,
    payload: &[u8],
    at_ms: u64,
) -> TestResult<InboxDraft> {
    Ok(InboxDraft {
        event_id,
        room_id,
        sender: user("@owner:example.test")?,
        event_type: "m.room.message".to_string(),
        payload: payload.to_vec(),
        binding_revision: 1,
        generation: 1,
        origin_server_ts_ms: at_ms,
        received_at_ms: at_ms + 1,
    })
}

fn commit(
    expected: Option<&str>,
    next: &str,
    observed_at_ms: u64,
    mutations: Vec<MatrixSyncMutationV2>,
) -> MatrixSyncDecisionV2 {
    commit_with_fence(
        expected,
        next,
        observed_at_ms,
        /*checkpoint_revision*/ 1,
        /*checkpoint_generation*/ 1,
        mutations,
    )
}

fn commit_with_fence(
    expected: Option<&str>,
    next: &str,
    observed_at_ms: u64,
    checkpoint_revision: u64,
    checkpoint_generation: u64,
    mutations: Vec<MatrixSyncMutationV2>,
) -> MatrixSyncDecisionV2 {
    MatrixSyncDecisionV2::Commit {
        batch: MatrixSyncBatchV2 {
            schema_version: 2,
            operation_id: format!("commit-{observed_at_ms}-{next}"),
            checkpoint_revision,
            checkpoint_generation,
            expected_next_batch: expected.map(ToOwned::to_owned),
            next_batch: next.to_string(),
            observed_at_ms,
            mutations,
        },
    }
}

fn dispositions(result: MatrixSyncResultV2) -> TestResult<Vec<MatrixSyncMutationDispositionV2>> {
    match result {
        MatrixSyncResultV2::Committed { outcomes, .. } => Ok(outcomes
            .into_iter()
            .map(|outcome| outcome.disposition)
            .collect()),
        MatrixSyncResultV2::Cancelled { .. } => Err("commit returned cancellation".into()),
        MatrixSyncResultV2::CapacityExhausted { .. } => {
            Err("commit exhausted its bounded journal".into())
        }
    }
}

#[tokio::test]
async fn redaction_missing_target_and_cancellation_remain_distinct() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!sync-v2:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let original = event("$original")?;
    let timeline = mutation(
        original.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"must be redacted".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    let mut duplicate_timeline = timeline.clone();
    duplicate_timeline.received_at_ms += 1;
    let applied_decision = commit(
        /*expected*/ None,
        "s1",
        /*observed_at_ms*/ 11,
        vec![timeline],
    );
    let lost_ack_retry = applied_decision.clone();
    assert_eq!(
        dispositions(store.apply_sync_decision_v2(&applied_decision).await?)?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert_eq!(
        dispositions(store.apply_sync_decision_v2(&lost_ack_retry).await?)?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    let mut altered_observation = applied_decision.clone();
    let MatrixSyncDecisionV2::Commit { batch } = &mut altered_observation else {
        return Err("commit helper returned cancellation".into());
    };
    batch.observed_at_ms += 1;
    assert_eq!(
        store.apply_sync_decision_v2(&altered_observation).await,
        Err(MatrixDurableError::Conflict)
    );
    let mut altered_receipt = applied_decision.clone();
    let MatrixSyncDecisionV2::Commit { batch } = &mut altered_receipt else {
        return Err("commit helper returned cancellation".into());
    };
    batch.mutations[0].received_at_ms -= 1;
    assert_eq!(
        store.apply_sync_decision_v2(&altered_receipt).await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s1",
                    /*observed_at_ms*/ 12,
                    vec![duplicate_timeline.clone()],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Duplicate]
    );
    let mut drifted_timeline = duplicate_timeline;
    drifted_timeline.body = MatrixSyncMutationBodyV2::Timeline {
        event_type: "m.room.message".to_string(),
        payload: b"source identity drift".to_vec(),
    };
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s1",
                /*observed_at_ms*/ 13,
                vec![drifted_timeline],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );

    let redaction = mutation(
        event("$redaction")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: original.clone(),
        },
        /*at_ms*/ 20,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 21,
                    vec![redaction],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert!(store.inbox(&original).await?.is_none());
    let changes = store
        .read_changes(/*after_cursor*/ 0, /*limit*/ 100)
        .await?;
    assert!(changes.events.iter().any(|change| {
        change.kind == ChangeKind::InboxRedacted && change.event_id.as_ref() == Some(&original)
    }));
    assert_eq!(
        store
            .ingest_inbox(&inbox_draft(
                event("$redaction")?,
                room_id.clone(),
                b"conflicting V1 meaning",
                /*at_ms*/ 22,
            )?)
            .await,
        Err(MatrixDurableError::Conflict)
    );
    let late = event("$late")?;
    let missing_redaction = mutation(
        event("$redaction-before-target")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: late.clone(),
        },
        /*at_ms*/ 30,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s2"),
                    "s3",
                    /*observed_at_ms*/ 31,
                    vec![missing_redaction],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Missing]
    );
    store.close().await;
    let store =
        MatrixDurableStore::open(&layout(&temp, &agent()?)?, MatrixDurableConfig::default())
            .await?;
    assert_eq!(
        dispositions(
            store
                .lookup_sync_decision_v2("commit-11-s1")
                .await?
                .ok_or("missing durable decision")?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert!(
        store
            .lookup_sync_decision_v2("never-recorded")
            .await?
            .is_none()
    );
    assert_eq!(
        store
            .ingest_inbox(&inbox_draft(
                late.clone(),
                room_id.clone(),
                b"V1 must not resurrect",
                /*at_ms*/ 40,
            )?)
            .await,
        Err(MatrixDurableError::AccessDenied)
    );
    let late_timeline = mutation(
        late.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"must not resurrect".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s3"),
                    "s4",
                    /*observed_at_ms*/ 41,
                    vec![late_timeline],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Tombstoned]
    );
    assert!(store.inbox(&late).await?.is_none());
    let other_room = room("!other:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: other_room.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 42,
        })
        .await?;
    assert_eq!(
        store
            .ingest_inbox(&inbox_draft(
                late.clone(),
                other_room,
                b"V1 cross-room source reuse",
                /*at_ms*/ 43,
            )?)
            .await,
        Err(MatrixDurableError::Conflict)
    );

    let cancel_decision = MatrixSyncDecisionV2::Cancel {
        schema_version: 2,
        operation_id: "cancel-s4".to_string(),
        checkpoint_revision: 1,
        checkpoint_generation: 1,
        expected_next_batch: Some("s4".to_string()),
    };
    let cancelled = store.apply_sync_decision_v2(&cancel_decision).await?;
    assert_eq!(
        cancelled,
        MatrixSyncResultV2::Cancelled {
            schema_version: 2,
            operation_id: "cancel-s4".to_string(),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
            retained_next_batch: Some("s4".to_string()),
        }
    );
    let mut cross_kind_reuse = commit(Some("s4"), "s5", /*observed_at_ms*/ 44, Vec::new());
    let MatrixSyncDecisionV2::Commit { batch } = &mut cross_kind_reuse else {
        return Err("commit helper returned cancellation".into());
    };
    batch.operation_id = "cancel-s4".to_string();
    assert_eq!(
        store.apply_sync_decision_v2(&cross_kind_reuse).await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s4"),
                    "s5",
                    /*observed_at_ms*/ 45,
                    Vec::new(),
                ))
                .await?,
        )?,
        Vec::new()
    );
    assert_eq!(
        store.apply_sync_decision_v2(&cancel_decision).await?,
        cancelled
    );
    assert_eq!(
        store
            .lookup_sync_decision_v2("cancel-s4")
            .await?
            .ok_or("missing cancellation decision")?,
        cancelled
    );
    assert_eq!(
        dispositions(store.apply_sync_decision_v2(&applied_decision).await?)?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s5"
    );
    Ok(())
}

#[tokio::test]
async fn durable_replay_precedes_a_reduced_runtime_capacity() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!capacity-replay:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let decision = commit(
        /*expected*/ None,
        "s1",
        /*observed_at_ms*/ 20,
        vec![
            mutation(
                event("$capacity-replay-1")?,
                room_id.clone(),
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: b"one".to_vec(),
                },
                /*at_ms*/ 10,
            )?,
            mutation(
                event("$capacity-replay-2")?,
                room_id,
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: b"two".to_vec(),
                },
                /*at_ms*/ 11,
            )?,
        ],
    );
    store.apply_sync_decision_v2(&decision).await?;
    store.close().await;

    let store = MatrixDurableStore::open(
        &layout(&temp, &agent()?)?,
        MatrixDurableConfig {
            delta_coalesce_window_ms: 150,
            max_delta_batch_bytes: 16 * 1024,
            event_capacity: 1,
        },
    )
    .await?;
    assert_eq!(
        dispositions(store.apply_sync_decision_v2(&decision).await?)?,
        vec![
            MatrixSyncMutationDispositionV2::Applied,
            MatrixSyncMutationDispositionV2::Applied,
        ]
    );
    Ok(())
}

#[tokio::test]
async fn room_leave_and_replacement_tombstones_prevent_replay() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!left:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let pending = mutation(
        event("$before-leave")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"pending".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![pending],
        ))
        .await?;
    let logical_outbox_id = "before-room-leave";
    let outbox_txn_id = transaction_id(logical_outbox_id, /*revision*/ 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical_outbox_id.to_string(),
            revision: 1,
            txn_id: outbox_txn_id.clone(),
            room_id: room_id.clone(),
            kind: OutboxKind::Terminal,
            payload: b"must not send after leave".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 12,
        })
        .await?;
    let leave_event = event("$leave")?;
    let mut leave = mutation(
        leave_event.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    leave.sender = user(AGENT_USER_ID)?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 21,
                    vec![leave],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    let changes = store
        .read_changes(/*after_cursor*/ 0, /*limit*/ 100)
        .await?;
    assert!(changes.events.iter().any(|change| {
        change.kind == ChangeKind::RoomLeft && change.event_id.as_ref() == Some(&leave_event)
    }));
    assert!(store.pending_inbox(/*limit*/ 10).await?.is_empty());
    assert!(store.pending_outbox(/*limit*/ 10).await?.is_empty());
    assert!(
        store
            .claim_outbox(/*now_ms*/ 30, /*lease_ms*/ 100, /*limit*/ 10)
            .await?
            .is_empty()
    );
    assert!(store.outbox_for_txn(&outbox_txn_id).await?.is_none());
    let denied_logical_outbox_id = "after-room-leave";
    assert_eq!(
        store
            .enqueue_outbox(&OutboxDraft {
                logical_outbox_id: denied_logical_outbox_id.to_string(),
                revision: 1,
                txn_id: transaction_id(denied_logical_outbox_id, /*revision*/ 1)?,
                room_id: room_id.clone(),
                kind: OutboxKind::Terminal,
                payload: b"denied".to_vec(),
                binding_revision: 1,
                generation: 1,
                created_at_ms: 31,
            })
            .await,
        Err(MatrixDurableError::AccessDenied)
    );

    let leave_replay = mutation(
        event("$after-leave")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"blocked by leave".to_vec(),
        },
        /*at_ms*/ 25,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s2"),
                    "s3",
                    /*observed_at_ms*/ 26,
                    vec![leave_replay],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Tombstoned]
    );

    let replacement = room("!replacement:example.test")?;
    let tombstone_event = event("$room-tombstone")?;
    let tombstone = mutation(
        tombstone_event.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomTombstone {
            replacement_room_id: replacement,
        },
        /*at_ms*/ 30,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            Some("s3"),
            "s4",
            /*observed_at_ms*/ 31,
            vec![tombstone],
        ))
        .await?;
    let changes = store
        .read_changes(/*after_cursor*/ 0, /*limit*/ 100)
        .await?;
    assert!(changes.events.iter().any(|change| {
        change.kind == ChangeKind::RoomTombstoned
            && change.event_id.as_ref() == Some(&tombstone_event)
    }));
    let replay = mutation(
        event("$after-replacement")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"blocked".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s4"),
                    "s5",
                    /*observed_at_ms*/ 41,
                    vec![replay],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Tombstoned]
    );
    assert_eq!(
        store
            .bind_room(&RoomBindingDraft {
                room_id: room_id.clone(),
                agent_user_id: user(AGENT_USER_ID)?,
                expected_revision: Some(1),
                generation: 2,
                changed_at_ms: 42,
            })
            .await,
        Err(MatrixDurableError::AccessDenied)
    );
    Ok(())
}

#[tokio::test]
async fn kicked_room_rebind_preserves_the_account_cursor_and_resumes_sync() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!kick-rebind:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let before_leave = mutation(
        event("$kick-before")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"old generation".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![before_leave],
        ))
        .await?;

    // A moderator, not the local user, may send the membership event that
    // removes the bound user. The departed membership is the local invariant.
    let mut kicked = mutation(
        event("$moderator-kick")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    kicked.sender = user("@moderator:example.test")?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 21,
                    vec![kicked],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );

    let rebound = store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: Some(1),
            generation: 2,
            changed_at_ms: 30,
        })
        .await?;
    assert_eq!(rebound.revision, 2);
    assert_eq!(rebound.generation, 2);
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("account checkpoint changed during room rebind")?
            .next_batch,
        "s2"
    );

    let mut after_rebind = mutation(
        event("$after-rebind")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"new generation".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    after_rebind.binding_revision = 2;
    after_rebind.generation = 2;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit_with_fence(
                    Some("s2"),
                    "s3",
                    /*observed_at_ms*/ 41,
                    /*checkpoint_revision*/ 1,
                    /*checkpoint_generation*/ 1,
                    vec![after_rebind],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert_eq!(store.pending_inbox(/*limit*/ 10).await?.len(), 1);
    Ok(())
}

#[tokio::test]
async fn one_room_rebind_does_not_fence_another_room_or_the_account_cursor() -> TestResult {
    let temp = TempDir::new()?;
    let room_a = room("!multi-a:example.test")?;
    let room_b = room("!multi-b:example.test")?;
    let store = store_and_room(&temp, &room_a).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_b.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 2,
        })
        .await?;
    let initial_a = mutation(
        event("$multi-a-initial")?,
        room_a.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"a1".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    let initial_b = mutation(
        event("$multi-b-initial")?,
        room_b.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"b1".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![initial_a, initial_b],
        ))
        .await?;

    let mut leave_a = mutation(
        event("$multi-a-leave")?,
        room_a.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    leave_a.sender = user(AGENT_USER_ID)?;
    store
        .apply_sync_decision_v2(&commit(
            Some("s1"),
            "s2",
            /*observed_at_ms*/ 21,
            vec![leave_a],
        ))
        .await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_a.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: Some(1),
            generation: 2,
            changed_at_ms: 30,
        })
        .await?;

    let mut next_a = mutation(
        event("$multi-a-next")?,
        room_a,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"a2".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    next_a.binding_revision = 2;
    next_a.generation = 2;
    let next_b = mutation(
        event("$multi-b-next")?,
        room_b,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"b2".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s2"),
                    "s3",
                    /*observed_at_ms*/ 41,
                    vec![next_a, next_b],
                ))
                .await?,
        )?,
        vec![
            MatrixSyncMutationDispositionV2::Applied,
            MatrixSyncMutationDispositionV2::Applied,
        ]
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("missing account checkpoint")?
            .next_batch,
        "s3"
    );
    Ok(())
}

#[tokio::test]
async fn caller_persisted_outbox_attempt_survives_a_later_room_leave() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let store_layout = layout(&temp, &agent_id)?;
    let room_id = room("!outbox-lost-ack:example.test")?;
    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let logical_outbox_id = "terminal-before-leave";
    let txn_id = transaction_id(logical_outbox_id, /*revision*/ 1)?;
    let draft = OutboxDraft {
        logical_outbox_id: logical_outbox_id.to_string(),
        revision: 1,
        txn_id: txn_id.clone(),
        room_id: room_id.clone(),
        kind: OutboxKind::Terminal,
        payload: b"already sent".to_vec(),
        binding_revision: 1,
        generation: 1,
        created_at_ms: 10,
    };
    store.enqueue_outbox(&draft).await?;
    let claimed = store
        .claim_outbox(/*now_ms*/ 11, /*lease_ms*/ 100, /*limit*/ 1)
        .await?;
    assert_eq!(claimed.len(), 1);
    let sent_event_id = event("$sent-before-leave")?;

    let mut leave = mutation(
        event("$leave-after-send")?,
        room_id,
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    leave.sender = user(AGENT_USER_ID)?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 21,
            vec![leave],
        ))
        .await?;
    assert!(store.pending_outbox(/*limit*/ 10).await?.is_empty());
    store.close().await;

    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    assert!(matches!(
        store.enqueue_outbox(&draft).await?,
        OutboxDisposition::Duplicate(_)
    ));
    assert_eq!(
        store
            .exact_outbox_revision(
                logical_outbox_id,
                &draft.room_id,
                draft.kind,
                &draft.payload,
                draft.binding_revision,
                draft.generation,
            )
            .await?,
        Some(1)
    );
    assert!(
        store
            .claim_outbox(
                /*now_ms*/ 200, /*lease_ms*/ 100, /*limit*/ 10
            )
            .await?
            .is_empty(),
        "an expired pre-leave lease must not be reclaimed"
    );
    let sent = store
        .mark_outbox_sent(
            &txn_id,
            claimed[0].attempts,
            &sent_event_id,
            /*now_ms*/ 201,
        )
        .await?;

    assert_eq!(
        store
            .mark_outbox_sent(
                &txn_id,
                claimed[0].attempts,
                &sent_event_id,
                /*now_ms*/ 202,
            )
            .await?,
        sent
    );
    assert_eq!(
        store
            .mark_outbox_sent(
                &txn_id,
                claimed[0].attempts,
                &event("$different-send-result")?,
                /*now_ms*/ 203,
            )
            .await,
        Err(MatrixDurableError::Conflict)
    );
    Ok(())
}

#[tokio::test]
async fn v1_source_hidden_by_leave_cannot_be_reused_after_rebind() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!v1-leave-rebind:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let source = event("$v1-before-leave")?;
    store
        .ingest_inbox(&inbox_draft(
            source.clone(),
            room_id.clone(),
            b"old fence meaning",
            /*at_ms*/ 10,
        )?)
        .await?;

    let leave = mutation(
        event("$leave-before-reuse")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 21,
            vec![leave],
        ))
        .await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: Some(1),
            generation: 2,
            changed_at_ms: 30,
        })
        .await?;

    let mut reused = mutation(
        source,
        room_id,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"new fence meaning".to_vec(),
        },
        /*at_ms*/ 40,
    )?;
    reused.binding_revision = 2;
    reused.generation = 2;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit_with_fence(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 41,
                /*checkpoint_revision*/ 1,
                /*checkpoint_generation*/ 1,
                vec![reused],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s1"
    );
    Ok(())
}

#[tokio::test]
async fn redacted_v1_source_cannot_be_reused_in_another_room() -> TestResult {
    let temp = TempDir::new()?;
    let source_room = room("!v1-source-room:example.test")?;
    let other_room = room("!v1-other-room:example.test")?;
    let store = store_and_room(&temp, &source_room).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: other_room.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 2,
        })
        .await?;
    let source = event("$v1-cross-room-redacted")?;
    store
        .ingest_inbox(&inbox_draft(
            source.clone(),
            source_room.clone(),
            b"source room meaning",
            /*at_ms*/ 10,
        )?)
        .await?;
    let redaction = mutation(
        event("$redact-before-cross-room-reuse")?,
        source_room,
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: source.clone(),
        },
        /*at_ms*/ 20,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 21,
            vec![redaction],
        ))
        .await?;

    let reused = mutation(
        source,
        other_room,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"other room meaning".to_vec(),
        },
        /*at_ms*/ 30,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 31,
                vec![reused],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s1"
    );
    Ok(())
}

#[tokio::test]
async fn tombstoned_v1_source_cannot_gain_a_new_v2_meaning() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!v1-redacted:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let source = event("$v1-redacted-source")?;
    store
        .ingest_inbox(&inbox_draft(
            source.clone(),
            room_id.clone(),
            b"V1 original meaning",
            /*at_ms*/ 10,
        )?)
        .await?;
    let redaction = mutation(
        event("$v1-redaction")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: source.clone(),
        },
        /*at_ms*/ 20,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 21,
            vec![redaction],
        ))
        .await?;

    let conflicting_timeline = mutation(
        source,
        room_id,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"different V2 meaning".to_vec(),
        },
        /*at_ms*/ 30,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 31,
                vec![conflicting_timeline],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s1"
    );
    Ok(())
}

#[tokio::test]
async fn v1_and_v2_timeline_identity_matches_exact_semantics_only() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!v1-v2-exact:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let source = event("$v1-v2-exact")?;
    store
        .ingest_inbox(&inbox_draft(
            source.clone(),
            room_id.clone(),
            b"same semantic payload",
            /*at_ms*/ 10,
        )?)
        .await?;
    let mut exact = mutation(
        source.clone(),
        room_id,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"same semantic payload".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    exact.received_at_ms = 20;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    /*expected*/ None,
                    "s1",
                    /*observed_at_ms*/ 20,
                    vec![exact],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Duplicate]
    );
    Ok(())
}

#[tokio::test]
async fn failed_mutation_rolls_back_prior_mutations_and_cursor() -> TestResult {
    let temp = TempDir::new()?;
    let room_id = room("!atomic:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 1,
            Vec::new(),
        ))
        .await?;
    let v1_source = event("$v1-source")?;
    store
        .ingest_inbox(&inbox_draft(
            v1_source.clone(),
            room_id.clone(),
            b"V1 source identity",
            /*at_ms*/ 2,
        )?)
        .await?;
    let split_identity = mutation(
        v1_source,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: event("$unrelated-target")?,
        },
        /*at_ms*/ 4,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 5,
                vec![split_identity],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );
    let valid_event = event("$rolled-back")?;
    let valid = mutation(
        valid_event.clone(),
        room_id,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"rollback".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    let retry = valid.clone();
    let foreign = mutation(
        event("$foreign-redaction")?,
        room("!foreign:example.test")?,
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: event("$foreign-target")?,
        },
        /*at_ms*/ 11,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 12,
                vec![valid, foreign],
            ))
            .await,
        Err(MatrixDurableError::AccessDenied)
    );
    assert!(store.inbox(&valid_event).await?.is_none());
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s1"
    );
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 13,
                    vec![retry],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    Ok(())
}

#[tokio::test]
async fn tombstone_refuses_to_orphan_an_active_dispatch() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let room_id = room("!active-dispatch:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    store
        .bind_room_thread(&RoomThreadBindingDraft {
            room_id: room_id.clone(),
            binding_revision: 1,
            generation: 1,
            project_id: room_project_idempotency_key(&agent_id, &room_id),
            thread_id: Some("thread-active".to_string()),
            changed_at_ms: 2,
        })
        .await?;
    let target = event("$active-target")?;
    let timeline = mutation(
        target.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"active".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![timeline],
        ))
        .await?;
    store
        .begin_inbox_dispatch(&target, /*begun_at_ms*/ 12)
        .await?;
    let redaction_source = event("$active-redaction")?;
    let redaction = mutation(
        redaction_source.clone(),
        room_id.clone(),
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: target.clone(),
        },
        /*at_ms*/ 13,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                Some("s1"),
                "s2",
                /*observed_at_ms*/ 14,
                vec![redaction],
            ))
            .await,
        Err(MatrixDurableError::Conflict)
    );
    assert_eq!(
        store.inbox(&target).await?.ok_or("inbox")?.state,
        InboxState::Pending
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s1"
    );
    store
        .ingest_inbox(&inbox_draft(
            redaction_source,
            room_id,
            b"failed decision left no ledger",
            /*at_ms*/ 15,
        )?)
        .await?;
    Ok(())
}

#[tokio::test]
async fn redaction_ignores_another_rooms_active_dispatch() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let active_room = room("!active-other-room:example.test")?;
    let redaction_room = room("!redaction-room:example.test")?;
    let store = store_and_room(&temp, &active_room).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: redaction_room.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 2,
        })
        .await?;
    store
        .bind_room_thread(&RoomThreadBindingDraft {
            room_id: active_room.clone(),
            binding_revision: 1,
            generation: 1,
            project_id: room_project_idempotency_key(&agent_id, &active_room),
            thread_id: Some("thread-other-room".to_string()),
            changed_at_ms: 3,
        })
        .await?;
    let target = event("$active-in-other-room")?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![mutation(
                target.clone(),
                active_room,
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: b"unrelated active dispatch".to_vec(),
                },
                /*at_ms*/ 10,
            )?],
        ))
        .await?;
    store
        .begin_inbox_dispatch(&target, /*begun_at_ms*/ 12)
        .await?;

    let redaction = mutation(
        event("$redaction-in-other-room")?,
        redaction_room,
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: target,
        },
        /*at_ms*/ 20,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 21,
                    vec![redaction],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Missing]
    );
    assert_eq!(store.pending_dispatches(/*limit*/ 10).await?.len(), 1);
    Ok(())
}

#[tokio::test]
async fn redaction_ignores_a_hidden_dispatch_from_an_old_room_fence() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let room_id = room("!active-before-rebind:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    store
        .bind_room_thread(&RoomThreadBindingDraft {
            room_id: room_id.clone(),
            binding_revision: 1,
            generation: 1,
            project_id: room_project_idempotency_key(&agent_id, &room_id),
            thread_id: Some("thread-old-fence".to_string()),
            changed_at_ms: 2,
        })
        .await?;
    let target = event("$active-before-rebind")?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![mutation(
                target.clone(),
                room_id.clone(),
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: b"old active dispatch".to_vec(),
                },
                /*at_ms*/ 10,
            )?],
        ))
        .await?;
    store
        .begin_inbox_dispatch(&target, /*begun_at_ms*/ 12)
        .await?;
    let leave = mutation(
        event("$leave-before-redaction")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    store
        .apply_sync_decision_v2(&commit(
            Some("s1"),
            "s2",
            /*observed_at_ms*/ 21,
            vec![leave],
        ))
        .await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: Some(1),
            generation: 2,
            changed_at_ms: 30,
        })
        .await?;

    let mut redaction = mutation(
        event("$redaction-after-rebind")?,
        room_id,
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: target,
        },
        /*at_ms*/ 40,
    )?;
    redaction.binding_revision = 2;
    redaction.generation = 2;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit_with_fence(
                    Some("s2"),
                    "s3",
                    /*observed_at_ms*/ 41,
                    /*checkpoint_revision*/ 1,
                    /*checkpoint_generation*/ 1,
                    vec![redaction],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert!(store.pending_dispatches(/*limit*/ 10).await?.is_empty());
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("checkpoint")?
            .next_batch,
        "s3"
    );
    Ok(())
}

#[tokio::test]
async fn room_leave_fences_an_active_dispatch_without_blocking_the_cursor() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let room_id = room("!active-room-leave:example.test")?;
    let store = store_and_room(&temp, &room_id).await?;
    let project_id = room_project_idempotency_key(&agent_id, &room_id);
    store
        .bind_room_thread(&RoomThreadBindingDraft {
            room_id: room_id.clone(),
            binding_revision: 1,
            generation: 1,
            project_id: project_id.clone(),
            thread_id: Some("thread-before-leave".to_string()),
            changed_at_ms: 2,
        })
        .await?;
    let event_id = event("$dispatch-before-leave")?;
    store
        .apply_sync_decision_v2(&commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![mutation(
                event_id.clone(),
                room_id.clone(),
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: "m.room.message".to_string(),
                    payload: b"must stop dispatching".to_vec(),
                },
                /*at_ms*/ 10,
            )?],
        ))
        .await?;
    let begun = store
        .begin_inbox_dispatch(&event_id, /*begun_at_ms*/ 12)
        .await?;
    let mut leave = mutation(
        event("$leave-with-active-dispatch")?,
        room_id,
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    leave.sender = user(AGENT_USER_ID)?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    Some("s1"),
                    "s2",
                    /*observed_at_ms*/ 21,
                    vec![leave],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert!(store.pending_dispatches(/*limit*/ 10).await?.is_empty());
    assert_eq!(
        store
            .record_inbox_queued(&InboxQueuedDraft {
                event_id,
                client_user_message_id: begun.client_user_message_id,
                project_id,
                thread_id: "thread-before-leave".to_string(),
                queued_submission_id: "queued-after-leave".to_string(),
                queued_at_ms: 22,
            })
            .await,
        Err(MatrixDurableError::AccessDenied)
    );
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("missing checkpoint")?
            .next_batch,
        "s2"
    );
    Ok(())
}

#[tokio::test]
async fn room_tombstone_is_a_logical_fence_above_the_physical_scrub_bound() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let store_layout = layout(&temp, &agent_id)?;
    let store = MatrixDurableStore::open(
        &store_layout,
        MatrixDurableConfig {
            delta_coalesce_window_ms: 150,
            max_delta_batch_bytes: 16 * 1024,
            event_capacity: 2,
        },
    )
    .await?;
    let room_id = room("!bounded-scrub:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    for index in 0..3_u64 {
        store
            .ingest_inbox(&inbox_draft(
                event(&format!("$bounded-{index}"))?,
                room_id.clone(),
                b"bounded payload",
                /*at_ms*/ 10 + index,
            )?)
            .await?;
    }
    let leave = mutation(
        event("$bounded-leave")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::RoomLeave {
            departed_user_id: user(AGENT_USER_ID)?,
        },
        /*at_ms*/ 20,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    /*expected*/ None,
                    "s1",
                    /*observed_at_ms*/ 21,
                    vec![leave],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Applied]
    );
    assert!(store.pending_inbox(/*limit*/ 10).await?.is_empty());
    assert_eq!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .ok_or("missing checkpoint")?
            .next_batch,
        "s1"
    );
    assert_eq!(
        store
            .ingest_inbox(&inbox_draft(
                event("$bounded-after-leave")?,
                room_id,
                b"must remain hidden",
                /*at_ms*/ 30,
            )?)
            .await,
        Err(MatrixDurableError::AccessDenied)
    );
    Ok(())
}

#[tokio::test]
async fn journal_saturation_is_terminal_but_preserves_the_deletion_reserve() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let store_layout = layout(&temp, &agent_id)?;
    let room_id = room("!journal-capacity:example.test")?;
    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id.clone(),
            agent_user_id: user(AGENT_USER_ID)?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    store.close().await;

    let database_path = store_layout.matrix_root().join("matrix_1.sqlite3");
    let pool = open_hostile_fixture_pool(&database_path).await?;
    sqlx::query(
        "INSERT INTO matrix_sync_decisions_v2 (
            decision_seq, operation_id, decision_kind, decision_sha256, schema_version,
            checkpoint_revision, checkpoint_generation, expected_next_batch, next_batch,
            retained_next_batch, outcome_count
         ) VALUES (61440, 'capacity-sentinel', 'cancel', ?, 2, 1, 1,
                   NULL, NULL, NULL, 0)",
    )
    .bind("0000000000000000000000000000000000000000000000000000000000000000")
    .execute(&pool)
    .await?;
    pool.close().await;

    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    let timeline = mutation(
        event("$capacity-timeline")?,
        room_id.clone(),
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"must not persist".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    assert_eq!(
        store
            .apply_sync_decision_v2(&commit(
                /*expected*/ None,
                "s1",
                /*observed_at_ms*/ 11,
                vec![timeline],
            ))
            .await?,
        MatrixSyncResultV2::CapacityExhausted {
            schema_version: 2,
            operation_id: "commit-11-s1".to_string(),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
        }
    );
    assert!(
        store
            .lookup_sync_decision_v2("commit-11-s1")
            .await?
            .is_none()
    );
    assert!(
        store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .is_none()
    );
    let redaction = mutation(
        event("$capacity-redaction")?,
        room_id,
        MatrixSyncMutationBodyV2::Redaction {
            target_event_id: event("$capacity-missing")?,
        },
        /*at_ms*/ 20,
    )?;
    assert_eq!(
        dispositions(
            store
                .apply_sync_decision_v2(&commit(
                    /*expected*/ None,
                    "s1",
                    /*observed_at_ms*/ 21,
                    vec![redaction],
                ))
                .await?,
        )?,
        vec![MatrixSyncMutationDispositionV2::Missing]
    );
    store.close().await;
    let pool = open_hostile_fixture_pool(&database_path).await?;
    assert!(
        sqlx::query(
            "INSERT INTO matrix_sync_decision_outcomes_v2 (
                decision_seq, outcome_index, source_event_id, disposition
             ) VALUES (61440, 0, '$capacity-redaction', 'missing')",
        )
        .execute(&pool)
        .await
        .is_err()
    );
    pool.close().await;
    Ok(())
}

#[tokio::test]
async fn startup_rejects_same_name_counterfeit_v2_schema_objects() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent()?;
    let store_layout = layout(&temp, &agent_id)?;
    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    store.close().await;

    let database_path = store_layout.matrix_root().join("matrix_1.sqlite3");
    let pool = open_hostile_fixture_pool(&database_path).await?;
    // Restore the exact migration SQL: Rust line continuations strip leading
    // spaces, which would change this store's intentionally exact fingerprint.
    // Pin each schema replacement to one connection and commit it atomically.
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
    let original_index_sql: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema
         WHERE type = 'index' AND name = 'matrix_sync_mutations_v2_by_tombstone'",
    )
    .fetch_one(&mut *transaction)
    .await?;
    sqlx::query("DROP INDEX matrix_sync_mutations_v2_by_tombstone")
        .execute(&mut *transaction)
        .await?;
    sqlx::query(
        "CREATE INDEX matrix_sync_mutations_v2_by_tombstone
         ON matrix_sync_mutations_v2(source_event_id)",
    )
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    pool.close().await;

    assert!(matches!(
        MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await,
        Err(MatrixDurableError::Corrupt)
    ));

    let pool = open_hostile_fixture_pool(&database_path).await?;
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("DROP INDEX matrix_sync_mutations_v2_by_tombstone")
        .execute(&mut *transaction)
        .await?;
    // Captured from the fresh, verified owner schema before any hostile write.
    sqlx::query(sqlx::AssertSqlSafe(original_index_sql))
        .execute(&mut *transaction)
        .await?;
    transaction.commit().await?;
    pool.close().await;
    let store = MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await?;
    store.close().await;

    let pool = open_hostile_fixture_pool(&database_path).await?;
    let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
    sqlx::query("DROP TRIGGER matrix_sync_mutations_v2_no_update")
        .execute(&mut *transaction)
        .await?;
    sqlx::query(
        "CREATE TRIGGER matrix_sync_mutations_v2_no_update
         BEFORE UPDATE ON matrix_sync_mutations_v2 BEGIN SELECT 1; END",
    )
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    pool.close().await;
    assert!(matches!(
        MatrixDurableStore::open(&store_layout, MatrixDurableConfig::default()).await,
        Err(MatrixDurableError::Corrupt)
    ));
    Ok(())
}

#[test]
fn v2_validation_rejects_wrong_schema() -> TestResult {
    let room_id = room("!wire:example.test")?;
    let timeline = mutation(
        event("$wire")?,
        room_id,
        MatrixSyncMutationBodyV2::Timeline {
            event_type: "m.room.message".to_string(),
            payload: b"SECRET-WIRE-PAYLOAD".to_vec(),
        },
        /*at_ms*/ 10,
    )?;
    assert!(
        commit(
            /*expected*/ None,
            "s1",
            /*observed_at_ms*/ 11,
            vec![timeline],
        )
        .validate()
        .is_ok()
    );
    assert!(
        MatrixSyncDecisionV2::Cancel {
            schema_version: 1,
            operation_id: "invalid-version".to_string(),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
            expected_next_batch: None,
        }
        .validate()
        .is_err()
    );
    Ok(())
}
