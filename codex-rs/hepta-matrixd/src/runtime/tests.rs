use std::collections::BTreeMap;
use std::fs;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::time::Duration;

use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::client_user_message_id;
use codex_hepta_matrix_sdk::IngressDisposition;
use codex_hepta_matrix_sdk::MatrixIngress;
use codex_hepta_matrix_sdk::MatrixSidecarConfig;
use codex_hepta_matrix_sdk::MatrixTimelineEvent;
use codex_hepta_matrix_store::ChangeKind;
use codex_hepta_matrix_store::InboxDisposition;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::InboxState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::ruma::events::room::message::RoomMessageEventContent;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[derive(Clone)]
struct FakeRuntimeBridge {
    agent_id: AgentId,
    state: Arc<StdMutex<FakeBridgeState>>,
}

#[derive(Default)]
struct FakeBridgeState {
    queued: BTreeMap<String, String>,
    turns: BTreeMap<String, String>,
    inputs: Vec<Vec<UserInput>>,
    admissions: usize,
    unbound_resolutions: usize,
}

impl FakeRuntimeBridge {
    fn new(agent_id: AgentId) -> Self {
        Self {
            agent_id,
            state: Arc::new(StdMutex::new(FakeBridgeState::default())),
        }
    }

    fn admissions(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .admissions
    }

    fn unbound_resolutions(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .unbound_resolutions
    }

    fn admit(&self, client_id: &str, turn_id: &str) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.queued.remove(client_id);
        state
            .turns
            .insert(client_id.to_string(), turn_id.to_string());
    }

    fn lose_core_record(&self, client_id: &str) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.queued.remove(client_id);
        state.turns.remove(client_id);
    }

    fn binding(&self, _room_id: &MatrixRoomId, thread_id: &str) -> RoomThreadBinding {
        RoomThreadBinding {
            project_id: "app-server-project-runtime-room".to_string(),
            thread_id: thread_id.to_string(),
            recovered: true,
        }
    }
}

impl MatrixRuntimeBridge for FakeRuntimeBridge {
    fn ensure_room_thread<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        expected_thread_id: Option<&'a str>,
    ) -> MatrixRuntimeFuture<'a, RoomThreadBinding> {
        Box::pin(async move {
            let thread_id = match expected_thread_id {
                Some(thread_id) => thread_id.to_string(),
                None => {
                    let mut state = self
                        .state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner);
                    state.unbound_resolutions += 1;
                    if state.unbound_resolutions == 1 {
                        "thread-matrix-room".to_string()
                    } else {
                        format!("replacement-thread-{}", state.unbound_resolutions)
                    }
                }
            };
            Ok(self.binding(room_id, &thread_id))
        })
    }

    fn submit_matrix_event_on_binding<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        event_id: &'a MatrixEventId,
        input: Vec<UserInput>,
        binding: &'a RoomThreadBinding,
        admission_mode: MatrixAdmissionMode,
    ) -> MatrixRuntimeFuture<'a, MatrixSubmission> {
        Box::pin(async move {
            if binding != &self.binding(room_id, &binding.thread_id) {
                return Err(MatrixBridgeError::Protocol(
                    "fake received a drifting binding".to_string(),
                ));
            }
            let client_id = client_user_message_id(&self.agent_id, room_id, event_id);
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let submission_state = if let Some(turn_id) = state.turns.get(&client_id) {
                MatrixSubmissionState::ReconciledTurn {
                    turn_id: turn_id.clone(),
                }
            } else if let Some(queued_submission_id) = state.queued.get(&client_id) {
                MatrixSubmissionState::ReconciledQueued {
                    queued_submission_id: queued_submission_id.clone(),
                }
            } else if admission_mode == MatrixAdmissionMode::AllowIfAbsent {
                state.admissions += 1;
                state.inputs.push(input);
                let queued_submission_id = format!("queue-{}", state.admissions);
                state
                    .queued
                    .insert(client_id.clone(), queued_submission_id.clone());
                MatrixSubmissionState::Queued {
                    queued_submission_id,
                }
            } else {
                return Err(MatrixBridgeError::Protocol(
                    "fake Core durable record is missing".to_string(),
                ));
            };
            Ok(MatrixSubmission {
                binding: binding.clone(),
                client_user_message_id: client_id,
                state: submission_state,
            })
        })
    }
}

fn agent_id() -> AgentId {
    AgentId::parse(AGENT_ID).expect("agent id")
}

fn room_id() -> MatrixRoomId {
    MatrixRoomId::parse("!runtime:example.test").expect("room id")
}

fn event_id(value: &str) -> MatrixEventId {
    MatrixEventId::parse(value).expect("event id")
}

fn layout(temp: &TempDir, agent_id: &AgentId) -> HeptaAgentLayout {
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root).expect("fleet root");
    let canonical = root.canonicalize().expect("canonical fleet root");
    HeptaFleetRoot::parse(canonical)
        .expect("fleet root")
        .layout()
        .agent(agent_id)
}

async fn open_bound_store(
    layout: &HeptaAgentLayout,
) -> Result<MatrixDurableStore, MatrixRuntimeError> {
    let store = MatrixDurableStore::open(layout, MatrixDurableConfig::default()).await?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room_id(),
            agent_user_id: MatrixUserId::parse("@agent:example.test").expect("agent mxid"),
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    Ok(store)
}

fn text_inbox(event_id: MatrixEventId, payload: &[u8]) -> InboxDraft {
    InboxDraft {
        event_id,
        room_id: room_id(),
        sender: MatrixUserId::parse("@owner:example.test").expect("owner mxid"),
        event_type: "m.room.message".to_string(),
        payload: payload.to_vec(),
        binding_revision: 1,
        generation: 1,
        origin_server_ts_ms: 10,
        received_at_ms: 11,
    }
}

fn notification(notification: ServerNotification) -> AppServerEvent {
    AppServerEvent::ServerNotification(Box::new(notification))
}

fn delta_event(delta: &str) -> AppServerEvent {
    notification(ServerNotification::AgentMessageDelta(
        AgentMessageDeltaNotification {
            thread_id: "thread-matrix-room".to_string(),
            turn_id: "turn-1".to_string(),
            item_id: "agent-message-1".to_string(),
            delta: delta.to_string(),
        },
    ))
}

fn final_event(text: &str) -> AppServerEvent {
    notification(ServerNotification::ItemCompleted(
        ItemCompletedNotification {
            item: ThreadItem::AgentMessage {
                id: "agent-message-1".to_string(),
                text: text.to_string(),
                phase: None,
                memory_citation: None,
                delivery: None,
            },
            thread_id: "thread-matrix-room".to_string(),
            turn_id: "turn-1".to_string(),
            completed_at_ms: 50,
        },
    ))
}

fn completed_event() -> AppServerEvent {
    notification(ServerNotification::TurnCompleted(
        TurnCompletedNotification {
            thread_id: "thread-matrix-room".to_string(),
            turn: Turn {
                id: "turn-1".to_string(),
                items: Vec::new(),
                items_view: TurnItemsView::Full,
                status: TurnStatus::Completed,
                error: None,
                started_at: Some(1),
                completed_at: Some(2),
                duration_ms: Some(1_000),
            },
        },
    ))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn crash_restart_and_duplicate_event_admit_core_exactly_once() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let agent_id = agent_id();
    let layout = layout(&temp, &agent_id);
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id.clone());
    let event_id = event_id("$durable-event");
    let draft = text_inbox(
        event_id.clone(),
        br#"{"msgtype":"m.text","body":"hello from Matrix"}"#,
    );
    assert!(matches!(
        store.ingest_inbox(&draft).await?,
        InboxDisposition::Accepted(_)
    ));
    let resume_cursor = store.snapshot(12, 10).await?.cursor;
    let first_runtime = MatrixRuntime::new(store, fake.clone());
    assert!(matches!(
        first_runtime.process_event(&event_id, 20).await?,
        MatrixDispatchOutcome::Queued { .. }
    ));
    assert_eq!(fake.admissions(), 1);
    assert_eq!(fake.unbound_resolutions(), 1);
    first_runtime.store().close().await;
    drop(first_runtime);

    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let restarted = MatrixRuntime::new(reopened, fake.clone());
    let queued_recovery = restarted.recover_pending(10, 30).await?;
    assert!(matches!(
        queued_recovery.outcomes.as_slice(),
        [MatrixDispatchOutcome::Queued { .. }]
    ));
    assert_eq!(fake.admissions(), 1);
    assert_eq!(fake.unbound_resolutions(), 1);

    let client_id = client_user_message_id(&agent_id, &room_id(), &event_id);
    fake.admit(&client_id, "turn-1");
    let admitted_recovery = restarted.recover_pending(10, 40).await?;
    assert!(matches!(
        admitted_recovery.outcomes.as_slice(),
        [MatrixDispatchOutcome::Admitted { .. }]
    ));
    assert_eq!(fake.admissions(), 1);
    assert!(matches!(
        restarted.store().ingest_inbox(&draft).await?,
        InboxDisposition::Duplicate(_)
    ));

    assert!(matches!(
        restarted
            .project_app_server_event(&delta_event("hello "), 50)
            .await?,
        MatrixEventProjection::Stored {
            kind: OutboxKind::TextDelta,
            ..
        }
    ));
    assert!(matches!(
        restarted
            .project_app_server_event(&delta_event("world"), 60)
            .await?,
        MatrixEventProjection::Stored {
            kind: OutboxKind::TextDelta,
            disposition: OutboxDisposition::Coalesced(_),
        }
    ));
    assert!(matches!(
        restarted
            .project_app_server_event(&final_event("hello world"), 70)
            .await?,
        MatrixEventProjection::Stored {
            kind: OutboxKind::Final,
            ..
        }
    ));
    let completed = restarted
        .project_app_server_event(&completed_event(), 80)
        .await?;
    assert!(matches!(
        completed,
        MatrixEventProjection::TurnCompleted { .. }
    ));
    assert!(matches!(
        restarted.process_event(&event_id, 90).await?,
        MatrixDispatchOutcome::Completed { .. }
    ));
    assert_eq!(fake.admissions(), 1);

    let inbox = restarted
        .store()
        .inbox(&event_id)
        .await?
        .expect("durable inbox");
    assert_eq!(inbox.state, InboxState::Processed);
    let outbox = restarted.store().pending_outbox(10).await?;
    assert_eq!(outbox.len(), 2);
    assert_eq!(outbox[0].kind, OutboxKind::Final);
    assert_eq!(outbox[0].payload, b"hello world");
    assert_eq!(outbox[0].logical_txn_count, 3);
    assert_eq!(outbox[1].kind, OutboxKind::Terminal);

    assert!(matches!(
        restarted
            .project_app_server_event(&final_event("hello world"), 100)
            .await?,
        MatrixEventProjection::Stored {
            disposition: OutboxDisposition::Duplicate(_),
            ..
        }
    ));
    assert_eq!(restarted.store().pending_outbox(10).await?.len(), 2);

    let claimed_root = restarted.store().claim_outbox(101, 30, 1).await?;
    assert_eq!(claimed_root.len(), 1);
    assert_eq!(claimed_root[0].kind, OutboxKind::Final);
    let root_event_id = MatrixEventId::parse("$matrix-agent-message-root").expect("root event id");
    restarted
        .store()
        .mark_outbox_sent(
            &claimed_root[0].stable_txn_id,
            claimed_root[0].attempts,
            &root_event_id,
            102,
        )
        .await?;

    assert!(matches!(
        restarted
            .project_app_server_event(&final_event("hello corrected world"), 103)
            .await?,
        MatrixEventProjection::Stored {
            kind: OutboxKind::Final,
            disposition: OutboxDisposition::Enqueued(_),
        }
    ));
    let claimed_after_edit = restarted.store().claim_outbox(103, 30, 10).await?;
    let corrected = claimed_after_edit
        .iter()
        .find(|record| record.kind == OutboxKind::Final)
        .expect("corrected final claim");
    let logical_stream = outbox_id(
        &agent_id,
        &room_id(),
        "thread-matrix-room",
        "turn-1",
        "agent-message-1",
        "agent_message",
    );
    assert_eq!(corrected.payload, b"hello corrected world");
    assert_eq!(corrected.stable_txn_id, transaction_id(&logical_stream, 4)?);
    assert_eq!(corrected.replaces_event_id.as_ref(), Some(&root_event_id));

    assert!(matches!(
        restarted
            .project_app_server_event(&completed_event(), 110)
            .await?,
        MatrixEventProjection::TurnCompleted {
            disposition: OutboxDisposition::Duplicate(_),
            ..
        }
    ));
    let changes = restarted.store().read_changes(resume_cursor, 64).await?;
    assert!(!changes.gap);
    assert_eq!(changes.next_cursor, changes.latest_cursor);
    let kinds = changes
        .events
        .into_iter()
        .map(|event| event.kind)
        .collect::<Vec<_>>();
    for required in [
        ChangeKind::InboxDispatchBegun,
        ChangeKind::InboxDispatchQueued,
        ChangeKind::InboxDispatchAdmitted,
        ChangeKind::OutboxEnqueued,
        ChangeKind::OutboxCoalesced,
        ChangeKind::InboxProcessed,
    ] {
        assert!(
            kinds.contains(&required),
            "missing resumed change {required:?}"
        );
    }
    restarted.store().close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn sdk_mentioned_text_reaches_core_exactly_once() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let agent_id = agent_id();
    let layout = layout(&temp, &agent_id);
    let store = open_bound_store(&layout).await?;
    let agent_mxid = MatrixUserId::parse("@agent:example.test")?;
    let owner_mxid = MatrixUserId::parse("@owner:example.test")?;
    let ingress = MatrixIngress::new(
        MatrixSidecarConfig {
            binding: MatrixBindingV1 {
                schema_version: MATRIX_BINDING_SCHEMA_VERSION,
                agent_id: agent_id.clone(),
                revision: 1,
                homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
                expected_mxid: agent_mxid.clone(),
                expected_device_id: MatrixDeviceId::parse("DEVICE")?,
                allowed_rooms: vec![room_id()],
                allowed_senders: vec![owner_mxid.clone()],
                require_explicit_mention: true,
            },
            matrix_generation: 1,
            sync_timeline_limit: 32,
            sync_timeout: Duration::from_secs(1),
        },
        store.clone(),
    );
    let content: RoomMessageEventContent = serde_json::from_value(serde_json::json!({
        "msgtype": "m.text",
        "body": "hello from Matrix",
        "m.mentions": { "user_ids": [agent_mxid.as_str()], "room": true }
    }))?;
    let event_id = event_id("$sdk-mention");
    let event = MatrixTimelineEvent {
        event_id: event_id.clone(),
        room_id: room_id(),
        sender: owner_mxid,
        event_type: "m.room.message".to_string(),
        // Match the SDK adapter's serialization of RoomMessageEventContent.
        payload: serde_json::to_vec(&serde_json::to_value(content)?)?,
        mentioned_user_ids: vec![agent_mxid],
        origin_server_ts_ms: 10,
        received_at_ms: 11,
    };
    assert_eq!(
        ingress.ingest(event.clone()).await?,
        IngressDisposition::Accepted
    );
    let fake = FakeRuntimeBridge::new(agent_id);
    let runtime = MatrixRuntime::new(store, fake.clone());
    assert!(matches!(
        runtime.process_event(&event_id, /*now_ms*/ 20).await?,
        MatrixDispatchOutcome::Queued { .. }
    ));
    assert_eq!(ingress.ingest(event).await?, IngressDisposition::Duplicate);
    assert!(matches!(
        runtime.process_event(&event_id, /*now_ms*/ 30).await?,
        MatrixDispatchOutcome::Queued { .. }
    ));
    assert_eq!(fake.admissions(), 1);
    assert_eq!(
        fake.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .inputs,
        vec![vec![UserInput::Text {
            text: "hello from Matrix".to_string(),
            text_elements: Vec::new(),
        }]]
    );
    runtime.store().close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unsupported_room_messages_fail_closed_without_core_admission() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let agent_id = agent_id();
    let layout = layout(&temp, &agent_id);
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id);
    let runtime = MatrixRuntime::new(store, fake.clone());

    for (index, payload) in [
        br#"{"msgtype":"m.notice","body":"do not dispatch"}"#.as_slice(),
        br#"{"msgtype":"m.text","body":"hidden","formatted_body":"<b>hidden</b>"}"#.as_slice(),
        br#"{"msgtype":"m.text","body":"hidden","m.mentions":{"user_ids":["@agent:example.test"],"critical":true}}"#.as_slice(),
        br#"{"msgtype":"m.text","body":"hidden","m.mentions":{"user_ids":["invalid"]}}"#.as_slice(),
        br#"{"msgtype":"m.text","body":"hidden","m.mentions":{"room":"true"}}"#.as_slice(),
        b"not-json".as_slice(),
    ]
    .into_iter()
    .enumerate()
    {
        let event_id = event_id(&format!("$unsupported-{index}"));
        runtime
            .store()
            .ingest_inbox(&text_inbox(event_id.clone(), payload))
            .await?;
        assert!(matches!(
            runtime.process_event(&event_id, 20).await?,
            MatrixDispatchOutcome::IgnoredUnsupported { .. }
        ));
        assert!(runtime.store().inbox_dispatch(&event_id).await?.is_none());
    }
    assert_eq!(fake.admissions(), 0);
    assert!(matches!(
        runtime
            .project_app_server_event(&AppServerEvent::Lagged { skipped: 2 }, 30)
            .await,
        Err(MatrixRuntimeError::Protocol(message)) if message.contains("snapshot/resync")
    ));
    runtime.store().close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_recovery_never_recreates_a_missing_core_record() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let agent_id = agent_id();
    let layout = layout(&temp, &agent_id);
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent_id.clone());
    let event_id = event_id("$lost-core-record");
    store
        .ingest_inbox(&text_inbox(
            event_id.clone(),
            br#"{"msgtype":"m.text","body":"once only"}"#,
        ))
        .await?;
    let runtime = MatrixRuntime::new(store, fake.clone());
    runtime.process_event(&event_id, 20).await?;
    let client_id = client_user_message_id(&agent_id, &room_id(), &event_id);
    fake.lose_core_record(&client_id);

    let error = runtime
        .recover_pending(10, 30)
        .await
        .expect_err("queued dispatch must not create a replacement Core record");
    assert!(matches!(
        error,
        MatrixRuntimeError::Bridge(MatrixBridgeError::Protocol(_))
    ));
    assert_eq!(fake.admissions(), 1);
    runtime.store().close().await;
    Ok(())
}
