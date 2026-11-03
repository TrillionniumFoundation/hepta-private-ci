use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_history::RolloutItem;
use codex_protocol::ThreadId;
use codex_protocol::items::TurnItem;
use codex_protocol::items::UserMessageItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ItemCompletedEvent;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::protocol::ThreadMemoryMode;
use codex_protocol::turn_input::TurnInput;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_thread_store::LocalQueueStore;
use codex_thread_store::LocalThreadStore;
use codex_thread_store::LocalThreadStoreConfig;
use codex_thread_store::LoadThreadHistoryParams;
use codex_thread_store::NativeCheckpointPermit;
use codex_thread_store::QueueStore;
use codex_thread_store::QueuedClientBindingFinalizeMode;
use codex_thread_store::QueuedClientBindingFinalizeOutcome;
use codex_thread_store::QueuedClientBindingReserveOutcome;
use codex_thread_store::ResumeThreadParams;
use codex_thread_store::StoredNativeCheckpoint;
use codex_thread_store::ThreadPersistenceMetadata;
use codex_thread_store::ThreadStoreError;
use codex_thread_store::ThreadStoreFuture;
use codex_thread_store::ThreadStore;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::sync::RwLock;

use super::*;
use crate::native_turn_checkpoint::NativeQueueBindingV1;
use crate::native_turn_queue::NativeQueueDispatch;

// Only host admission is a fixture. Storage, history, process dispatch locks,
// original queue leases, CAS, shutdown and reopen use their production owners.
struct HostFixture {
    binding: NativeCheckpointBinding,
    current: Arc<RwLock<bool>>,
    pause_commit: AtomicBool,
    acquired: Notify,
    resume_commit: Notify,
}

impl NativeCheckpointCurrentness for HostFixture {
    fn acquire<'a>(&'a self, binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async move {
            let guard = self.current.clone().read_owned().await;
            if binding != &self.binding || !*guard {
                return Err(ThreadStoreError::Conflict { message: "fixture host revoked original owner".to_owned() });
            }
            if self.pause_commit.swap(false, Ordering::SeqCst) {
                self.acquired.notify_one();
                self.resume_commit.notified().await;
            }
            Ok(NativeCheckpointPermit::hold(guard))
        })
    }
}

impl NativeTurnAdmission for HostFixture {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        ensure!(binding.thread_id.as_str() == self.binding.thread_id.to_string()
            && binding.turn_id.as_str() == self.binding.turn_id
            && binding.operation_id.as_str() == self.binding.operation_id
            && binding.generation.get() == self.binding.generation
            && *self.current.read().await, "fixture host no longer current");
        Ok(())
    }

    async fn admit_model(&self, binding: &TurnBinding, _sequence: usize, exact_body: &[u8]) -> Result<ModelRequest> {
        self.verify_current(binding).await?;
        Ok(ModelRequest { operation_id: "model:original".to_owned(), body: exact_body.to_vec() })
    }

    async fn admit_tool(&self, _binding: &TurnBinding, _call: &ToolCall) -> Result<ToolAdmission> {
        anyhow::bail!("storage fixture does not admit tools")
    }
}

struct Fixture {
    _home: TempDir,
    config: LocalThreadStoreConfig,
    state_db: Arc<StateRuntime>,
    live: LiveThread,
    resume: ResumeThreadParams,
    anchor: NativeTurnAnchorV1,
    host: Arc<HostFixture>,
    queue: Arc<LocalQueueStore>,
}

impl Fixture {
    async fn new() -> Result<Self> {
        let home = TempDir::new().context("home")?;
        let thread_id = ThreadId::new();
        let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(home.path().join("state")).context("absolute state home")?);
        let state_db = StateRuntime::init(sqlite.clone(), "test-provider".to_owned()).await.context("real state owner")?;
        let config = LocalThreadStoreConfig { codex_home: home.path().to_path_buf(), sqlite, default_model_provider_id: "test-provider".to_owned() };
        let directory = home.path().join("sessions/2025/01/03");
        std::fs::create_dir_all(&directory).context("sessions")?;
        let path = directory.join(format!("rollout-2025-01-03T00-00-00-{thread_id}.jsonl"));
        let meta = json!({"ordinal":0,"timestamp":"2025-01-03T00:00:00Z","type":"session_meta","payload":{
            "session_id":thread_id,"id":thread_id,"timestamp":"2025-01-03T00:00:00Z",
            "cwd":home.path(),"originator":"test_originator","cli_version":"test_version",
            "source":"cli","model_provider":"test-provider","history_mode":"paginated"}});
        std::fs::write(&path, format!("{meta}\n")).context("real rollout")?;
        let resume = ResumeThreadParams {
            thread_id, rollout_path: Some(path), history: None, include_archived: false,
            metadata: ThreadPersistenceMetadata { cwd: Some(home.path().to_path_buf()), model_provider:"test-provider".to_owned(), memory_mode:ThreadMemoryMode::Disabled },
        };
        let store = Arc::new(LocalThreadStore::new(config.clone(), Some(state_db.clone())));
        let mut initial_resume = resume.clone();
        initial_resume.history = Some(store.load_latest_model_context(LoadThreadHistoryParams {
            thread_id, include_archived: false,
        }).await.context("original paginated resume context")?.items.into());
        let live = LiveThread::resume(store, ThreadHistoryMode::Paginated, initial_resume).await.context("live original owner")?;
        // These hashes are fixture provenance. The production adapter must
        // obtain its semantic boundary from the original history owner.
        let anchor: NativeTurnAnchorV1 = serde_json::from_value(json!({
            "checkpoint":{"thread_id":thread_id,"turn_id":"turn:original","operation_id":"operation:original","generation":7,"lease_id":"lease:original"},
            "recovery":{"turn_id":"turn:original","generation":3,"fingerprint_sha256":Digest32::of_bytes(b"semantic request").to_string(),
                "history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"model history").to_string()},
                "replay":{"history_boundary":{"item_count":1,"prefix_sha256":Digest32::of_bytes(b"model history").to_string()},
                    "turn_context_sha256":Digest32::of_bytes(b"turn context").to_string(),"start":{},"environments":[]}},"queue":null
        })).context("fixture anchor")?;
        live.append_items(&[RolloutItem::TurnRecoveryRequestBinding(anchor.recovery.clone())]).await.context("original history record")?;
        live.flush().await.context("history flush")?;
        let host = Arc::new(HostFixture { binding:anchor.checkpoint.clone(), current:Arc::new(RwLock::new(true)), pause_commit:AtomicBool::new(false), acquired:Notify::new(), resume_commit:Notify::new() });
        let queue = Arc::new(LocalQueueStore::new(state_db.clone()));
        Ok(Self { _home:home, config, state_db, live, resume, anchor, host, queue })
    }

    fn initial(&self) -> Result<TurnState> {
        Ok(TurnState::new(self.anchor.turn_binding().context("binding")?, "original input".to_owned()))
    }

    async fn owner(&self) -> Result<NativeThreadTurnOwner<HostFixture>> {
        NativeThreadTurnOwner::create(self.live.clone(), self.anchor.clone(), self.host.clone(), self.host.clone(), &self.initial()?).await.context("durable native owner")
    }

    async fn reopen(&self) -> Result<LiveThread> {
        self.live.shutdown().await.context("shutdown original writer")?;
        let store = Arc::new(LocalThreadStore::new(self.config.clone(), Some(self.state_db.clone())));
        let mut resume = self.resume.clone();
        resume.history = Some(store.load_latest_model_context(LoadThreadHistoryParams {
            thread_id: resume.thread_id, include_archived: false,
        }).await.context("original paginated recovery context")?.items.into());
        LiveThread::resume(store, ThreadHistoryMode::Paginated, resume).await.context("new writer epoch")
    }

    async fn head(&self, owner: &NativeThreadTurnOwner<HostFixture>) -> Result<StoredNativeCheckpoint> {
        let NativeCheckpointLoad::Present(head) = owner.live_thread.load_native_checkpoint(&owner.session).await.context("read checkpoint")? else {
            anyhow::bail!("checkpoint absent");
        };
        Ok(head)
    }

    async fn enqueue(&mut self) -> Result<(String, Vec<UserInput>)> {
        let content = vec![UserInput::Text { text:"original input".to_owned(), text_elements:Vec::new() }];
        let input = TurnInput::UserInput { content:content.clone(), client_id:Some("client:original".to_owned()) };
        let payload = serde_json::to_string(&input).context("input")?;
        let digest = user_input_payload_sha256(&content).context("canonical original digest")?;
        let thread_id = self.anchor.checkpoint.thread_id;
        let QueuedClientBindingReserveOutcome::Reserved(lease) = self.queue.reserve_client_binding(thread_id, "client:original".to_owned(), digest.clone(), payload.clone()).await.context("reserve original queue input")? else {
            anyhow::bail!("fresh queue fixture was already bound");
        };
        let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = self.queue.finalize_client_binding(thread_id, "client:original".to_owned(), digest.clone(), payload.clone(), lease, QueuedClientBindingFinalizeMode::AllowIfAbsent, None).await.context("original queue commit")? else {
            anyhow::bail!("input not queued");
        };
        self.anchor.queue = Some(NativeQueueBindingV1 { client_id:"client:original".to_owned(), queued_item_id:record.id, payload_sha256:digest });
        let item = RolloutItem::EventMsg(EventMsg::ItemCompleted(ItemCompletedEvent {
            thread_id, turn_id:self.anchor.checkpoint.turn_id.clone(),
            item:TurnItem::UserMessage(UserMessageItem { id:"item:original".to_owned(), client_id:Some("client:original".to_owned()), content:content.clone() }),
            started_at_ms:Some(1), completed_at_ms:2,
        }));
        self.live.append_items(&[item]).await.context("original typed user history")?;
        self.live.flush().await.context("flush exact input")?;
        Ok((payload, content))
    }
}

#[tokio::test]
async fn real_store_reopen_preserves_uncertain_model_and_original_binding() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = fixture.owner().await?;
    let mut state = fixture.initial()?;
    state.model_calls = 1;
    state.pending_model = Some(ModelRequest { operation_id:"model:original".to_owned(), body:b"{ \"input\": [\"original\"] }".to_vec() });
    owner.checkpoint(&state).await.expect("admission precedes provider entry");
    state.provider_response_id = Some("resp_original".to_owned());
    state.cancelled = true;
    state.last_error = Some("transport interrupted".to_owned());
    owner.checkpoint(&state).await.expect("original pending bytes durable");
    let expected = fixture.head(&owner).await?;
    let reopened = fixture.reopen().await?;
    let (recovered, actual) = NativeThreadTurnOwner::recover(reopened, fixture.anchor.checkpoint.clone(), fixture.host.clone(), fixture.host.clone()).await.expect("recover same operation");
    assert_eq!(encode(&fixture.anchor, &actual).expect("recovered payload"), expected.state.payload);
    assert_eq!(fixture.head(&recovered).await?, expected);
    assert!(owner.checkpoint(&state).await.is_err());
    recovered.live_thread.shutdown().await.expect("close reopened writer");
    Ok(())
}

#[tokio::test]
async fn cancelled_waiter_reconciles_one_exact_real_store_commit() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = Arc::new(fixture.owner().await?);
    let mut pending = fixture.initial()?;
    pending.model_calls = 1;
    pending.pending_model = Some(ModelRequest { operation_id:"model:uncertain".to_owned(), body:b"{}".to_vec() });
    fixture.host.pause_commit.store(true, Ordering::SeqCst);
    let waiter_owner = owner.clone();
    let waiter_state = pending.clone();
    let waiter = tokio::spawn(async move { waiter_owner.checkpoint(&waiter_state).await });
    fixture.host.acquired.notified().await;
    waiter.abort();
    assert!(waiter.await.expect_err("cancelled waiter").is_cancelled());
    fixture.host.resume_commit.notify_one();
    owner.checkpoint(&pending).await.expect("reconcile lost acknowledgement");
    let head = fixture.head(&owner).await?;
    assert_eq!((head.version.revision, head.state.payload), (2, encode(&fixture.anchor, &pending).expect("exact pending payload")));
    fixture.live.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn unrelated_head_advance_is_never_adopted_or_overwritten() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = fixture.owner().await?;
    let before = fixture.head(&owner).await?;
    let mut external = fixture.initial()?;
    external.last_error = Some("different writer observation".to_owned());
    let committed = fixture.live.commit_native_checkpoint(&owner.session, NativeCheckpointExpected::Version(before.version), NativeCheckpointState {
        binding:fixture.anchor.checkpoint.clone(), payload:encode(&fixture.anchor, &external).expect("external payload"),
    }).await.expect("independent CAS");
    assert!(owner.checkpoint(&fixture.initial()?).await.is_err());
    assert_eq!(fixture.head(&owner).await?, committed);
    fixture.live.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn revoked_owner_and_duplicate_history_are_held() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = fixture.owner().await?;
    let before = fixture.head(&owner).await?;
    *fixture.host.current.write().await = false;
    let mut changed = fixture.initial()?;
    changed.cancelled = true;
    assert!(owner.checkpoint(&changed).await.is_err());
    assert_eq!(fixture.head(&owner).await?, before);
    *fixture.host.current.write().await = true;
    // A later resumable compaction suffix can contain one apparently valid
    // binding while hiding earlier duplicates. Identity verification must scan
    // the complete canonical file, not accept this model-context projection.
    let cutoff_turn = "fixture:compaction-cutoff";
    fixture.live.append_items(&[
        RolloutItem::TurnRecoveryRequestBinding(fixture.anchor.recovery.clone()),
        RolloutItem::EventMsg(EventMsg::TurnStarted(codex_protocol::protocol::TurnStartedEvent {
            turn_id: cutoff_turn.to_owned(), trace_id: None, started_at: None,
            model_context_window: Some(128_000), collaboration_mode_kind: Default::default(),
        })),
        RolloutItem::EventMsg(EventMsg::ItemCompleted(ItemCompletedEvent {
            thread_id: fixture.anchor.checkpoint.thread_id, turn_id: cutoff_turn.to_owned(),
            item: TurnItem::UserMessage(UserMessageItem { id: "fixture:cutoff-user".to_owned(),
                client_id: None, content: Vec::new() }), started_at_ms: Some(1), completed_at_ms: 2,
        })),
        RolloutItem::TurnContext(serde_json::from_value(json!({
            "turn_id":cutoff_turn, "cwd":fixture._home.path(), "approval_policy":"never",
            "sandbox_policy":codex_protocol::protocol::SandboxPolicy::new_read_only_policy(),
            "model":"fixture-model", "summary":"auto"
        })).expect("real typed turn context")),
        RolloutItem::Compacted(codex_history::CompactedItem {
            message: "fixture resumable suffix".to_owned(), replacement_history: Some(Vec::new()),
            mcp_resource_origins: None, window_number: Some(1), first_window_id: None,
            previous_window_id: None, window_id: None,
        }),
        RolloutItem::TurnRecoveryRequestBinding(fixture.anchor.recovery.clone()),
    ]).await.expect("duplicate fixture corruption around a real compaction cutoff");
    fixture.live.flush().await.expect("flush corruption");
    let store = LocalThreadStore::new(fixture.config.clone(), Some(fixture.state_db.clone()));
    let suffix = store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: fixture.anchor.checkpoint.thread_id, include_archived: false,
    }).await.expect("existing paginated model-context reader");
    assert_eq!(suffix.items.iter().filter(|item| matches!(item,
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding == &fixture.anchor.recovery)).count(), 1,
        "the bounded resume suffix deliberately hides the earlier duplicate");
    assert!(owner.confirm_durable().await.is_err());
    let reopened = fixture.reopen().await?;
    assert!(NativeThreadTurnOwner::recover(reopened.clone(), fixture.anchor.checkpoint.clone(), fixture.host.clone(), fixture.host.clone()).await.is_err());
    reopened.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn original_queue_completes_only_after_exact_native_input_is_durable() -> Result<()> {
    let mut fixture = Fixture::new().await?;
    let (payload, _) = fixture.enqueue().await?;
    let binding = fixture.anchor.queue.clone().expect("queue binding");
    let mut wrong = binding.clone();
    wrong.payload_sha256 = Digest32::of_bytes(b"another input").to_string();
    assert!(NativeQueueDispatch::claim(fixture.queue.clone(), fixture.anchor.checkpoint.thread_id, wrong, "dispatch:wrong".to_owned(), 1, 100).await.is_err());
    let mut dispatch = NativeQueueDispatch::claim(fixture.queue.clone(), fixture.anchor.checkpoint.thread_id, binding.clone(), "dispatch:original".to_owned(), 1, 100).await.expect("original process lock and lease");
    assert_eq!(dispatch.payload(), payload);
    dispatch.authorize(2, 101).await.expect("original pre-admission CAS");
    let owner = fixture.owner().await?;
    dispatch.complete(&owner).await.expect("complete original queue transaction");
    assert!(fixture.queue.list_page(fixture.anchor.checkpoint.thread_id, 0, 100).await.expect("queue").is_empty());
    assert_eq!(fixture.queue.reserve_client_binding(fixture.anchor.checkpoint.thread_id, binding.client_id, binding.payload_sha256, payload).await.expect("existing binding observation"),
        QueuedClientBindingReserveOutcome::Persisted { turn_id:fixture.anchor.checkpoint.turn_id.clone() });
    fixture.live.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn restart_settles_expired_original_queue_without_readmitting_input() -> Result<()> {
    let mut fixture = Fixture::new().await?;
    fixture.enqueue().await?;
    let dispatch = NativeQueueDispatch::claim(fixture.queue.clone(), fixture.anchor.checkpoint.thread_id, fixture.anchor.queue.clone().expect("queue binding"), "dispatch:crashed".to_owned(), 1, 10).await.expect("original claim");
    let owner = fixture.owner().await?;
    let head = fixture.head(&owner).await?;
    drop(dispatch);
    let reopened = fixture.reopen().await?;
    let (recovered, state) = NativeThreadTurnOwner::recover(reopened, fixture.anchor.checkpoint.clone(), fixture.host.clone(), fixture.host.clone()).await.expect("original pending recovery");
    NativeQueueDispatch::reconcile_completed(fixture.queue.clone(), &recovered, "dispatch:successor".to_owned(), 11, 30).await.expect("settle expired original row");
    NativeQueueDispatch::reconcile_completed(fixture.queue.clone(), &recovered, "dispatch:successor".to_owned(), 12, 31).await.expect("observe already persisted binding");
    assert_eq!(fixture.head(&recovered).await?, head);
    assert_eq!((state.model_calls, state.tool_calls), (0, 0));
    assert!(fixture.queue.list_page(fixture.anchor.checkpoint.thread_id, 0, 100).await.expect("queue").is_empty());
    recovered.live_thread.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn reading_original_recovery_correlation_never_writes_or_reauthorizes() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = fixture.owner().await?;
    let before = fixture.head(&owner).await?;
    *fixture.host.current.write().await = false;
    let (anchor, state) = NativeThreadTurnOwner::<HostFixture>::read_original(
        fixture.live.clone(), fixture.anchor.checkpoint.clone(), fixture.host.clone(),
    ).await.expect("observation without fresh authority");
    assert_eq!(anchor, fixture.anchor);
    assert_eq!(encode(&anchor, &state).expect("original state"), before.state.payload);
    assert_eq!(fixture.head(&owner).await?, before);
    assert!(owner.checkpoint(&state).await.is_err());
    fixture.live.shutdown().await.expect("shutdown");
    Ok(())
}

#[tokio::test]
async fn cancelling_a_serial_waiter_keeps_the_original_checkpoint_intact() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = Arc::new(fixture.owner().await?);
    let mut pending = fixture.initial()?;
    pending.model_calls = 1;
    pending.pending_model = Some(ModelRequest {
        operation_id: "model:original-serial".to_owned(),
        body: br#"{"input":"exact original"}"#.to_vec(),
    });
    fixture.host.pause_commit.store(true, Ordering::SeqCst);
    let first_owner = owner.clone();
    let first_state = pending.clone();
    let first = tokio::spawn(async move { first_owner.checkpoint(&first_state).await });
    tokio::time::timeout(
        std::time::Duration::from_secs(10), fixture.host.acquired.notified(),
    ).await.context("original commit did not reach its held storage permit")?;

    let mut cancelled = pending.clone();
    cancelled.cancelled = true;
    {
        // Poll a real concurrent call until it waits behind the original I/O,
        // then cancel only that waiter. No production test hook is involved.
        let mut waiting = Box::pin(owner.checkpoint(&cancelled));
        let mut context = std::task::Context::from_waker(std::task::Waker::noop());
        assert!(std::future::Future::poll(waiting.as_mut(), &mut context).is_pending());
    }
    fixture.host.resume_commit.notify_one();
    first.await.context("original checkpoint task panicked")??;
    owner.confirm_durable().await?;
    let head = fixture.head(&owner).await?;
    pretty_assertions::assert_eq!(head.version.revision, 2);
    pretty_assertions::assert_eq!(head.state.payload, encode(&fixture.anchor, &pending)?);
    let (_, recovered) = decode(&head.state.payload, &fixture.anchor.checkpoint)?;
    assert!(!recovered.cancelled);
    pretty_assertions::assert_eq!(
        recovered.pending_model.as_ref().map(|request| (&request.operation_id, &request.body)),
        pending.pending_model.as_ref().map(|request| (&request.operation_id, &request.body)),
    );
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn lost_ack_is_reconciled_before_a_distinct_successor_checkpoint() -> Result<()> {
    let fixture = Fixture::new().await?;
    let owner = Arc::new(fixture.owner().await?);
    let mut pending = fixture.initial()?;
    pending.model_calls = 1;
    pending.pending_model = Some(ModelRequest {
        operation_id: "model:lost-ack-serial".to_owned(),
        body: br#"{"input":"retain exact admitted bytes"}"#.to_vec(),
    });
    fixture.host.pause_commit.store(true, Ordering::SeqCst);
    let first_owner = owner.clone();
    let first_state = pending.clone();
    let first = tokio::spawn(async move { first_owner.checkpoint(&first_state).await });
    tokio::time::timeout(
        std::time::Duration::from_secs(10), fixture.host.acquired.notified(),
    ).await.context("original commit did not reach its held storage permit")?;
    first.abort();
    assert!(first.await.expect_err("original waiter must be cancelled").is_cancelled());

    // The original ThreadStore owned commit is still alive. Hold the next
    // commit at that same real storage permit to inspect the reconciled state.
    fixture.host.pause_commit.store(true, Ordering::SeqCst);
    let mut successor = pending.clone();
    successor.provider_response_id = Some("response:original".to_owned());
    let next_owner = owner.clone();
    let next_state = successor.clone();
    let next = tokio::spawn(async move { next_owner.checkpoint(&next_state).await });
    fixture.host.resume_commit.notify_one();
    tokio::time::timeout(
        std::time::Duration::from_secs(10), fixture.host.acquired.notified(),
    ).await.context("successor commit did not follow the original durable commit")?;
    let (version, payload, still_pending) = owner.with_cursor(|cursor| {
        Ok((cursor.version.clone(), cursor.payload.clone(), cursor.pending.clone()))
    })?;
    pretty_assertions::assert_eq!(version.context("original acknowledgement missing")?.revision, 2);
    pretty_assertions::assert_eq!(payload, Some(encode(&fixture.anchor, &pending)?));
    pretty_assertions::assert_eq!(still_pending, Some(encode(&fixture.anchor, &successor)?));

    fixture.host.resume_commit.notify_one();
    next.await.context("successor checkpoint task panicked")??;
    owner.confirm_durable().await?;
    let head = fixture.head(&owner).await?;
    pretty_assertions::assert_eq!(head.version.revision, 3);
    pretty_assertions::assert_eq!(head.state.payload, encode(&fixture.anchor, &successor)?);
    assert!(owner.checkpoint(&pending).await.is_err(), "stale state cannot erase the original response");
    pretty_assertions::assert_eq!(fixture.head(&owner).await?, head);
    fixture.live.shutdown().await?;
    Ok(())
}
