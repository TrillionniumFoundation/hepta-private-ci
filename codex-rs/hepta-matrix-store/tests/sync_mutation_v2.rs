use std::error::Error;
use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_store::ChangeKind;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixEventId;
use codex_hepta_matrix_store::MatrixRoomId;
use codex_hepta_matrix_store::MatrixUserId;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationDispositionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
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

async fn store_and_room(
    temp: &TempDir,
    room_id: &MatrixRoomId,
) -> TestResult<MatrixDurableStore> {
    let agent_id = agent()?;
    let store = MatrixDurableStore::open(&layout(temp, &agent_id)?, MatrixDurableConfig::default())
        .await?;
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
        MatrixSyncResultV2::Committed { outcomes, .. } => {
            Ok(outcomes.into_iter().map(|outcome| outcome.disposition).collect())
        }
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
    let store = MatrixDurableStore::open(
        &layout(&temp, &agent()?)?,
        MatrixDurableConfig::default(),
    )
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
    let mut cross_kind_reuse = commit(
        Some("s4"),
        "s5",
        /*observed_at_ms*/ 44,
        Vec::new(),
    );
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
