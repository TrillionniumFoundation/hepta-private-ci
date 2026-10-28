use std::sync::Arc;

use codex_protocol::ThreadId;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::protocol::ThreadMemoryMode;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio::sync::Notify;
use tokio::sync::RwLock;

use super::*;
use crate::LiveThread;
use crate::NativeCheckpointPermit;
use crate::ResumeThreadParams;
use crate::ThreadPersistenceMetadata;
use crate::ThreadStoreFuture;
use crate::local::test_support::test_config;
use crate::local::test_support::write_session_file;
use crate::local::test_support::write_session_file_with_fork;

// This is a host-fence fixture, not Fleet/QueueStore or production authorization.
struct HostFence {
    current: Arc<RwLock<(u64, String)>>,
    original: NativeCheckpointBinding,
    admitted_head: (u64, String),
    acquired: Notify,
}

impl NativeCheckpointCurrentness for HostFence {
    fn acquire<'a>(
        &'a self,
        binding: &'a NativeCheckpointBinding,
    ) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async move {
            let guard = self.current.clone().read_owned().await;
            if binding != &self.original || *guard != self.admitted_head {
                return Err(conflict("host generation or lease is no longer current"));
            }
            self.acquired.notify_one();
            Ok(NativeCheckpointPermit::hold(guard))
        })
    }
}

struct Fixture {
    live: LiveThread,
    store: Arc<LocalThreadStore>,
    binding: NativeCheckpointBinding,
    authority: Arc<HostFence>,
    resume: ResumeThreadParams,
    home: TempDir,
}

impl Fixture {
    async fn new() -> Self {
        let home = TempDir::new().expect("temporary home");
        let thread_id = ThreadId::new();
        let path = write_session_file(
            home.path(),
            "2025-01-03T00-00-00",
            uuid::Uuid::parse_str(&thread_id.to_string()).expect("thread UUID"),
        )
        .expect("real rollout");
        let store = Arc::new(LocalThreadStore::new(
            test_config(home.path()),
            /*state_db*/ None,
        ));
        let resume = ResumeThreadParams {
            thread_id,
            rollout_path: Some(path),
            history: None,
            include_archived: false,
            metadata: ThreadPersistenceMetadata {
                cwd: Some(home.path().to_path_buf()),
                model_provider: "test-provider".to_string(),
                memory_mode: ThreadMemoryMode::Disabled,
            },
        };
        let live = LiveThread::resume(store.clone(), ThreadHistoryMode::Legacy, resume.clone())
            .await
            .expect("live real store");
        let binding = NativeCheckpointBinding {
            thread_id,
            turn_id: "turn:original".to_string(),
            operation_id: "operation:original".to_string(),
            generation: 7,
            lease_id: "lease:original".to_string(),
        };
        let authority = Arc::new(HostFence {
            current: Arc::new(RwLock::new((binding.generation, binding.lease_id.clone()))),
            original: binding.clone(),
            admitted_head: (binding.generation, binding.lease_id.clone()),
            acquired: Notify::new(),
        });
        Self {
            live,
            store,
            binding,
            authority,
            resume,
            home,
        }
    }

    async fn session(&self, mode: NativeCheckpointOpenMode) -> NativeCheckpointSession {
        self.live
            .open_native_checkpoint(self.binding.clone(), mode, self.authority.clone())
            .await
            .expect("bound existing writer")
    }

    fn state(&self, response_id: &str) -> NativeCheckpointState {
        NativeCheckpointState {
            binding: self.binding.clone(),
            payload: serde_json::to_vec(&serde_json::json!({
                "pending_model": {"operation_id": "model:original", "body": "exact request bytes"},
                "provider_response_id": response_id,
                "submission_attempted": true,
                "cancel_requested": false
            }))
            .expect("state bytes"),
        }
    }
}

#[tokio::test]
async fn original_pending_operation_survives_real_store_reopen() {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    assert_eq!(
        fixture
            .live
            .load_native_checkpoint(&session)
            .await
            .expect("empty"),
        NativeCheckpointLoad::Missing
    );
    let first = fixture
        .live
        .commit_native_checkpoint(
            &session,
            NativeCheckpointExpected::Absent,
            fixture.state(""),
        )
        .await
        .expect("durable first state");
    let second = fixture
        .live
        .commit_native_checkpoint(
            &session,
            NativeCheckpointExpected::Version(first.version.clone()),
            fixture.state("response:original"),
        )
        .await
        .expect("durable next state");
    fixture.live.shutdown().await.expect("close writer");
    *fixture.authority.current.write().await = (8, "lease:successor".to_string());
    let reopened = Arc::new(LocalThreadStore::new(
        test_config(fixture.home.path()),
        /*state_db*/ None,
    ));
    let live = LiveThread::resume(reopened, ThreadHistoryMode::Legacy, fixture.resume.clone())
        .await
        .expect("reopen writer");
    let resumed = live
        .open_native_checkpoint(
            fixture.binding.clone(),
            NativeCheckpointOpenMode::Recover,
            fixture.authority.clone(),
        )
        .await
        .expect("recovery handle");
    // A successor may observe old pending state without treating its old lease
    // as authority to submit anything again.
    assert_eq!(
        live.load_native_checkpoint(&resumed)
            .await
            .expect("recover exact pending state"),
        NativeCheckpointLoad::Present(second.clone())
    );
    assert!(matches!(
        live.commit_native_checkpoint(
            &resumed,
            NativeCheckpointExpected::Version(second.version.clone()),
            fixture.state("response:original")
        )
        .await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    // This explicit host recovery decision relates the current head to the
    // unchanged original binding; it is a fixture seam, not production FinalUse.
    let recovery = Arc::new(HostFence {
        current: fixture.authority.current.clone(),
        original: fixture.binding.clone(),
        admitted_head: (8, "lease:successor".to_string()),
        acquired: Notify::new(),
    });
    let recovery_session = live
        .open_native_checkpoint(
            fixture.binding.clone(),
            NativeCheckpointOpenMode::Recover,
            recovery,
        )
        .await
        .expect("explicit host recovery permit");
    let recovered = live
        .commit_native_checkpoint(
            &recovery_session,
            NativeCheckpointExpected::Version(second.version),
            fixture.state("response:original"),
        )
        .await
        .expect("checkpoint original binding with current recovery permit");
    assert_eq!(recovered.state.binding, fixture.binding);
    live.shutdown().await.expect("close reopened writer");
}

#[tokio::test]
async fn forked_thread_does_not_inherit_parent_pending_state() {
    let fixture = Fixture::new().await;
    let parent = fixture.session(NativeCheckpointOpenMode::Create).await;
    let original = fixture
        .live
        .commit_native_checkpoint(
            &parent,
            NativeCheckpointExpected::Absent,
            fixture.state("response:original"),
        )
        .await
        .expect("parent pending state");
    let child_id = ThreadId::new();
    let path = write_session_file_with_fork(
        fixture.home.path(),
        fixture.home.path().join("sessions/2025/01/03"),
        "2025-01-03T01-00-00",
        uuid::Uuid::parse_str(&child_id.to_string()).expect("child UUID"),
        "inherited user context",
        Some("test-provider"),
        Some(uuid::Uuid::parse_str(&fixture.binding.thread_id.to_string()).expect("parent UUID")),
        ThreadHistoryMode::Legacy,
    )
    .expect("forked rollout");
    let mut resume = fixture.resume.clone();
    resume.thread_id = child_id;
    resume.rollout_path = Some(path);
    let child = LiveThread::resume(fixture.store.clone(), ThreadHistoryMode::Legacy, resume)
        .await
        .expect("child live writer");
    let mut binding = fixture.binding.clone();
    binding.thread_id = child_id;
    let session = child
        .open_native_checkpoint(
            binding,
            NativeCheckpointOpenMode::Create,
            fixture.authority.clone(),
        )
        .await
        .expect("child checkpoint namespace");
    assert_eq!(
        child
            .load_native_checkpoint(&session)
            .await
            .expect("child has no pending authority"),
        NativeCheckpointLoad::Missing
    );
    assert_eq!(
        fixture
            .live
            .load_native_checkpoint(&parent)
            .await
            .expect("parent retains original state"),
        NativeCheckpointLoad::Present(original)
    );
    child.shutdown().await.expect("close child");
    fixture.live.shutdown().await.expect("close parent");
}

#[tokio::test]
async fn existing_writer_lock_and_writer_instance_fence_are_reused() {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    let secondary = LocalThreadStore::new(test_config(fixture.home.path()), /*state_db*/ None);
    assert!(matches!(
        secondary.resume_thread(fixture.resume.clone()).await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    fixture
        .live
        .shutdown()
        .await
        .expect("release original writer lock");
    let replacement = LiveThread::resume(
        fixture.store.clone(),
        ThreadHistoryMode::Legacy,
        fixture.resume.clone(),
    )
    .await
    .expect("new writer instance");
    assert!(matches!(
        replacement
            .commit_native_checkpoint(
                &session,
                NativeCheckpointExpected::Absent,
                fixture.state("response:original")
            )
            .await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    replacement.shutdown().await.expect("close replacement");
}

#[tokio::test]
async fn changed_host_generation_or_lease_rejects_before_storage_publication() {
    for changed in [(8, "lease:original"), (7, "lease:expired")] {
        let fixture = Fixture::new().await;
        let session = fixture.session(NativeCheckpointOpenMode::Create).await;
        *fixture.authority.current.write().await = (changed.0, changed.1.to_string());
        assert!(matches!(
            fixture
                .live
                .commit_native_checkpoint(
                    &session,
                    NativeCheckpointExpected::Absent,
                    fixture.state("response:original")
                )
                .await,
            Err(ThreadStoreError::Conflict { .. })
        ));
        assert!(!fixture.home.path().join(DATABASE).exists());
        fixture.live.shutdown().await.expect("close writer");
    }
}

#[tokio::test]
async fn cas_and_exact_original_binding_reject_conflicting_writes() {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    let first = fixture
        .live
        .commit_native_checkpoint(
            &session,
            NativeCheckpointExpected::Absent,
            fixture.state("response:original"),
        )
        .await
        .expect("first commit");
    assert!(matches!(
        fixture
            .live
            .commit_native_checkpoint(
                &session,
                NativeCheckpointExpected::Absent,
                fixture.state("response:changed")
            )
            .await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    let mut substituted = fixture.state("response:changed");
    substituted.binding.generation += 1;
    assert!(matches!(
        fixture
            .live
            .commit_native_checkpoint(
                &session,
                NativeCheckpointExpected::Version(first.version.clone()),
                substituted
            )
            .await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    let mut wrong_hash = first.version.clone();
    wrong_hash.sha256 = "0".repeat(64);
    assert!(matches!(
        fixture
            .live
            .commit_native_checkpoint(
                &session,
                NativeCheckpointExpected::Version(wrong_hash),
                fixture.state("response:changed")
            )
            .await,
        Err(ThreadStoreError::Conflict { .. })
    ));
    assert_eq!(
        fixture
            .live
            .load_native_checkpoint(&session)
            .await
            .expect("unchanged original"),
        NativeCheckpointLoad::Present(first)
    );
    fixture.live.shutdown().await.expect("close writer");
}

#[tokio::test]
async fn corrupt_or_missing_recovery_state_never_becomes_new_work() {
    let fixture = Fixture::new().await;
    let missing = fixture.session(NativeCheckpointOpenMode::Recover).await;
    assert!(matches!(
        fixture.live.load_native_checkpoint(&missing).await,
        Err(ThreadStoreError::Internal { .. })
    ));
    assert!(!fixture.home.path().join(DATABASE).exists());
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    fixture
        .live
        .commit_native_checkpoint(
            &session,
            NativeCheckpointExpected::Absent,
            fixture.state("response:original"),
        )
        .await
        .expect("commit");
    let pool = database(&fixture.store, NativeCheckpointOpenMode::Recover)
        .await
        .expect("existing durable DB");
    sqlx::query("UPDATE checkpoint_rows SET payload=X'01'")
        .execute(pool)
        .await
        .expect("inject payload corruption");
    assert!(matches!(
        fixture.live.load_native_checkpoint(&session).await,
        Err(ThreadStoreError::Internal { .. })
    ));
    sqlx::query("DELETE FROM checkpoint_rows")
        .execute(pool)
        .await
        .expect("inject missing chain");
    assert!(matches!(
        fixture.live.load_native_checkpoint(&session).await,
        Err(ThreadStoreError::Internal { .. })
    ));
    fixture.live.shutdown().await.expect("close writer");
}

#[tokio::test]
async fn existing_invalid_database_is_not_initialized_or_replaced() {
    let fixture = Fixture::new().await;
    let bytes = b"existing database with corrupt bytes";
    tokio::fs::write(fixture.home.path().join(DATABASE), bytes)
        .await
        .expect("corrupt DB fixture");
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    assert!(matches!(
        fixture.live.load_native_checkpoint(&session).await,
        Err(ThreadStoreError::Internal { .. })
    ));
    assert_eq!(
        tokio::fs::read(fixture.home.path().join(DATABASE))
            .await
            .expect("unchanged corrupt DB"),
        bytes
    );
    fixture.live.shutdown().await.expect("close writer");
}

#[tokio::test]
async fn cancelled_waiter_does_not_release_owner_commit_permit() {
    let fixture = Fixture::new().await;
    let session = fixture.session(NativeCheckpointOpenMode::Create).await;
    fixture
        .live
        .load_native_checkpoint(&session)
        .await
        .expect("initialize sidecar");
    let pool = database(&fixture.store, NativeCheckpointOpenMode::Recover)
        .await
        .expect("durable DB");
    let mut blocker = pool.acquire().await.expect("blocking connection");
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *blocker)
        .await
        .expect("hold SQLite write slot");
    let store = fixture.store.clone();
    let state = fixture.state("response:original");
    let write_session = session.clone();
    let pending = tokio::spawn(async move {
        store
            .commit_native_checkpoint(&write_session, NativeCheckpointExpected::Absent, state)
            .await
    });
    tokio::time::timeout(
        std::time::Duration::from_secs(2),
        fixture.authority.acquired.notified(),
    )
    .await
    .expect("host permit acquired");
    assert!(fixture.authority.current.try_write().is_err());
    pending.abort();
    assert!(pending.await.expect_err("waiter cancelled").is_cancelled());
    assert!(fixture.authority.current.try_write().is_err());
    sqlx::query("ROLLBACK")
        .execute(&mut *blocker)
        .await
        .expect("release write slot");
    let NativeCheckpointLoad::Present(record) = fixture
        .live
        .load_native_checkpoint(&session)
        .await
        .expect("owner finishes commit after waiter cancellation")
    else {
        panic!("original operation must have a committed checkpoint");
    };
    assert_eq!(record.state, fixture.state("response:original"));
    assert!(fixture.authority.current.try_write().is_ok());
    fixture.live.shutdown().await.expect("close writer");
}
