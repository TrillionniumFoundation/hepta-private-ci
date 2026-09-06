use std::sync::Mutex;

use codex_app_server_protocol::UserInput;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::client_user_message_id;
use codex_hepta_matrix_protocol::room_project_idempotency_key;
use codex_hepta_matrix_sdk::MatrixSdkError;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::RoomThreadBindingDraft;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::MatrixAdmissionMode;
use crate::MatrixRuntimeBridge;
use crate::MatrixRuntimeFuture;
use crate::MatrixSubmission;
use crate::MatrixSubmissionState;
use crate::RoomThreadBinding;

struct StartupBridge {
    agent_id: AgentId,
    trace: Arc<Mutex<Vec<String>>>,
}

impl MatrixRuntimeBridge for StartupBridge {
    fn ensure_room_thread<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        expected_thread_id: Option<&'a str>,
    ) -> MatrixRuntimeFuture<'a, RoomThreadBinding> {
        Box::pin(async move {
            self.trace.lock().expect("trace").push("ensure".to_string());
            Ok(RoomThreadBinding {
                project_id: room_project_idempotency_key(&self.agent_id, room_id),
                thread_id: expected_thread_id.expect("durable thread").to_string(),
                recovered: true,
            })
        })
    }

    fn submit_matrix_event_on_binding<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        event_id: &'a MatrixEventId,
        _input: Vec<UserInput>,
        binding: &'a RoomThreadBinding,
        _admission_mode: MatrixAdmissionMode,
    ) -> MatrixRuntimeFuture<'a, MatrixSubmission> {
        Box::pin(async move {
            self.trace
                .lock()
                .expect("trace")
                .push(format!("submit:{}", event_id.as_str()));
            Ok(MatrixSubmission {
                binding: binding.clone(),
                client_user_message_id: client_user_message_id(&self.agent_id, room_id, event_id),
                state: MatrixSubmissionState::Queued {
                    queued_submission_id: "queue-survivor".to_string(),
                },
            })
        })
    }
}

struct Fixture {
    _temp: TempDir,
    config: MatrixSidecarConfig,
    runtime: MatrixRuntime<StartupBridge>,
    trace: Arc<Mutex<Vec<String>>>,
}

impl Fixture {
    async fn new() -> anyhow::Result<Self> {
        let temp = TempDir::new()?;
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let layout = HeptaFleetRoot::parse(temp.path().canonicalize()?)?
            .layout()
            .agent(&agent_id);
        let room_id = MatrixRoomId::parse("!startup:example.test")?;
        let agent_user_id = MatrixUserId::parse("@agent:example.test")?;
        let sender = MatrixUserId::parse("@owner:example.test")?;
        let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
        store
            .bind_room(&RoomBindingDraft {
                room_id: room_id.clone(),
                agent_user_id: agent_user_id.clone(),
                expected_revision: None,
                generation: 1,
                changed_at_ms: 1,
            })
            .await?;
        store
            .bind_room_thread(&RoomThreadBindingDraft {
                room_id: room_id.clone(),
                binding_revision: 1,
                generation: 1,
                project_id: room_project_idempotency_key(&agent_id, &room_id),
                thread_id: Some("thread-startup".to_string()),
                changed_at_ms: 2,
            })
            .await?;
        for event_id in ["$deleted", "$survivor"] {
            store
                .ingest_inbox(&InboxDraft {
                    event_id: MatrixEventId::parse(event_id)?,
                    room_id: room_id.clone(),
                    sender: sender.clone(),
                    event_type: "m.room.message".to_string(),
                    payload: br#"{"msgtype":"m.text","body":"offline inbox"}"#.to_vec(),
                    binding_revision: 1,
                    generation: 1,
                    origin_server_ts_ms: 10,
                    received_at_ms: 11,
                })
                .await?;
        }
        let config = MatrixSidecarConfig {
            binding: MatrixBindingV1 {
                schema_version: MATRIX_BINDING_SCHEMA_VERSION,
                agent_id: agent_id.clone(),
                revision: 1,
                homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
                expected_mxid: agent_user_id,
                expected_device_id: MatrixDeviceId::parse("DEVICE")?,
                allowed_rooms: vec![room_id],
                allowed_senders: vec![sender],
                require_explicit_mention: false,
            },
            matrix_generation: 1,
            sync_timeline_limit: 32,
            sync_timeout: Duration::from_secs(1),
        };
        let trace = Arc::new(Mutex::new(Vec::new()));
        let runtime = MatrixRuntime::new(
            store,
            StartupBridge {
                agent_id,
                trace: Arc::clone(&trace),
            },
        );
        Ok(Self {
            _temp: temp,
            config,
            runtime,
            trace,
        })
    }
}

#[tokio::test]
async fn pending_or_failed_initial_sync_cannot_resume_or_dispatch_old_inbox() -> anyhow::Result<()>
{
    let fixture = Fixture::new().await?;
    let before = fixture
        .runtime
        .store()
        .pending_inbox(INBOX_RECOVERY_LIMIT)
        .await?;
    let (started, observed) = tokio::sync::oneshot::channel();
    let (finish, finished) = tokio::sync::oneshot::channel();
    let startup = recover_startup_after_sync(
        &fixture.runtime,
        &fixture.config,
        async {
            fixture
                .trace
                .lock()
                .expect("trace")
                .push("sync-start".to_string());
            started.send(()).expect("start observer");
            finished.await.expect("sync result")
        },
        |thread_id| {
            let trace = &fixture.trace;
            async move {
                trace.lock().expect("trace").push("resume".to_string());
                Ok(thread_id)
            }
        },
    );
    tokio::pin!(startup);
    tokio::select! {
        biased;
        result = &mut startup => panic!("startup completed before sync: {result:?}"),
        result = observed => result?,
    }
    assert_eq!(*fixture.trace.lock().expect("trace"), vec!["sync-start"]);
    assert_eq!(
        fixture
            .runtime
            .store()
            .pending_inbox(INBOX_RECOVERY_LIMIT)
            .await?,
        before
    );
    finish
        .send(Err(MatrixdRunError::Sdk(MatrixSdkError::Sync)))
        .expect("finish sync");
    assert!(matches!(
        startup.await,
        Err(MatrixdRunError::Sdk(MatrixSdkError::Sync))
    ));
    assert_eq!(*fixture.trace.lock().expect("trace"), vec!["sync-start"]);
    assert_eq!(
        fixture
            .runtime
            .store()
            .pending_inbox(INBOX_RECOVERY_LIMIT)
            .await?,
        before
    );
    Ok(())
}

#[tokio::test]
async fn initial_sync_redaction_commits_before_resume_and_inbox_recovery() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let decision = MatrixSyncDecisionV2::Commit {
        batch: MatrixSyncBatchV2 {
            schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
            operation_id: "startup-redaction".to_string(),
            checkpoint_revision: 1,
            checkpoint_generation: 1,
            expected_next_batch: None,
            next_batch: "startup-complete".to_string(),
            observed_at_ms: 20,
            mutations: vec![MatrixSyncMutationV2 {
                source_event_id: MatrixEventId::parse("$redaction")?,
                room_id: fixture.config.binding.allowed_rooms[0].clone(),
                sender: fixture.config.binding.allowed_senders[0].clone(),
                binding_revision: 1,
                generation: 1,
                origin_server_ts_ms: 19,
                received_at_ms: 20,
                body: MatrixSyncMutationBodyV2::Redaction {
                    target_event_id: MatrixEventId::parse("$deleted")?,
                },
            }],
        },
    };
    recover_startup_after_sync(
        &fixture.runtime,
        &fixture.config,
        async {
            fixture
                .runtime
                .store()
                .apply_sync_decision_v2(&decision)
                .await?;
            fixture
                .trace
                .lock()
                .expect("trace")
                .push("sync-commit".to_string());
            Ok(())
        },
        |thread_id| {
            let trace = &fixture.trace;
            async move {
                trace
                    .lock()
                    .expect("trace")
                    .push(format!("resume:{thread_id}"));
                Ok(thread_id)
            }
        },
    )
    .await?;
    assert_eq!(
        *fixture.trace.lock().expect("trace"),
        vec![
            "sync-commit",
            "resume:thread-startup",
            "ensure",
            "submit:$survivor"
        ]
    );
    let pending_ids: Vec<_> = fixture
        .runtime
        .store()
        .pending_inbox(INBOX_RECOVERY_LIMIT)
        .await?
        .into_iter()
        .map(|inbox| inbox.event_id)
        .collect();
    assert_eq!(pending_ids, vec![MatrixEventId::parse("$survivor")?]);
    assert!(
        fixture
            .runtime
            .store()
            .inbox_dispatch(&MatrixEventId::parse("$deleted")?)
            .await?
            .is_none()
    );
    assert!(
        fixture
            .runtime
            .store()
            .inbox_dispatch(&MatrixEventId::parse("$survivor")?)
            .await?
            .is_some()
    );
    Ok(())
}
