use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_protocol::ThreadId;
use codex_protocol::protocol::ThreadMemoryMode;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;
use tokio::sync::Notify;
use tokio::sync::RwLock;

use super::*;
use crate::LiveThread;
use crate::NativeCheckpointBinding;
use crate::NativeCheckpointCurrentness;
use crate::NativeCheckpointExpected;
use crate::NativeCheckpointOpenMode;
use crate::NativeCheckpointPermit;
use crate::NativeCheckpointState;
use crate::ResumeThreadParams;
use crate::StoredNativeCheckpoint;
use crate::ThreadPersistenceMetadata;
use crate::ThreadStoreFuture;
use crate::local::test_support::test_config;
use crate::local::test_support::write_session_file;

// The permit is a revocable host fixture. The writer, checkpoint, JSONL, flush,
// fsync, shutdown/reopen, and exact conflict detection are production code.
struct Host {
    current: Arc<RwLock<bool>>,
    pause: AtomicBool,
    acquired: Notify,
    resume: Notify,
}

impl NativeCheckpointCurrentness for Host {
    fn acquire<'a>(&'a self, _binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async move {
            let guard = self.current.clone().read_owned().await;
            if !*guard { return Err(conflict("test host revoked")); }
            if self.pause.swap(false, Ordering::SeqCst) {
                self.acquired.notify_one();
                self.resume.notified().await;
            }
            Ok(NativeCheckpointPermit::hold(guard))
        })
    }
}

struct Fixture {
    live: LiveThread,
    session: NativeCheckpointSession,
    host: Arc<Host>,
    path: PathBuf,
    resume: ResumeThreadParams,
    home: TempDir,
}

impl Fixture {
    async fn new() -> Self {
        let home = TempDir::new().expect("home");
        let thread_id = ThreadId::new();
        let path = write_session_file(home.path(), "2025-01-03T00-00-00", uuid::Uuid::parse_str(&thread_id.to_string()).expect("uuid")).expect("original history");
        let resume = ResumeThreadParams { thread_id, rollout_path: Some(path.clone()), history: None,
            include_archived: false, metadata: ThreadPersistenceMetadata { cwd: Some(home.path().to_path_buf()),
                model_provider: "test-provider".to_owned(), memory_mode: ThreadMemoryMode::Disabled } };
        let store = Arc::new(LocalThreadStore::new(test_config(home.path()), /*state_db*/ None));
        let live = LiveThread::resume(store, ThreadHistoryMode::Legacy, resume.clone()).await.expect("live writer");
        let host = Arc::new(Host { current: Arc::new(RwLock::new(true)), pause: AtomicBool::new(false), acquired: Notify::new(), resume: Notify::new() });
        let binding = NativeCheckpointBinding { thread_id, turn_id: "original-turn".to_owned(),
            operation_id: "original-operation".to_owned(), generation: 3, lease_id: "original-lease".to_owned() };
        let session = live.open_native_checkpoint(binding, NativeCheckpointOpenMode::Create, host.clone()).await.expect("session");
        Self { live, session, host, path, resume, home }
    }

    async fn checkpoint(&self, expected: NativeCheckpointExpected) -> StoredNativeCheckpoint {
        self.live.commit_native_checkpoint(&self.session, expected, NativeCheckpointState {
            binding: self.session.binding().clone(), payload: b"confirmed native state fixture".to_vec(),
        }).await.expect("real checkpoint")
    }

    fn items(&self) -> Vec<ResponseItem> {
        let namespace = format!("hepta_native_{:x}", Sha256::digest(serde_json::to_vec(self.session.binding()).expect("binding")));
        [json!({"type":"function_call","call_id":"call-original","name":"read","arguments":"{ \"path\": \"source.rs\" }"}),
            json!({"type":"function_call_output","call_id":"call-original","output":"exact output\n"}),
            json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"complete"}]})]
            .into_iter().enumerate().map(|(index, value)| {
                let mut item: ResponseItem = serde_json::from_value(value).expect("canonical output");
                item.set_id(Some(ResponseItemId::with_suffix(item.id_prefix().expect("kind"), format!("{namespace}_{index}"))));
                item.set_turn_id_if_missing(&self.session.binding().turn_id);
                item
            }).collect()
    }

    async fn append_existing(&self, items: &[ResponseItem]) {
        self.live.append_items(&items.iter().cloned().map(|item| RolloutItem::ResponseItem(item.into())).collect::<Vec<_>>()).await.expect("original writer append");
        self.live.flush().await.expect("flush");
    }

    async fn output(&self) -> Vec<ResponseItem> {
        self.live.load_history(false).await.expect("ordinary Codex history reader").items.into_iter()
            .filter_map(|item| match item { RolloutItem::ResponseItem(item) => Some(item.item), _ => None }).collect()
    }
}

#[tokio::test]
async fn checkpoint_inspection_does_not_create_missing_storage_or_grant_writes() {
    let fixture = Fixture::new().await;
    let database = fixture.home.path().join("native-turn-checkpoints.sqlite");
    let inspection = fixture.live.open_native_checkpoint(fixture.session.binding().clone(),
        NativeCheckpointOpenMode::Inspect, fixture.host.clone()).await.expect("original live inspection");
    assert!(matches!(fixture.live.load_native_checkpoint(&inspection).await.expect("inspect absent storage"),
        crate::NativeCheckpointLoad::Missing));
    assert!(!database.exists(), "an observation cannot initialize the missing checkpoint database");
    assert!(fixture.live.commit_native_checkpoint(&inspection, NativeCheckpointExpected::Absent,
        NativeCheckpointState { binding: inspection.binding().clone(), payload: b"not a write permit".to_vec() }).await.is_err());
    assert!(!database.exists());
    let original = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    assert_eq!(fixture.live.load_native_checkpoint(&inspection).await.expect("observe real checkpoint"),
        crate::NativeCheckpointLoad::Present(original));
    fixture.live.shutdown().await.expect("close original writer");
    assert!(fixture.live.load_native_checkpoint(&inspection).await.is_err(), "inspection retains the original writer epoch");
}

#[tokio::test]
async fn checkpoint_first_projection_preserves_input_and_is_exactly_idempotent() {
    let fixture = Fixture::new().await;
    let original = tokio::fs::read(&fixture.path).await.expect("input bytes");
    let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    let items = fixture.items();
    fixture.live.sync_native_history(&fixture.session, checkpoint.version.clone(), items.clone()).await.expect("project after checkpoint");
    let once = tokio::fs::read(&fixture.path).await.expect("history");
    assert!(once.starts_with(&original));
    assert_eq!(fixture.output().await, items);
    fixture.live.sync_native_history(&fixture.session, checkpoint.version, items).await.expect("lost acknowledgment retry");
    assert_eq!(tokio::fs::read(&fixture.path).await.expect("history"), once);
    fixture.live.shutdown().await.expect("shutdown");
}

#[tokio::test]
async fn original_developer_system_and_additional_tools_are_preserved_as_input() {
    let fixture = Fixture::new().await;
    let mut input = Vec::new();
    for role in ["developer", "system"] {
        let mut item: ResponseItem = serde_json::from_value(json!({"type":"message","role":role,
            "content":[{"type":"input_text","text":"original input instructions"}]})).expect("input");
        item.set_turn_id_if_missing(&fixture.session.binding().turn_id);
        input.push(item);
    }
    fixture.append_existing(&input).await;
    let tools: ResponseItem = serde_json::from_value(json!({"type":"additional_tools","role":"system",
        "tools":[{"type":"function","name":"read","parameters":{"type":"object"}}]})).expect("tools input");
    // Current append policy filters this request-only item. A legacy canonical
    // history may still contain it; write the actual record to test that reader.
    let mut line = serde_json::to_value(RolloutItem::ResponseItem(tools.clone().into())).expect("canonical record");
    line["timestamp"] = json!("2025-01-03T00:00:00Z");
    let mut bytes = serde_json::to_vec(&line).expect("line");
    bytes.push(b'\n');
    let mut file = tokio::fs::OpenOptions::new().append(true).open(&fixture.path).await.expect("legacy history");
    file.write_all(&bytes).await.expect("legacy input");
    file.flush().await.expect("legacy input flush");
    drop(file);
    input.push(tools);
    let original = tokio::fs::read(&fixture.path).await.expect("input history");
    let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    fixture.live.sync_native_history(&fixture.session, checkpoint.version.clone(), Vec::new()).await.expect("empty output sync accepts original input");
    assert_eq!(tokio::fs::read(&fixture.path).await.expect("unchanged input"), original);
    let output = fixture.items();
    fixture.live.sync_native_history(&fixture.session, checkpoint.version, output.clone()).await.expect("native output beside original input");
    input.extend(output);
    assert_eq!(fixture.output().await, input);
    fixture.live.shutdown().await.expect("shutdown");
}

#[tokio::test]
async fn complete_prefix_after_interruption_is_repaired_by_same_checkpoint_after_reopen() {
    let fixture = Fixture::new().await;
    let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    let items = fixture.items();
    fixture.append_existing(&items[..1]).await;
    fixture.live.shutdown().await.expect("shutdown old writer");
    let store = Arc::new(LocalThreadStore::new(test_config(fixture.home.path()), /*state_db*/ None));
    let live = LiveThread::resume(store, ThreadHistoryMode::Legacy, fixture.resume.clone()).await.expect("reopen");
    assert!(live.sync_native_history(&fixture.session, checkpoint.version.clone(), items.clone()).await.is_err(), "old writer epoch cannot append");
    let session = live.open_native_checkpoint(fixture.session.binding().clone(), NativeCheckpointOpenMode::Recover, fixture.host.clone()).await.expect("original recovery session");
    live.sync_native_history(&session, checkpoint.version, items.clone()).await.expect("repair complete prefix");
    let output = live.load_history(false).await.expect("canonical reader").items.into_iter().filter_map(|item| match item { RolloutItem::ResponseItem(item) => Some(item.item), _ => None }).collect::<Vec<_>>();
    assert_eq!(output, items);
    live.shutdown().await.expect("shutdown");
}

#[tokio::test]
async fn duplicate_changed_reordered_or_cross_turn_items_are_held_without_append() {
    for mutation in ["duplicate", "changed", "reordered", "cross-turn", "foreign-assistant"] {
        let fixture = Fixture::new().await;
        let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
        let items = fixture.items();
        let existing = match mutation {
            "duplicate" => vec![items[0].clone(), items[0].clone()],
            "changed" => {
                let mut item = items[0].clone();
                if let ResponseItem::FunctionCall { arguments, .. } = &mut item { *arguments = "different content".to_owned(); }
                vec![item]
            }
            "reordered" => vec![items[1].clone()],
            "cross-turn" => {
                let mut item = serde_json::to_value(&items[0]).expect("item");
                item["internal_chat_message_metadata_passthrough"]["turn_id"] = json!("other-turn");
                vec![serde_json::from_value(item).expect("changed correlation")]
            }
            "foreign-assistant" => {
                let mut item = items[2].clone();
                item.set_id(Some(ResponseItemId::from_server("msg_foreign".to_owned())));
                vec![item]
            }
            _ => unreachable!(),
        };
        fixture.append_existing(&existing).await;
        let before = tokio::fs::read(&fixture.path).await.expect("history");
        assert!(fixture.live.sync_native_history(&fixture.session, checkpoint.version, items).await.is_err(), "{mutation}");
        assert_eq!(tokio::fs::read(&fixture.path).await.expect("history"), before);
        fixture.live.shutdown().await.expect("shutdown");
    }
}

#[tokio::test]
async fn malformed_and_partial_tail_are_not_skipped_or_truncated() {
    for tail in [b"{\"timestamp\":".as_slice(), b"{}\n".as_slice()] {
        let fixture = Fixture::new().await;
        let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
        let mut file = tokio::fs::OpenOptions::new().append(true).open(&fixture.path).await.expect("inject interrupted tail");
        file.write_all(tail).await.expect("tail");
        file.flush().await.expect("tail flush");
        drop(file);
        let before = tokio::fs::read(&fixture.path).await.expect("history");
        assert!(fixture.live.sync_native_history(&fixture.session, checkpoint.version, fixture.items()).await.is_err());
        assert_eq!(tokio::fs::read(&fixture.path).await.expect("history"), before);
        fixture.live.shutdown().await.expect("shutdown");
    }
}

#[tokio::test]
async fn stale_checkpoint_and_revoked_owner_cannot_project_even_valid_items() {
    let fixture = Fixture::new().await;
    let first = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    let second = fixture.checkpoint(NativeCheckpointExpected::Version(first.version.clone())).await;
    let before = tokio::fs::read(&fixture.path).await.expect("history");
    assert!(fixture.live.sync_native_history(&fixture.session, first.version, fixture.items()).await.is_err());
    *fixture.host.current.write().await = false;
    assert!(fixture.live.sync_native_history(&fixture.session, second.version, fixture.items()).await.is_err());
    assert_eq!(tokio::fs::read(&fixture.path).await.expect("history"), before);
    fixture.live.shutdown().await.expect("shutdown");
}

#[tokio::test]
async fn cancelled_waiter_keeps_original_guard_until_durable_projection_finishes() {
    let fixture = Fixture::new().await;
    let checkpoint = fixture.checkpoint(NativeCheckpointExpected::Absent).await;
    fixture.host.pause.store(true, Ordering::SeqCst);
    let live = fixture.live.clone();
    let session = fixture.session.clone();
    let version = checkpoint.version.clone();
    let items = fixture.items();
    let task = tokio::spawn(async move { live.sync_native_history(&session, version, items).await });
    fixture.host.acquired.notified().await;
    task.abort();
    assert!(task.await.expect_err("cancelled waiter").is_cancelled());
    assert!(fixture.host.current.try_write().is_err(), "original permit must outlive the cancelled caller");
    fixture.host.resume.notify_one();
    fixture.live.sync_native_history(&fixture.session, checkpoint.version, fixture.items()).await.expect("observe original append, no duplicate");
    assert_eq!(fixture.output().await, fixture.items());
    fixture.live.shutdown().await.expect("shutdown");
}
