use std::collections::HashSet;
use std::fs;
use std::num::NonZeroUsize;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use codex_core::NotSubmittedReason;
use codex_core::StartIfIdleSubmission;
use codex_core::StartThreadOptions;
use codex_core::TurnInput;
use codex_core::TurnInputRequest;
use codex_core::TurnInputSubmission;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionEventSink;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ExtensionWarning;
use codex_extension_api::NoopExtensionEventSink;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadResumeInput;
use codex_history::RolloutItem;
use codex_history::RolloutLine;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::items::TurnItem;
use codex_protocol::models::ImageDetail;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::user_input::MAX_USER_INPUT_TEXT_CHARS;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_queue_extension::QueueReconcileMode;
use codex_queue_extension::QueueReconcileOutcome;
use codex_queue_extension::QueueServiceError;
use codex_queue_extension::QueuedItemService;
use codex_rollout::open_rollout_line_reader;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_thread_store::LocalQueueStore;
use codex_thread_store::QueueStore;
use codex_thread_store::QueuedClientBindingReserveOutcome;
use codex_thread_store::QueuedClientDispatchClaimOutcome;
use codex_thread_store::QueuedClientDispatchLease;
use codex_thread_store::QueuedClientDispatchLock;
use codex_thread_store::QueuedClientExpiredDispatch;
use codex_thread_store::ThreadStoreError;
use codex_thread_store::ThreadStoreFuture;
use codex_utils_absolute_path::test_support::PathExt;
use core_test_support::hooks::trust_discovered_hooks;
use core_test_support::responses;
use core_test_support::responses::start_mock_server;
use core_test_support::streaming_sse::StreamingSseChunk;
use core_test_support::streaming_sse::start_streaming_sse_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event_match;
use core_test_support::wait_for_event_with_timeout;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::sync::oneshot;

const TINY_PNG_BYTES: &[u8] = &[
    137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82, 0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0,
    0, 0, 31, 21, 196, 137, 0, 0, 0, 11, 73, 68, 65, 84, 120, 156, 99, 96, 0, 2, 0, 0, 5, 0, 1,
    122, 94, 171, 63, 0, 0, 0, 0, 73, 69, 78, 68, 174, 66, 96, 130,
];
const TINY_PNG_DATA_URL: &str = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=";

#[derive(Default)]
struct RecordingEventSink {
    events: Mutex<Vec<Event>>,
}

impl ExtensionEventSink for RecordingEventSink {
    fn emit(&self, event: Event) {
        self.events
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(event);
    }

    fn emit_warning(&self, _warning: ExtensionWarning) {}
}

#[derive(Default)]
struct InstalledQueue {
    service: OnceLock<Arc<QueuedItemService>>,
    skip_next_idle: Mutex<Option<ThreadId>>,
}

impl ThreadLifecycleContributor<codex_core::config::Config> for InstalledQueue {
    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        match self.service.get() {
            Some(service) => <QueuedItemService as ThreadLifecycleContributor<
                codex_core::config::Config,
            >>::on_thread_resume(service.as_ref(), input),
            None => Box::pin(async {}),
        }
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        if self
            .skip_next_idle
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take_if(|thread_id| thread_id.to_string() == input.thread_store.level_id())
            .is_some()
        {
            return Box::pin(async {});
        }
        match self.service.get() {
            Some(service) => <QueuedItemService as ThreadLifecycleContributor<
                codex_core::config::Config,
            >>::on_thread_idle(service.as_ref(), input),
            None => Box::pin(async {}),
        }
    }
}

fn registered_queue_extensions() -> (
    Arc<InstalledQueue>,
    Arc<ExtensionRegistry<codex_core::config::Config>>,
) {
    let installed = Arc::new(InstalledQueue::default());
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(installed.clone());
    (installed, Arc::new(extensions.build()))
}

fn install_registered_queue(
    test: &TestCodex,
    installed: &InstalledQueue,
) -> anyhow::Result<Arc<QueuedItemService>> {
    let service = Arc::new(QueuedItemService::new(
        loaded_thread_queue(test)?,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    ));
    assert!(installed.service.set(Arc::clone(&service)).is_ok());
    Ok(service)
}

fn write_rejecting_prompt_hook(home: &Path) {
    let script_path = home.join("queue_prompt_hook.py");
    let log_path = home.join("queue_prompt_hook.log");
    let script = format!(
        r#"import json
from pathlib import Path
import sys

payload = json.load(sys.stdin)
with Path(r"{log_path}").open("a", encoding="utf-8") as log:
    log.write(payload["prompt"] + "\n")
if payload["prompt"] == "blocked":
    print(json.dumps({{"decision": "block", "reason": "blocked by queue hook"}}))
"#,
        log_path = log_path.display(),
    );
    std::fs::write(&script_path, script)
        .unwrap_or_else(|error| panic!("write queue hook script: {error}"));
    let hooks = serde_json::json!({
        "hooks": {
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": format!("python3 {}", script_path.display()),
                }]
            }]
        }
    });
    std::fs::write(home.join("hooks.json"), hooks.to_string())
        .unwrap_or_else(|error| panic!("write queue hooks: {error}"));
}

fn write_blocking_prompt_hook(home: &Path) {
    let script_path = home.join("queue_blocking_prompt_hook.py");
    let entered_path = home.join("queue_blocking_prompt_hook.entered");
    let release_path = home.join("queue_blocking_prompt_hook.release");
    let script = format!(
        r#"import json
from pathlib import Path
import sys
import time

payload = json.load(sys.stdin)
if payload["prompt"] in ["delay exact persistence", "delay exact rejection"]:
    Path(r"{entered_path}").write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not Path(r"{release_path}").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out waiting to release queue persistence hook")
        time.sleep(0.01)
    if payload["prompt"] == "delay exact rejection":
        print(json.dumps({{"decision": "block", "reason": "delayed queue rejection"}}))
"#,
        entered_path = entered_path.display(),
        release_path = release_path.display(),
    );
    std::fs::write(&script_path, script)
        .unwrap_or_else(|error| panic!("write blocking queue hook script: {error}"));
    let hooks = serde_json::json!({
        "hooks": {
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": format!("python3 {}", script_path.display()),
                }]
            }]
        }
    });
    std::fs::write(home.join("hooks.json"), hooks.to_string())
        .unwrap_or_else(|error| panic!("write blocking queue hooks: {error}"));
}

async fn wait_for_path(path: &Path) -> anyhow::Result<()> {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if path.exists() {
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .with_context(|| format!("timed out waiting for `{}`", path.display()))?;
    Ok(())
}

async fn test_queue() -> anyhow::Result<(Arc<dyn QueueStore>, TempDir)> {
    let home = tempfile::tempdir()?;
    let sqlite = SqliteConfig::new_for_testing(home.path().abs());
    let runtime = StateRuntime::init(sqlite.clone(), "test-provider".to_string()).await?;
    let queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::new(runtime));
    Ok((queue, home))
}

async fn test_queue_with_capacity(
    capacity: NonZeroUsize,
) -> anyhow::Result<(Arc<dyn QueueStore>, TempDir)> {
    let home = tempfile::tempdir()?;
    let sqlite = SqliteConfig::new_for_testing(home.path().abs());
    let runtime = StateRuntime::init(sqlite.clone(), "test-provider".to_string()).await?;
    let queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::with_capacity(runtime, capacity));
    Ok((queue, home))
}

struct FailDeleteOnceQueueStore {
    inner: LocalQueueStore,
    fail_next_delete: AtomicBool,
    fail_next_complete: AtomicBool,
    panic_next_complete: AtomicBool,
    block_complete_after_panic: AtomicBool,
    allow_blocked_complete: AtomicBool,
    complete_attempts: AtomicUsize,
    short_dispatch_lease: bool,
    release_count: AtomicUsize,
}

impl FailDeleteOnceQueueStore {
    fn new(inner: LocalQueueStore) -> Self {
        Self {
            inner,
            fail_next_delete: AtomicBool::new(true),
            fail_next_complete: AtomicBool::new(false),
            panic_next_complete: AtomicBool::new(false),
            block_complete_after_panic: AtomicBool::new(false),
            allow_blocked_complete: AtomicBool::new(true),
            complete_attempts: AtomicUsize::new(0),
            short_dispatch_lease: false,
            release_count: AtomicUsize::new(0),
        }
    }

    fn crash_after_rollout_flush(inner: LocalQueueStore) -> Self {
        Self {
            inner,
            fail_next_delete: AtomicBool::new(false),
            fail_next_complete: AtomicBool::new(true),
            panic_next_complete: AtomicBool::new(false),
            block_complete_after_panic: AtomicBool::new(false),
            allow_blocked_complete: AtomicBool::new(true),
            complete_attempts: AtomicUsize::new(0),
            short_dispatch_lease: true,
            release_count: AtomicUsize::new(0),
        }
    }

    fn with_short_dispatch_lease(inner: LocalQueueStore) -> Self {
        Self {
            inner,
            fail_next_delete: AtomicBool::new(false),
            fail_next_complete: AtomicBool::new(false),
            panic_next_complete: AtomicBool::new(false),
            block_complete_after_panic: AtomicBool::new(false),
            allow_blocked_complete: AtomicBool::new(true),
            complete_attempts: AtomicUsize::new(0),
            short_dispatch_lease: true,
            release_count: AtomicUsize::new(0),
        }
    }

    fn panic_then_block_completion(inner: LocalQueueStore) -> Self {
        Self {
            inner,
            fail_next_delete: AtomicBool::new(false),
            fail_next_complete: AtomicBool::new(false),
            panic_next_complete: AtomicBool::new(true),
            block_complete_after_panic: AtomicBool::new(true),
            allow_blocked_complete: AtomicBool::new(false),
            complete_attempts: AtomicUsize::new(0),
            short_dispatch_lease: true,
            release_count: AtomicUsize::new(0),
        }
    }
}

impl QueueStore for FailDeleteOnceQueueStore {
    fn change_version(&self) -> ThreadStoreFuture<'_, i64> {
        self.inner.change_version()
    }

    fn changes_since<'a>(
        &'a self,
        revision: i64,
        thread_ids: &'a [ThreadId],
    ) -> ThreadStoreFuture<'a, Vec<(ThreadId, i64)>> {
        self.inner.changes_since(revision, thread_ids)
    }

    fn enqueue(
        &self,
        thread_id: ThreadId,
        payload: String,
    ) -> ThreadStoreFuture<'_, codex_thread_store::QueuedUserSubmissionRecord> {
        self.inner.enqueue(thread_id, payload)
    }

    fn enqueue_guarded(
        &self,
        thread_id: ThreadId,
        payload: String,
        client_id: String,
        payload_sha256: String,
    ) -> ThreadStoreFuture<'_, codex_thread_store::QueuedUserSubmissionRecord> {
        self.inner
            .enqueue_guarded(thread_id, payload, client_id, payload_sha256)
    }

    fn reserve_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, QueuedClientBindingReserveOutcome> {
        self.inner
            .reserve_client_binding(thread_id, client_id, payload_sha256, payload)
    }

    #[allow(clippy::too_many_arguments)]
    fn finalize_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
        lease: codex_thread_store::QueuedClientBindingLease,
        mode: codex_thread_store::QueuedClientBindingFinalizeMode,
        observed_turn_id: Option<String>,
    ) -> ThreadStoreFuture<'_, codex_thread_store::QueuedClientBindingFinalizeOutcome> {
        self.inner.finalize_client_binding(
            thread_id,
            client_id,
            payload_sha256,
            payload,
            lease,
            mode,
            observed_turn_id,
        )
    }

    fn mark_client_binding_persisted(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        queued_item_id: String,
        turn_id: String,
    ) -> ThreadStoreFuture<'_, bool> {
        self.inner.mark_client_binding_persisted(
            thread_id,
            client_id,
            payload_sha256,
            queued_item_id,
            turn_id,
        )
    }

    fn try_acquire_client_dispatch_lock(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
    ) -> Result<Option<QueuedClientDispatchLock>, ThreadStoreError> {
        self.inner
            .try_acquire_client_dispatch_lock(thread_id, client_id, payload_sha256)
    }

    fn claim_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        queued_item_id: String,
        owner_id: String,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        let lease_expires_at_ms = if self.short_dispatch_lease {
            now_ms + 250
        } else {
            lease_expires_at_ms
        };
        self.inner.claim_client_binding_dispatch(
            process_lock,
            queued_item_id,
            owner_id,
            now_ms,
            lease_expires_at_ms,
        )
    }

    fn authorize_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchLease> {
        let lease_expires_at_ms = if self.short_dispatch_lease {
            now_ms + 250
        } else {
            lease_expires_at_ms
        };
        self.inner.authorize_client_binding_dispatch(
            process_lock,
            lease,
            now_ms,
            lease_expires_at_ms,
        )
    }

    fn recover_expired_client_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        expired: QueuedClientExpiredDispatch,
        new_owner_id: String,
        observed_turn_id: Option<String>,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        self.inner.recover_expired_client_dispatch(
            process_lock,
            expired,
            new_owner_id,
            observed_turn_id,
            now_ms,
            lease_expires_at_ms,
        )
    }

    fn complete_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: &'a QueuedClientDispatchLease,
        turn_id: String,
    ) -> ThreadStoreFuture<'a, ()> {
        self.complete_attempts.fetch_add(1, Ordering::SeqCst);
        if self.panic_next_complete.swap(false, Ordering::SeqCst) {
            panic!("simulated panic after durable Core admission before dispatch DB completion");
        }
        if self.fail_next_complete.swap(false, Ordering::SeqCst) {
            return Box::pin(async {
                Err(ThreadStoreError::Internal {
                    message: "simulated crash after rollout flush before dispatch DB completion"
                        .to_string(),
                })
            });
        }
        if self.block_complete_after_panic.load(Ordering::SeqCst) {
            return Box::pin(async move {
                while !self.allow_blocked_complete.load(Ordering::SeqCst) {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                self.inner
                    .complete_client_binding_dispatch(process_lock, lease, turn_id)
                    .await
            });
        }
        self.inner
            .complete_client_binding_dispatch(process_lock, lease, turn_id)
    }

    fn release_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
    ) -> ThreadStoreFuture<'a, ()> {
        self.release_count.fetch_add(1, Ordering::SeqCst);
        self.inner
            .release_client_binding_dispatch(process_lock, lease)
    }

    fn list_page(
        &self,
        thread_id: ThreadId,
        offset: usize,
        limit: usize,
    ) -> ThreadStoreFuture<'_, Vec<codex_thread_store::QueuedUserSubmissionRecord>> {
        self.inner.list_page(thread_id, offset, limit)
    }

    fn update(
        &self,
        thread_id: ThreadId,
        item_id: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, Option<codex_thread_store::QueuedUserSubmissionRecord>> {
        self.inner.update(thread_id, item_id, payload)
    }

    fn delete(&self, thread_id: ThreadId, item_id: String) -> ThreadStoreFuture<'_, bool> {
        if self.fail_next_delete.swap(false, Ordering::SeqCst) {
            return Box::pin(async {
                Err(ThreadStoreError::Internal {
                    message: "simulated crash before queue deletion".to_string(),
                })
            });
        }
        self.inner.delete(thread_id, item_id)
    }

    fn reorder(&self, thread_id: ThreadId, item_ids: Vec<String>) -> ThreadStoreFuture<'_, ()> {
        self.inner.reorder(thread_id, item_ids)
    }
}

fn loaded_thread_queue(test: &TestCodex) -> anyhow::Result<Arc<dyn QueueStore>> {
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    Ok(Arc::new(LocalQueueStore::new(runtime)))
}

fn user_input(text: &str) -> TurnInput {
    TurnInput::UserInput {
        content: vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }],
        client_id: None,
    }
}

fn structured_user_input(text: &str) -> TurnInput {
    TurnInput::UserInput {
        content: vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }],
        client_id: Some("stable-client-message".to_string()),
    }
}

fn user_input_with_media(text: &str, image: UserInput, audio: UserInput) -> TurnInput {
    let mut input = structured_user_input(text);
    if let TurnInput::UserInput { content, .. } = &mut input {
        content.extend([image, audio]);
    }
    input
}

async fn persisted_client_message_count(
    thread: &codex_core::CodexThread,
    client_id: &str,
) -> anyhow::Result<usize> {
    let path = thread.rollout_path().context("rollout path unavailable")?;
    let mut reader = open_rollout_line_reader(&path).await?;
    let mut current_turn_id = None;
    let mut observed_turn_ids = HashSet::new();
    let mut anonymous_legacy_count = 0;
    while let Some(line) = reader.next_line().await? {
        let Ok(record) = serde_json::from_str::<RolloutLine>(&line) else {
            continue;
        };
        match record.item {
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                current_turn_id = Some(event.turn_id);
            }
            RolloutItem::TurnContext(context) if context.turn_id.is_some() => {
                current_turn_id = context.turn_id;
            }
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event))
                if matches!(
                    &event.item,
                    TurnItem::UserMessage(item)
                        if item.client_id.as_deref() == Some(client_id)
                ) =>
            {
                observed_turn_ids.insert(event.turn_id);
            }
            RolloutItem::EventMsg(EventMsg::UserMessage(event))
                if event.client_id.as_deref() == Some(client_id) =>
            {
                if let Some(turn_id) = current_turn_id.as_ref() {
                    observed_turn_ids.insert(turn_id.clone());
                } else {
                    anonymous_legacy_count += 1;
                }
            }
            RolloutItem::EventMsg(EventMsg::TurnComplete(_)) => current_turn_id = None,
            _ => {}
        }
    }
    Ok(observed_turn_ids.len() + anonymous_legacy_count)
}

async fn emit_idle(service: &QueuedItemService, thread_id: ThreadId) {
    emit_idle_with_cause(service, thread_id, ThreadIdleCause::Completed).await;
}

async fn emit_idle_with_cause(
    service: &QueuedItemService,
    thread_id: ThreadId,
    cause: ThreadIdleCause,
) {
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new(thread_id.to_string());
    <QueuedItemService as ThreadLifecycleContributor<()>>::on_thread_idle(
        service,
        ThreadIdleInput {
            cause,
            session_store: &session_store,
            thread_store: &thread_store,
        },
    )
    .await;
}

#[tokio::test]
async fn queued_input_and_unique_event_ids_round_trip() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let sink = Arc::new(RecordingEventSink::default());
    let event_sink: Arc<dyn ExtensionEventSink> = sink.clone();
    let service = QueuedItemService::new(queue, Weak::new(), event_sink);
    let thread_id = ThreadId::new();
    let input = structured_user_input("structured message");

    let first = service.enqueue(thread_id, input.clone()).await?;
    let second = service.enqueue(thread_id, user_input("next")).await?;
    let TurnInput::UserInput {
        client_id: Some(generated_client_id),
        ..
    } = &second.input
    else {
        anyhow::bail!("queued message did not receive a client message id");
    };
    assert_eq!(
        7,
        uuid::Uuid::parse_str(generated_client_id)?.get_version_num()
    );
    assert_eq!(
        vec![first.clone(), second.clone()],
        service.list(thread_id).await?
    );
    assert_eq!(input, first.input);

    {
        let events = sink
            .events
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(2, events.len());
        for event in events.iter() {
            let EventMsg::ThreadQueueChanged(change) = &event.msg else {
                anyhow::bail!("event is not a queue change");
            };
            assert_eq!(change.thread_id, thread_id);
        }
        assert_ne!(events[0].id, events[1].id);
    }
    Ok(())
}

#[tokio::test]
async fn exact_reconcile_is_one_idempotent_queue_admission() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let input = structured_user_input("Matrix event");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;

    let first = service
        .reconcile(
            thread_id,
            None,
            input.clone(),
            digest.clone(),
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    assert_eq!("stable-client-message", first.client_user_message_id);
    assert_eq!(digest, first.payload_sha256);
    let QueueReconcileOutcome::Queued {
        item: first_item,
        created: true,
    } = first.outcome
    else {
        anyhow::bail!("first exact reconciliation did not create a row");
    };

    let second = service
        .reconcile(
            thread_id,
            None,
            input,
            digest,
            QueueReconcileMode::ReconcileOnly,
        )
        .await?;
    let QueueReconcileOutcome::Queued {
        item: second_item,
        created: false,
    } = second.outcome
    else {
        anyhow::bail!("same-payload retry did not join the durable row");
    };
    assert_eq!(first_item, second_item);
    assert_eq!(vec![first_item], service.list(thread_id).await?);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_queue_services_across_state_runtimes_submit_one_exact_binding() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response = responses::mount_sse_once(&server, responses::sse_completed("one-owner")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let primary_runtime = test.codex.state_db().context("state runtime unavailable")?;
    let other_runtime = StateRuntime::init(
        primary_runtime.sqlite().clone(),
        "test-provider".to_string(),
    )
    .await?;
    let primary_queue: Arc<dyn QueueStore> =
        Arc::new(LocalQueueStore::new(Arc::clone(&primary_runtime)));
    let other_queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::new(other_runtime));
    let input = structured_user_input("one exact Matrix dispatch");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let staging = QueuedItemService::new(
        Arc::clone(&primary_queue),
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    let admitted = staging
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    let QueueReconcileOutcome::Queued { item, .. } = admitted.outcome else {
        anyhow::bail!("exact Matrix input was not queued");
    };

    let first = QueuedItemService::new(
        primary_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let second = QueuedItemService::new(
        other_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let (first_result, second_result) = tokio::join!(
        first.start(test.codex.as_ref(), Some(item.id.clone()), None),
        second.start(test.codex.as_ref(), Some(item.id), None),
    );
    let results = [first_result, second_result];
    assert!(results.iter().any(Result::is_ok));
    for result in results {
        match result {
            Ok(StartIfIdleSubmission::Started { .. })
            | Err(QueueServiceError::DispatchInProgress { .. })
            | Err(QueueServiceError::Storage(ThreadStoreError::InvalidRequest { .. })) => {}
            outcome => anyhow::bail!("unexpected competing QueueService outcome: {outcome:?}"),
        }
    }
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    assert!(first.list(thread_id).await?.is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn caller_abort_after_core_started_keeps_exact_authority_until_persistence()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("one-cancel-safe-owner")).await;
    let test = test_codex()
        .with_pre_build_hook(write_blocking_prompt_hook)
        .with_config(trust_discovered_hooks)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let primary_runtime = test.codex.state_db().context("state runtime unavailable")?;
    let competing_runtime = StateRuntime::init(
        primary_runtime.sqlite().clone(),
        "test-provider".to_string(),
    )
    .await?;
    let owner_queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::with_short_dispatch_lease(
            LocalQueueStore::new(Arc::clone(&primary_runtime)),
        ));
    let competing_queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::new(competing_runtime));
    let owner = Arc::new(QueuedItemService::new(
        Arc::clone(&owner_queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    ));
    let competitor = QueuedItemService::new(
        competing_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let input = structured_user_input("delay exact persistence");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let admitted = owner
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    let QueueReconcileOutcome::Queued { item, .. } = admitted.outcome else {
        anyhow::bail!("exact Matrix input was not queued");
    };

    let owner_start = tokio::spawn({
        let owner = Arc::clone(&owner);
        let codex = Arc::clone(&test.codex);
        let queued_item_id = item.id.clone();
        async move {
            owner
                .start(codex.as_ref(), Some(queued_item_id), None)
                .await
        }
    });
    let entered = test
        .codex_home_path()
        .join("queue_blocking_prompt_hook.entered");
    let release = test
        .codex_home_path()
        .join("queue_blocking_prompt_hook.release");
    wait_for_path(&entered).await?;
    owner_start.abort();
    let aborted = owner_start
        .await
        .expect_err("caller task must be cancelled");
    assert!(aborted.is_cancelled());

    tokio::time::sleep(Duration::from_millis(400)).await;
    let competing = competitor
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("expired SQLite time alone must not bypass the owned process lock");
    assert!(matches!(
        competing,
        QueueServiceError::DispatchInProgress { .. }
    ));
    assert_eq!(0, response.requests().len());

    fs::write(&release, b"release")?;
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if competitor
                .list(thread_id)
                .await
                .is_ok_and(|items| items.is_empty())
            {
                return;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await?;
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn core_error_after_started_never_releases_ambiguous_dispatch() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("must-not-run")).await;
    let test = test_codex()
        .with_pre_build_hook(write_blocking_prompt_hook)
        .with_config(trust_discovered_hooks)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let primary_runtime = test.codex.state_db().context("state runtime unavailable")?;
    let competing_runtime = StateRuntime::init(
        primary_runtime.sqlite().clone(),
        "test-provider".to_string(),
    )
    .await?;
    let owner_store = Arc::new(FailDeleteOnceQueueStore::with_short_dispatch_lease(
        LocalQueueStore::new(Arc::clone(&primary_runtime)),
    ));
    let owner_queue: Arc<dyn QueueStore> = owner_store.clone();
    let competing_queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::new(competing_runtime));
    let owner = Arc::new(QueuedItemService::new(
        owner_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    ));
    let competitor = QueuedItemService::new(
        competing_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let input = structured_user_input("delay exact rejection");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let admitted = owner
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    let QueueReconcileOutcome::Queued { item, .. } = admitted.outcome else {
        anyhow::bail!("exact Matrix input was not queued");
    };

    let owner_start = tokio::spawn({
        let owner = Arc::clone(&owner);
        let codex = Arc::clone(&test.codex);
        let queued_item_id = item.id.clone();
        async move {
            owner
                .start(codex.as_ref(), Some(queued_item_id), None)
                .await
        }
    });
    let entered = test
        .codex_home_path()
        .join("queue_blocking_prompt_hook.entered");
    let release = test
        .codex_home_path()
        .join("queue_blocking_prompt_hook.release");
    wait_for_path(&entered).await?;
    tokio::time::sleep(Duration::from_millis(400)).await;
    let competing = competitor
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("expired SQLite lease must not bypass active Core ownership");
    assert!(matches!(
        competing,
        QueueServiceError::DispatchInProgress { .. }
    ));

    fs::write(&release, b"release")?;
    let error = tokio::time::timeout(Duration::from_secs(10), owner_start)
        .await??
        .expect_err("the delayed hook must reject the started Core task");
    assert!(matches!(error, QueueServiceError::CoreSubmissionError(_)));
    assert_eq!(
        0,
        owner_store.release_count.load(Ordering::SeqCst),
        "an ambiguous Core error must leave the binding dispatching"
    );
    assert_eq!(vec![item.clone()], owner.list(thread_id).await?);
    assert!(response.requests().is_empty());
    tokio::time::sleep(Duration::from_millis(400)).await;
    let competing = competitor
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("an ambiguous Core error must retain the process fence beyond lease expiry");
    assert!(matches!(
        competing,
        QueueServiceError::DispatchInProgress { .. }
    ));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completion_panic_retains_exact_authority_in_settlement_guardian() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("panic-safe-owner")).await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let primary_runtime = test.codex.state_db().context("state runtime unavailable")?;
    let competing_runtime = StateRuntime::init(
        primary_runtime.sqlite().clone(),
        "test-provider".to_string(),
    )
    .await?;
    let owner_store = Arc::new(FailDeleteOnceQueueStore::panic_then_block_completion(
        LocalQueueStore::new(Arc::clone(&primary_runtime)),
    ));
    let owner_queue: Arc<dyn QueueStore> = owner_store.clone();
    let competing_queue: Arc<dyn QueueStore> = Arc::new(LocalQueueStore::new(competing_runtime));
    let owner = QueuedItemService::new(
        owner_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let competitor = QueuedItemService::new(
        competing_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let input = structured_user_input("panic after exact admission");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let admitted = owner
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    let QueueReconcileOutcome::Queued { item, .. } = admitted.outcome else {
        anyhow::bail!("exact Matrix input was not queued");
    };

    let error = owner
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("completion panic must be surfaced without dropping authority");
    assert!(
        matches!(
            error,
            QueueServiceError::Storage(ThreadStoreError::Internal { ref message })
                if message.contains("completion task failed ambiguously")
        ),
        "unexpected completion panic error: {error:?}"
    );

    tokio::time::timeout(Duration::from_secs(10), async {
        while owner_store.complete_attempts.load(Ordering::SeqCst) < 2 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await?;
    tokio::time::sleep(Duration::from_millis(400)).await;
    let competing = competitor
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("lease expiry must not bypass the panic guardian's process lock");
    assert!(matches!(
        competing,
        QueueServiceError::DispatchInProgress { .. }
    ));
    assert_eq!(
        0,
        owner_store.release_count.load(Ordering::SeqCst),
        "panic settlement must never release ambiguous authority"
    );

    owner_store
        .allow_blocked_complete
        .store(true, Ordering::SeqCst);
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if owner
                .list(thread_id)
                .await
                .is_ok_and(|items| items.is_empty())
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await?;
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reserved_to_persisted_legacy_row_deletion_emits_queue_changed() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("already-persisted")).await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let input = structured_user_input("persist before legacy row adoption");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let submission = test
        .codex
        .start_or_steer_turn(TurnInputRequest::new(input.clone()))
        .await?;
    assert!(matches!(submission, TurnInputSubmission::Started { .. }));
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;

    let queue = loaded_thread_queue(&test)?;
    queue
        .enqueue(thread_id, serde_json::to_string(&input)?)
        .await?;
    let sink = Arc::new(RecordingEventSink::default());
    let event_sink: Arc<dyn ExtensionEventSink> = sink.clone();
    let service = QueuedItemService::new(queue, Arc::downgrade(&test.thread_manager), event_sink);
    let reconciled = service
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::ReconcileOnly,
        )
        .await?;
    assert!(matches!(
        reconciled.outcome,
        QueueReconcileOutcome::Persisted { .. }
    ));
    assert!(service.list(thread_id).await?.is_empty());
    let events = sink
        .events
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert_eq!(1, events.len());
    assert!(matches!(
        &events[0].msg,
        EventMsg::ThreadQueueChanged(change) if change.thread_id == thread_id
    ));
    assert_eq!(1, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rollout_flush_before_dispatch_db_completion_recovers_without_resubmit()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("persisted-before-crash"))
            .await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let crash_queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::crash_after_rollout_flush(
            LocalQueueStore::new(Arc::clone(&runtime)),
        ));
    let crashing = QueuedItemService::new(
        crash_queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let input = structured_user_input("rollout durable before DB CAS");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let admitted = crashing
        .reconcile(
            thread_id,
            test.codex.rollout_path(),
            input,
            digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;
    let QueueReconcileOutcome::Queued { item, .. } = admitted.outcome else {
        anyhow::bail!("exact Matrix input was not queued");
    };

    let error = crashing
        .start(test.codex.as_ref(), Some(item.id.clone()), None)
        .await
        .expect_err("fault must interrupt after Core persisted admission");
    assert!(
        matches!(
            error,
            QueueServiceError::Storage(ThreadStoreError::Internal { .. })
        ),
        "unexpected crash-window error: {error:?}"
    );
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    tokio::time::sleep(Duration::from_millis(300)).await;

    let restarted_runtime =
        StateRuntime::init(runtime.sqlite().clone(), "test-provider".to_string()).await?;
    let restarted = QueuedItemService::new(
        Arc::new(LocalQueueStore::new(restarted_runtime)),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let recovered = restarted
        .start(test.codex.as_ref(), Some(item.id), None)
        .await?;
    assert!(matches!(recovered, StartIfIdleSubmission::Started { .. }));
    assert!(restarted.list(thread_id).await?.is_empty());
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    Ok(())
}

#[tokio::test]
async fn exact_reconcile_rejects_expected_digest_drift_without_a_row() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();

    let error = service
        .reconcile(
            thread_id,
            None,
            structured_user_input("Matrix event"),
            "0".repeat(64),
            QueueReconcileMode::AllowIfAbsent,
        )
        .await
        .expect_err("caller digest drift must fail before reservation");
    assert!(matches!(
        error,
        QueueServiceError::ClientIdPayloadConflict { .. }
    ));
    assert!(service.list(thread_id).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn raw_queue_store_enqueue_cannot_bypass_reconcile_reservation() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let thread_id = ThreadId::new();
    let input = structured_user_input("Matrix event");
    let TurnInput::UserInput { content, .. } = &input else {
        unreachable!("test input is user input");
    };
    let digest = user_input_payload_sha256(content)?;
    let payload = serde_json::to_string(&input)?;
    assert!(matches!(
        queue
            .reserve_client_binding(
                thread_id,
                "stable-client-message".to_string(),
                digest,
                payload.clone(),
            )
            .await?,
        QueuedClientBindingReserveOutcome::Reserved(_)
    ));

    let error = queue
        .enqueue(thread_id, payload)
        .await
        .expect_err("raw trait enqueue must observe the reservation");
    assert!(matches!(error, ThreadStoreError::Conflict { .. }));
    assert!(queue.list_page(thread_id, 0, 1).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn exact_reconcile_conflicting_payload_fails_before_second_admission() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let first = structured_user_input("first Matrix payload");
    let TurnInput::UserInput { content, .. } = &first else {
        unreachable!("test input is user input");
    };
    let first_digest = user_input_payload_sha256(content)?;
    service
        .reconcile(
            thread_id,
            None,
            first,
            first_digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await?;

    let conflicting = structured_user_input("different Matrix payload");
    let TurnInput::UserInput { content, .. } = &conflicting else {
        unreachable!("test input is user input");
    };
    let conflicting_digest = user_input_payload_sha256(content)?;
    let error = service
        .reconcile(
            thread_id,
            None,
            conflicting,
            conflicting_digest,
            QueueReconcileMode::AllowIfAbsent,
        )
        .await
        .expect_err("same client id cannot bind different content");
    assert!(matches!(
        error,
        QueueServiceError::Storage(ThreadStoreError::Conflict { .. })
    ));
    assert_eq!(1, service.list(thread_id).await?.len());
    Ok(())
}

#[tokio::test]
async fn capacity_rejection_preserves_the_admitted_client_identity() -> anyhow::Result<()> {
    let (queue, _home) = test_queue_with_capacity(NonZeroUsize::new(1).expect("non-zero")).await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let admitted = service
        .enqueue(thread_id, structured_user_input("admitted"))
        .await?;

    let error = service
        .enqueue(thread_id, structured_user_input("rejected"))
        .await
        .expect_err("the runtime capacity must reject the second pending item");
    assert!(matches!(
        error,
        QueueServiceError::Storage(ThreadStoreError::InvalidRequest { ref message })
            if message == "runtime queue cannot contain more than 1 submission"
    ));
    assert_eq!(vec![admitted], service.list(thread_id).await?);
    Ok(())
}

#[tokio::test]
async fn editing_reordering_and_deleting_preserve_queue_identity() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let first = service
        .enqueue(thread_id, structured_user_input("first"))
        .await?;
    let second = service.enqueue(thread_id, user_input("second")).await?;
    let edited = service
        .update(thread_id, first.id.clone(), user_input("edited"))
        .await?
        .context("queued item missing")?;
    assert_eq!(first.id, edited.id);
    let TurnInput::UserInput { client_id, .. } = &edited.input else {
        anyhow::bail!("edited queue item does not contain user input");
    };
    assert_eq!(Some("stable-client-message"), client_id.as_deref());
    assert!(matches!(
        service.reorder(thread_id, vec![first.id.clone()]).await,
        Err(QueueServiceError::Storage(
            ThreadStoreError::InvalidRequest { .. }
        ))
    ));
    service
        .reorder(thread_id, vec![second.id.clone(), first.id.clone()])
        .await?;
    assert_eq!(
        vec![second.clone(), edited.clone()],
        service.list(thread_id).await?
    );
    assert!(service.delete(thread_id, second.id).await?);
    assert_eq!(vec![edited], service.list(thread_id).await?);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn starting_a_selected_item_preserves_the_remaining_queue() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("selected-turn")).await;
    let test = test_codex().build_with_auto_env(&server).await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let first = service.enqueue(thread_id, user_input("first")).await?;
    let second = service
        .enqueue(thread_id, structured_user_input("second"))
        .await?;

    let submission = service
        .start(
            test.codex.as_ref(),
            Some(second.id.clone()),
            /*trace*/ None,
        )
        .await?;

    assert!(matches!(
        submission,
        StartIfIdleSubmission::Started { turn_id } if !turn_id.is_empty()
    ));
    assert_eq!(vec![first], service.list(thread_id).await?);
    wait_for_event_match(test.codex.as_ref(), |event| match event {
        EventMsg::TurnComplete(_) => Some(()),
        _ => None,
    })
    .await;
    assert_eq!(
        Some("second"),
        response
            .single_request()
            .message_input_texts("user")
            .last()
            .map(String::as_str)
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn persisted_admission_reconciles_compressed_rollout() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("durable-turn")).await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::new(LocalQueueStore::new(runtime)));
    let service = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, structured_user_input("survive delete crash"))
        .await?;

    let error = service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("simulated delete failure must leave the queue row durable");
    assert!(
        matches!(
            error,
            QueueServiceError::Storage(ThreadStoreError::Internal { .. })
        ),
        "unexpected simulated crash error: {error:?}"
    );
    assert_eq!(vec![queued.clone()], service.list(thread_id).await?);

    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    let rollout_path = test
        .codex
        .rollout_path()
        .context("rollout path unavailable")?;
    test.codex.shutdown_and_wait().await?;
    let rollout = fs::read(&rollout_path)?;
    let compressed_path = rollout_path.with_extension("jsonl.zst");
    fs::write(
        &compressed_path,
        zstd::stream::encode_all(rollout.as_slice(), /*level*/ 3)?,
    )?;
    fs::remove_file(&rollout_path)?;

    // A new service instance models restart after Core persisted the message
    // but the old process died before queue deletion. Reconciliation must use
    // the compressed representation without loading the whole rollout.
    let restarted = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let replay = restarted
        .start(test.codex.as_ref(), Some(queued.id), /*trace*/ None)
        .await?;
    assert!(matches!(replay, StartIfIdleSubmission::Started { .. }));
    assert!(restarted.list(thread_id).await?.is_empty());
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn persisted_client_id_with_conflicting_payload_fails_closed_from_compressed_rollout()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("durable-turn")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::new(LocalQueueStore::new(runtime)));
    let service = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, structured_user_input("original Matrix event"))
        .await?;

    service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("simulated delete failure must retain the admitted queue row");
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    let conflicting = service
        .update(
            thread_id,
            queued.id.clone(),
            structured_user_input("conflicting Matrix event"),
        )
        .await?
        .context("retained queue row disappeared")?;

    let rollout_path = test
        .codex
        .rollout_path()
        .context("rollout path unavailable")?;
    test.codex.shutdown_and_wait().await?;
    let rollout = fs::read(&rollout_path)?;
    let compressed_path = rollout_path.with_extension("jsonl.zst");
    fs::write(
        &compressed_path,
        zstd::stream::encode_all(rollout.as_slice(), /*level*/ 3)?,
    )?;
    fs::remove_file(&rollout_path)?;

    let restarted = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let error = restarted
        .start(
            test.codex.as_ref(),
            Some(conflicting.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("same client id with different content must not join");
    assert!(
        matches!(
            error,
            QueueServiceError::ClientIdPayloadConflict { ref client_id, .. }
                if client_id == "stable-client-message"
        ),
        "unexpected conflict error: {error:?}"
    );
    assert_eq!(vec![conflicting], restarted.list(thread_id).await?);
    assert_eq!(1, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn legacy_client_id_without_payload_digest_is_readable_but_cannot_join() -> anyhow::Result<()>
{
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("durable-turn")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::new(LocalQueueStore::new(runtime)));
    let service = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, structured_user_input("legacy Matrix event"))
        .await?;
    service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("simulated delete failure must retain the admitted queue row");
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;

    let rollout_path = test
        .codex
        .rollout_path()
        .context("rollout path unavailable")?;
    test.codex.shutdown_and_wait().await?;
    let mut saw_binding = false;
    let mut rewritten = Vec::new();
    for line in fs::read_to_string(&rollout_path)?.lines() {
        let mut record = serde_json::from_str::<RolloutLine>(line)?;
        if let RolloutItem::EventMsg(EventMsg::UserMessage(event)) = &mut record.item
            && event.client_id.as_deref() == Some("stable-client-message")
        {
            saw_binding = event.payload_sha256.take().is_some();
        }
        rewritten.push(serde_json::to_string(&record)?);
    }
    assert!(
        saw_binding,
        "new rollout did not contain its payload digest"
    );
    fs::write(&rollout_path, format!("{}\n", rewritten.join("\n")))?;

    let cold_reader = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let error = cold_reader
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("legacy client id without an exact digest must fail closed");
    assert!(
        matches!(
            error,
            QueueServiceError::LegacyClientIdBinding { ref client_id }
                if client_id == "stable-client-message"
        ),
        "unexpected legacy binding error: {error:?}"
    );
    assert_eq!(vec![queued], cold_reader.list(thread_id).await?);
    assert_eq!(1, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_and_legacy_bindings_for_the_same_turn_join_once() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("durable-turn")).await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let runtime = test.codex.state_db().context("state runtime unavailable")?;
    let queue: Arc<dyn QueueStore> =
        Arc::new(FailDeleteOnceQueueStore::new(LocalQueueStore::new(runtime)));
    let service = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, structured_user_input("paginated Matrix event"))
        .await?;
    service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("simulated delete failure must retain the admitted queue row");
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;

    let rollout_path = test
        .codex
        .rollout_path()
        .context("rollout path unavailable")?;
    test.codex.shutdown_and_wait().await?;
    let mut exact_turn_id = None;
    let mut rewritten = Vec::new();
    for line in fs::read_to_string(&rollout_path)?.lines() {
        let record = serde_json::from_str::<RolloutLine>(line)?;
        let legacy = match &record.item {
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) => match &event.item {
                TurnItem::UserMessage(item)
                    if item.client_id.as_deref() == Some("stable-client-message") =>
                {
                    exact_turn_id = Some(event.turn_id.clone());
                    Some(RolloutLine {
                        timestamp: record.timestamp.clone(),
                        ordinal: None,
                        item: RolloutItem::EventMsg(EventMsg::UserMessage(
                            item.as_legacy_user_message_event(),
                        )),
                    })
                }
                _ => None,
            },
            _ => None,
        };
        rewritten.push(serde_json::to_string(&record)?);
        if let Some(legacy) = legacy {
            rewritten.push(serde_json::to_string(&legacy)?);
        }
    }
    let turn_id = exact_turn_id.context("paginated exact user-message binding unavailable")?;
    fs::write(&rollout_path, format!("{}\n", rewritten.join("\n")))?;

    let cold_reader = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let joined = cold_reader
        .start(test.codex.as_ref(), Some(queued.id), /*trace*/ None)
        .await?;
    assert!(matches!(
        joined,
        StartIfIdleSubmission::Started { turn_id: joined } if joined == turn_id
    ));
    assert!(cold_reader.list(thread_id).await?.is_empty());
    assert_eq!(1, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn same_client_id_bound_to_two_turns_is_ambiguous_and_fails_closed() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse_completed("first-turn"),
            responses::sse_completed("second-turn"),
        ],
    )
    .await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    for _ in 0..2 {
        let mut attempts = 0;
        loop {
            let submission = test
                .codex
                .start_turn_if_idle_and_wait_for_persisted_admission(TurnInputRequest::new(
                    structured_user_input("reused Matrix event"),
                ))
                .await
                .map_err(|error| anyhow::anyhow!("persist duplicate client id: {error:?}"))?;
            match submission {
                StartIfIdleSubmission::Started { .. } => break,
                StartIfIdleSubmission::NotSubmitted {
                    reason: NotSubmittedReason::NotIdle,
                } if attempts < 50 => {
                    attempts += 1;
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                other => anyhow::bail!("duplicate client-id seed turn was not started: {other:?}"),
            }
        }
        wait_for_event_match(test.codex.as_ref(), |event| {
            matches!(event, EventMsg::TurnComplete(_)).then_some(())
        })
        .await;
    }

    let thread_id = test.session_configured.thread_id;
    let service = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, structured_user_input("reused Matrix event"))
        .await?;
    let error = service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("one client id cannot authorize joins to multiple turns");
    assert!(
        matches!(
            error,
            QueueServiceError::AmbiguousClientIdBinding { ref client_id }
                if client_id == "stable-client-message"
        ),
        "unexpected ambiguous binding error: {error:?}"
    );
    assert_eq!(vec![queued], service.list(thread_id).await?);
    assert_eq!(2, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn corrupt_rollout_blocks_queue_replay_and_preserves_the_item() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response = responses::mount_sse_once(&server, responses::sse_completed("seed-turn")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    test.submit_text_turn("seed").await?;

    let rollout_path = test
        .codex
        .rollout_path()
        .context("rollout path unavailable")?;
    let mut rollout = fs::read(&rollout_path)?;
    rollout.extend_from_slice(b"not-json\n");
    fs::write(&rollout_path, rollout)?;

    let queue = loaded_thread_queue(&test)?;
    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(
            test.session_configured.thread_id,
            structured_user_input("must not replay across corruption"),
        )
        .await?;

    let error = service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("rollout corruption must block queue replay");
    assert!(
        matches!(
            error,
            QueueServiceError::Storage(ThreadStoreError::Internal { .. })
        ),
        "unexpected rollout corruption error: {error:?}"
    );
    assert_eq!(
        vec![queued],
        service.list(test.session_configured.thread_id).await?
    );
    assert_eq!(1, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn duplicate_queued_client_ids_dispatch_to_core_once() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("single-turn")).await;
    let test = test_codex()
        .with_history_mode(ThreadHistoryMode::Paginated)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    let staging = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    staging
        .enqueue(thread_id, structured_user_input("same Matrix event"))
        .await?;
    staging
        .enqueue(thread_id, structured_user_input("same Matrix event"))
        .await?;

    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    emit_idle(&service, thread_id).await;
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    emit_idle(&service, thread_id).await;

    assert!(service.list(thread_id).await?.is_empty());
    assert_eq!(1, response.requests().len());
    assert_eq!(
        1,
        persisted_client_message_count(test.codex.as_ref(), "stable-client-message").await?
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn conflicting_queued_client_ids_fail_closed_before_core_submission() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("must-not-run")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    let staging = QueuedItemService::new(
        Arc::clone(&queue),
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let first = staging
        .enqueue(thread_id, structured_user_input("first Matrix payload"))
        .await?;
    let second = staging
        .enqueue(
            thread_id,
            structured_user_input("conflicting Matrix payload"),
        )
        .await?;

    let error = staging
        .start(
            test.codex.as_ref(),
            Some(first.id.clone()),
            /*trace*/ None,
        )
        .await
        .expect_err("conflicting durable queue bindings must block manual dispatch");
    assert!(
        matches!(error, QueueServiceError::ClientIdPayloadConflict { .. }),
        "unexpected conflict error: {error:?}"
    );

    let lifecycle = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    emit_idle(&lifecycle, thread_id).await;
    assert_eq!(vec![first, second], lifecycle.list(thread_id).await?);
    assert_eq!(0, response.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn starting_a_selected_item_while_active_leaves_it_queued() -> anyhow::Result<()> {
    let (release_response, response_gate) = oneshot::channel();
    let (server, _completions) = start_streaming_sse_server(vec![vec![
        StreamingSseChunk {
            gate: None,
            body: responses::sse(vec![responses::ev_response_created("resp-1")]),
        },
        StreamingSseChunk {
            gate: Some(response_gate),
            body: responses::sse(vec![responses::ev_completed("resp-1")]),
        },
    ]])
    .await;
    let test = test_codex().build_with_streaming_server(&server).await?;
    let thread_id = test.session_configured.thread_id;
    let service = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, user_input("stay queued"))
        .await?;

    let active_turn = test
        .codex
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: "active turn".to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    assert!(matches!(active_turn, TurnInputSubmission::Started { .. }));
    tokio::time::timeout(
        Duration::from_secs(5),
        server.wait_for_request_count(/*count*/ 1),
    )
    .await?;

    let submission = service
        .start(
            test.codex.as_ref(),
            Some(queued.id.clone()),
            /*trace*/ None,
        )
        .await?;
    assert!(matches!(
        submission,
        StartIfIdleSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle
        }
    ));
    assert_eq!(vec![queued], service.list(thread_id).await?);

    release_response
        .send(())
        .expect("active response gate should remain open");
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn interrupted_turns_pause_queued_messages_but_failed_turns_drain_them() -> anyhow::Result<()>
{
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("failed-follow-up")).await;
    let test = test_codex().build_with_auto_env(&server).await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    let queued = service
        .enqueue(thread_id, user_input("continue after failure"))
        .await?;

    emit_idle_with_cause(&service, thread_id, ThreadIdleCause::Interrupted).await;
    assert_eq!(vec![queued], service.list(thread_id).await?);

    emit_idle_with_cause(&service, thread_id, ThreadIdleCause::Failed).await;
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    assert!(service.list(thread_id).await?.is_empty());
    assert_eq!(
        Some("continue after failure"),
        response
            .single_request()
            .message_input_texts("user")
            .last()
            .map(String::as_str)
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn registered_queue_lifecycle_starts_messages_in_fifo_order() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses = responses::mount_sse_sequence(
        &server,
        ["turn-a", "turn-b", "turn-c"]
            .into_iter()
            .map(responses::sse_completed)
            .collect(),
    )
    .await;
    let (installed, extensions) = registered_queue_extensions();
    let test = test_codex()
        .with_extensions(extensions)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let staging = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    for prompt in ["B", "C"] {
        staging.enqueue(thread_id, user_input(prompt)).await?;
    }
    let queue = install_registered_queue(&test, installed.as_ref())?;

    tokio::time::timeout(Duration::from_secs(10), async {
        test.submit_text_turn("A").await?;
        for _ in 0..2 {
            wait_for_event_match(test.codex.as_ref(), |event| {
                matches!(event, EventMsg::TurnComplete(_)).then_some(())
            })
            .await;
        }
        anyhow::Ok(())
    })
    .await??;

    let prompts = responses
        .requests()
        .into_iter()
        .map(|request| {
            request
                .message_input_texts("user")
                .pop()
                .context("model request has no user input")
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    assert_eq!(vec!["A", "B", "C"], prompts);
    assert!(queue.list(thread_id).await?.is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn externally_changed_queues_dispatch_independently_and_retry_failed_wakes()
-> anyhow::Result<()> {
    let server = start_mock_server().await;
    let model_responses = responses::mount_sse_sequence(
        &server,
        [
            "independent-queued-turn",
            "external-queued-turn",
            "resumed-queued-turn",
        ]
        .into_iter()
        .map(responses::sse_completed)
        .collect(),
    )
    .await;
    let (installed, extensions) = registered_queue_extensions();
    let test = test_codex()
        .with_extensions(extensions)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let queue = install_registered_queue(&test, installed.as_ref())?;
    let independent_thread = test
        .thread_manager
        .start_thread(StartThreadOptions::new(test.config.clone()))
        .await?;
    let external_runtime = StateRuntime::init(
        test.codex
            .state_db()
            .context("state runtime unavailable")?
            .sqlite()
            .clone(),
        "test-provider".to_string(),
    )
    .await?;
    let external_queue = QueuedItemService::new(
        Arc::new(LocalQueueStore::new(external_runtime)),
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    let mut watcher_extensions = ExtensionRegistryBuilder::<codex_core::config::Config>::new();
    codex_queue_extension::install(&mut watcher_extensions, Arc::clone(&queue));

    tokio::time::sleep(Duration::from_secs(/*secs*/ 1)).await;
    assert!(model_responses.requests().is_empty());
    *installed
        .skip_next_idle
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(thread_id);
    let first = external_queue
        .enqueue(thread_id, user_input("written by another process"))
        .await?;
    let updated = queue
        .update(
            thread_id,
            first.id,
            user_input("locally edited external message"),
        )
        .await?
        .context("external queue item disappeared")?;
    external_queue
        .enqueue(
            independent_thread.thread_id,
            user_input("independent thread"),
        )
        .await?;

    wait_for_event_with_timeout(
        independent_thread.thread.as_ref(),
        |event| matches!(event, EventMsg::TurnComplete(_)),
        Duration::from_secs(/*secs*/ 25),
    )
    .await;
    assert_eq!(1, model_responses.requests().len());
    assert_eq!(vec![updated], queue.list(thread_id).await?);

    wait_for_event_with_timeout(
        test.codex.as_ref(),
        |event| matches!(event, EventMsg::TurnComplete(_)),
        Duration::from_secs(/*secs*/ 25),
    )
    .await;
    tokio::time::sleep(Duration::from_secs(/*secs*/ 11)).await;

    assert!(queue.list(thread_id).await?.is_empty());
    assert!(queue.list(independent_thread.thread_id).await?.is_empty());

    let rollout_path = test.codex.rollout_path().context("rollout path missing")?;
    test.codex.shutdown_and_wait().await?;
    test.thread_manager.remove_thread(&thread_id).await;
    external_queue
        .enqueue(thread_id, user_input("queued before ordinary resume"))
        .await?;
    tokio::time::sleep(Duration::from_secs(/*secs*/ 11)).await;
    let resumed = test
        .thread_manager
        .resume_thread_from_rollout(
            test.config.clone(),
            rollout_path,
            test.thread_manager.auth_manager(),
            /*parent_trace*/ None,
            Default::default(),
        )
        .await?;
    wait_for_event_with_timeout(
        resumed.thread.as_ref(),
        |event| matches!(event, EventMsg::TurnComplete(_)),
        Duration::from_secs(/*secs*/ 25),
    )
    .await;
    assert!(queue.list(thread_id).await?.is_empty());

    let prompts = model_responses
        .requests()
        .into_iter()
        .filter_map(|request| request.message_input_texts("user").pop())
        .collect::<Vec<_>>();
    assert_eq!(
        vec![
            "independent thread",
            "locally edited external message",
            "queued before ordinary resume",
        ],
        prompts
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rejected_queue_messages_remain_durable_and_block_followups() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses =
        responses::mount_sse_once(&server, responses::sse_completed("initial-turn")).await;
    let (installed, extensions) = registered_queue_extensions();
    let test = test_codex()
        .with_extensions(extensions)
        .with_pre_build_hook(write_rejecting_prompt_hook)
        .with_config(trust_discovered_hooks)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let staging = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    let blocked = staging.enqueue(thread_id, user_input("blocked")).await?;
    let following = staging.enqueue(thread_id, user_input("C")).await?;
    let queue = install_registered_queue(&test, installed.as_ref())?;

    tokio::time::timeout(Duration::from_secs(10), async {
        test.submit_text_turn("A").await?;
        for _ in 0..2 {
            wait_for_event_match(test.codex.as_ref(), |event| {
                matches!(event, EventMsg::TurnComplete(_)).then_some(())
            })
            .await;
        }
        anyhow::Ok(())
    })
    .await??;

    let prompts = responses
        .requests()
        .into_iter()
        .map(|request| {
            request
                .message_input_texts("user")
                .pop()
                .context("model request has no user input")
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    assert_eq!(vec!["A"], prompts);
    let hook_log = std::fs::read_to_string(test.codex_home_path().join("queue_prompt_hook.log"))?;
    let hook_lines = hook_log.lines().collect::<Vec<_>>();
    assert_eq!(Some(&"A"), hook_lines.first());
    assert!(hook_lines[1..].iter().all(|line| *line == "blocked"));
    assert!(hook_lines.len() >= 2);
    assert_eq!(vec![blocked, following], queue.list(thread_id).await?);
    assert_eq!(1, responses.requests().len());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn explicitly_started_rejected_queue_messages_remain_durable() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let responses =
        responses::mount_sse_once(&server, responses::sse_completed("unexpected-turn")).await;
    let test = test_codex()
        .with_pre_build_hook(write_rejecting_prompt_hook)
        .with_config(trust_discovered_hooks)
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let queue = QueuedItemService::new(
        loaded_thread_queue(&test)?,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );

    let rejected = queue.enqueue(thread_id, user_input("blocked")).await?;
    let error = tokio::time::timeout(
        Duration::from_secs(10),
        queue.start(
            test.codex.as_ref(),
            Some(rejected.id.clone()),
            /*trace*/ None,
        ),
    )
    .await?
    .expect_err("hook rejection must not consume an unpersisted queue item");
    let QueueServiceError::CoreSubmissionError(error) = error else {
        anyhow::bail!("unexpected hook rejection error: {error:?}");
    };
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InvalidRequest(message)
            if message == "user message was rejected by a hook"
    ));
    wait_for_event_match(test.codex.as_ref(), |event| {
        matches!(event, EventMsg::TurnComplete(_)).then_some(())
    })
    .await;
    assert_eq!(vec![rejected], queue.list(thread_id).await?);
    let hook_log = std::fs::read_to_string(test.codex_home_path().join("queue_prompt_hook.log"))?;
    assert_eq!(vec!["blocked"], hook_log.lines().collect::<Vec<_>>());
    assert!(responses.requests().is_empty());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_attachments_are_snapshotted_before_enqueue_and_update() -> anyhow::Result<()> {
    let (queue, home) = test_queue().await?;
    let service = QueuedItemService::new(
        Arc::clone(&queue),
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    );
    let thread_id = ThreadId::new();
    let image_path = home.path().join("queued.png");
    let audio_path = home.path().join("queued.mp3");
    std::fs::write(&image_path, TINY_PNG_BYTES)?;
    std::fs::write(&audio_path, b"audio")?;
    let queued_input = user_input_with_media(
        "queued attachments",
        UserInput::LocalImage {
            path: image_path.clone(),
            detail: Some(ImageDetail::Original),
        },
        UserInput::LocalAudio {
            path: audio_path.clone(),
        },
    );
    let expected_queued_input = user_input_with_media(
        "queued attachments",
        UserInput::Image {
            image_url: TINY_PNG_DATA_URL.to_string(),
            detail: Some(ImageDetail::Original),
        },
        UserInput::Audio {
            audio_url: "data:audio/mpeg;base64,YXVkaW8=".to_string(),
        },
    );

    let queued = service.enqueue(thread_id, queued_input).await?;
    std::fs::remove_file(&image_path)?;
    std::fs::remove_file(&audio_path)?;

    assert_eq!(expected_queued_input, queued.input);
    assert_eq!(vec![queued.clone()], service.list(thread_id).await?);
    let queued_record = queue
        .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
        .await?
        .into_iter()
        .next()
        .context("snapshotted queued attachments were not persisted")?;
    let persisted_queued_input: TurnInput = serde_json::from_str(&queued_record.payload)?;
    assert_eq!(expected_queued_input, persisted_queued_input);

    let edited_image_path = home.path().join("edited.png");
    let edited_audio_path = home.path().join("edited.m4a");
    std::fs::write(&edited_image_path, TINY_PNG_BYTES)?;
    std::fs::write(&edited_audio_path, b"edited audio")?;
    let edited_input = user_input_with_media(
        "edited attachments",
        UserInput::LocalImage {
            path: edited_image_path.clone(),
            detail: Some(ImageDetail::High),
        },
        UserInput::LocalAudio {
            path: edited_audio_path.clone(),
        },
    );
    let expected_edited_input = user_input_with_media(
        "edited attachments",
        UserInput::Image {
            image_url: TINY_PNG_DATA_URL.to_string(),
            detail: Some(ImageDetail::High),
        },
        UserInput::Audio {
            audio_url: "data:audio/mp4;base64,ZWRpdGVkIGF1ZGlv".to_string(),
        },
    );

    let edited = service
        .update(thread_id, queued.id.clone(), edited_input)
        .await?
        .context("snapshotted queued attachments were not updated")?;
    std::fs::remove_file(&edited_image_path)?;
    std::fs::remove_file(&edited_audio_path)?;

    assert_eq!(expected_edited_input, edited.input);
    assert_eq!(vec![edited.clone()], service.list(thread_id).await?);
    let edited_record = queue
        .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
        .await?
        .into_iter()
        .next()
        .context("snapshotted edited attachments were not persisted")?;
    let persisted_edited_input: TurnInput = serde_json::from_str(&edited_record.payload)?;
    assert_eq!(expected_edited_input, persisted_edited_input);

    Ok(())
}

#[tokio::test]
async fn invalid_local_attachments_do_not_mutate_queue() -> anyhow::Result<()> {
    let (queue, home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let existing = service.enqueue(thread_id, user_input("existing")).await?;
    let missing_path = home.path().join("missing.png");
    let invalid_input = user_input_with_media(
        "invalid attachments",
        UserInput::LocalImage {
            path: missing_path,
            detail: Some(ImageDetail::Original),
        },
        UserInput::Audio {
            audio_url: "data:audio/mpeg;base64,YXVkaW8=".to_string(),
        },
    );

    assert!(matches!(
        service
            .enqueue(thread_id, invalid_input.clone())
            .await,
        Err(QueueServiceError::InvalidAttachment(error))
            if error.kind() == std::io::ErrorKind::NotFound
    ));
    assert!(matches!(
        service
            .update(
                thread_id,
                existing.id.clone(),
                invalid_input,
            )
            .await,
        Err(QueueServiceError::InvalidAttachment(error))
            if error.kind() == std::io::ErrorKind::NotFound
    ));
    assert_eq!(vec![existing], service.list(thread_id).await?);

    Ok(())
}

#[tokio::test]
async fn non_user_input_cannot_enter_the_user_message_queue() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let error = service
        .enqueue(
            ThreadId::new(),
            TurnInput::ResponseItem(ResponseItem::Other),
        )
        .await
        .expect_err("response item should not enter the user queue");
    assert!(matches!(error, QueueServiceError::InvalidInput));
    Ok(())
}

#[tokio::test]
async fn queued_text_limit_is_enforced_across_all_input_items() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let thread_id = ThreadId::new();
    let existing = service.enqueue(thread_id, user_input("existing")).await?;
    let mut oversized = user_input(&"x".repeat(MAX_USER_INPUT_TEXT_CHARS / 2));
    if let TurnInput::UserInput { content, .. } = &mut oversized {
        content.push(UserInput::Text {
            text: "y".repeat(MAX_USER_INPUT_TEXT_CHARS / 2 + 1),
            text_elements: Vec::new(),
        });
    }

    assert!(matches!(
        service
            .enqueue(thread_id, oversized.clone())
            .await,
        Err(QueueServiceError::InputTooLarge { actual_chars })
            if actual_chars == MAX_USER_INPUT_TEXT_CHARS + 1
    ));
    assert!(matches!(
        service
            .update(
                thread_id,
                existing.id.clone(),
                oversized,
            )
            .await,
        Err(QueueServiceError::InputTooLarge { actual_chars })
            if actual_chars == MAX_USER_INPUT_TEXT_CHARS + 1
    ));
    assert_eq!(vec![existing], service.list(thread_id).await?);

    Ok(())
}

#[tokio::test]
async fn queued_text_limit_counts_characters_and_ignores_non_text_items() -> anyhow::Result<()> {
    let (queue, _home) = test_queue().await?;
    let service = QueuedItemService::new(queue, Weak::new(), Arc::new(NoopExtensionEventSink));
    let mut input = structured_user_input(&"é".repeat(MAX_USER_INPUT_TEXT_CHARS));
    if let TurnInput::UserInput { content, .. } = &mut input {
        content.push(UserInput::Mention {
            name: "Demo App".to_string(),
            path: "app://demo-app".to_string(),
        });
    }

    let queued = service.enqueue(ThreadId::new(), input.clone()).await?;
    assert_eq!(input, queued.input);

    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn invalid_head_is_skipped_and_a_live_user_turn_is_accepted() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let response =
        responses::mount_sse_once(&server, responses::sse_completed("queued-turn")).await;
    let test = test_codex()
        .with_config(|config| config.include_environment_context = false)
        .build_with_auto_env(&server)
        .await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    queue
        .enqueue(thread_id, r#"{"unsupported":true}"#.to_string())
        .await?;
    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );

    service
        .enqueue(thread_id, structured_user_input("durable follow-up"))
        .await?;
    emit_idle(&service, thread_id).await;
    let client_id = wait_for_event_match(test.codex.as_ref(), |event| match event {
        EventMsg::ItemCompleted(event) => match &event.item {
            TurnItem::UserMessage(item) => Some(item.client_id.clone()),
            _ => None,
        },
        _ => None,
    })
    .await;
    assert_eq!(Some("stable-client-message".to_string()), client_id);
    wait_for_event_match(test.codex.as_ref(), |event| match event {
        EventMsg::TurnComplete(_) => Some(()),
        _ => None,
    })
    .await;
    assert!(service.list(thread_id).await?.is_empty());
    let request = response.single_request();
    assert_eq!(
        vec!["durable follow-up"],
        request.message_input_texts("user")
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn resumed_idle_dispatches_input_without_a_loaded_manager() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    responses::mount_sse_once(&server, responses::sse_completed("resumed-turn")).await;
    let test = test_codex().build_with_auto_env(&server).await?;
    let thread_id = test.session_configured.thread_id;
    let queue = loaded_thread_queue(&test)?;
    QueuedItemService::new(
        Arc::clone(&queue),
        Weak::new(),
        Arc::new(NoopExtensionEventSink),
    )
    .enqueue(thread_id, user_input("queued while unloaded"))
    .await?;
    let service = QueuedItemService::new(
        queue,
        Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink),
    );
    emit_idle(&service, thread_id).await;
    assert!(service.list(thread_id).await?.is_empty());
    Ok(())
}
