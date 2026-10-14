//! These tests use the ORIGINAL SQLite CognitiveStore and its real
//! BEGIN IMMEDIATE source writer transaction; no mocked database receipts.
//! All witnesses are fixtures, NOT independently authorized production pins.
use super::*;
use crate::cognitive_test_support::{agent_id, layout, source};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::sync::mpsc;
use std::time::Duration;
use tempfile::TempDir;

#[tokio::test]
async fn amcn_shadow_sqlite_fence_checks_exact_current_cut_and_scope_before_work() {
    let tmp = TempDir::new().expect("isolated root");
    let owner = agent_id(221);
    let store = CognitiveStore::open(&layout(&tmp, &owner))
        .await
        .expect("original SQLite store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    store.append_source(&access, &source(scope.clone(), "first", "original source bytes"))
        .await
        .expect("original durable source");
    let cut = store.recovery_anchor().await.expect("complete current cut");
    let invoked = Arc::new(AtomicBool::new(false));
    let call = Arc::clone(&invoked);

    let answer = store.with_amcn_shadow_cognitive_cut(
        &access, &scope, &cut, || {
            call.store(true, Ordering::SeqCst);
            Ok::<_, CognitiveStoreError>(17_u64)
        }
    ).await.expect("exact original source cut held");
    assert_eq!(answer, 17);
    assert!(invoked.load(Ordering::SeqCst));
    assert!(!AMCN_SHADOW_COGNITIVE_FENCE_PRODUCTION_ACCEPTED);

    invoked.store(false, Ordering::SeqCst);
    let wrong = CognitiveAccess::agent_private(agent_id(222));
    let refused = store.with_amcn_shadow_cognitive_cut(&wrong, &scope, &cut, || {
        invoked.store(true, Ordering::SeqCst);
        Ok::<_, CognitiveStoreError>(())
    }).await;
    assert!(matches!(refused, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!invoked.load(Ordering::SeqCst));

    store.append_source(&access, &source(scope.clone(), "second", "new immutable source revision"))
        .await
        .expect("real mutation must change owner cut");
    let stale = store.with_amcn_shadow_cognitive_cut(&access, &scope, &cut, || {
        invoked.store(true, Ordering::SeqCst);
        Ok::<_, CognitiveStoreError>(())
    }).await;
    assert!(matches!(stale, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!invoked.load(Ordering::SeqCst));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn amcn_shadow_sqlite_fence_prevents_real_competing_source_writer_until_work_exits() {
    let tmp = TempDir::new().expect("isolated root");
    let owner = agent_id(223);
    let owner_layout = layout(&tmp, &owner);
    let first = CognitiveStore::open(&owner_layout).await.expect("first owner handle");
    let second = CognitiveStore::open(&owner_layout).await.expect("competing owner handle");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;

    first.append_source(&access, &source(scope.clone(), "seed", "seed fact"))
        .await
        .expect("seed source");
    let cut = first.recovery_anchor().await.expect("sealed original source cut");

    let (wake_writer, writer_ready) = mpsc::channel::<()>();
    let (attempt_tx, attempt_rx) = mpsc::channel::<()>();
    let (committed_tx, committed_rx) = mpsc::channel();
    let writer_access = access.clone();
    let writer_scope = scope.clone();
    let writer_thread = std::thread::spawn(move || {
        writer_ready.recv_timeout(Duration::from_secs(5)).expect("source writer wake");
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("separate source writer runtime");
        attempt_tx.send(()).expect("writer started");
        let result = runtime.block_on(second.append_source(
            &writer_access,
            &source(writer_scope, "racing-with-model", "concurrent source revision"),
        ));
        committed_tx.send(result).expect("write terminal observation");
    });

    let observed = first.with_amcn_shadow_cognitive_cut(
        &access, &scope, &cut, || {
            wake_writer.send(()).expect("start competing source writer");
            attempt_rx.recv_timeout(Duration::from_secs(5))
                .expect("source write attempt signaled");
            // SQLite BEGIN IMMEDIATE is still held by first. The competing
            // writer must not commit until our bounded model-like callback
            // has returned and the research transaction is rolled back.
            assert!(matches!(
                committed_rx.recv_timeout(Duration::from_millis(100)),
                Err(mpsc::RecvTimeoutError::Timeout)
            ), "SQLite source writer committed DURING the supposed source fence");
            Ok::<_, CognitiveStoreError>(99_u32)
        },
    ).await.expect("model-like callback under original SQLite transaction");
    assert_eq!(observed, 99);

    let result = committed_rx.recv_timeout(Duration::from_secs(10))
        .expect("competing source write completes after fence");
    assert!(result.is_ok(), "source may write only AFTER fence releases");
    writer_thread.join().expect("source writer thread");
    assert_ne!(
        first.recovery_anchor().await.expect("new source cut"),
        cut,
        "a committed source write changes the independently pinnable owner cut",
    );
    let callback_hit = Arc::new(AtomicBool::new(false));
    let observed_hit = Arc::clone(&callback_hit);
    let stale = first.with_amcn_shadow_cognitive_cut(&access, &scope, &cut, || {
        observed_hit.store(true, Ordering::SeqCst);
        Ok::<_, CognitiveStoreError>(())
    }).await;
    assert!(matches!(stale, Err(CognitiveStoreError::AccessDenied(_))));
    assert!(!callback_hit.load(Ordering::SeqCst));
}

#[tokio::test]
async fn amcn_shadow_sqlite_fence_callback_error_releases_writer_without_minting_authority() {
    let tmp = TempDir::new().expect("isolated root");
    let owner = agent_id(224);
    let store = CognitiveStore::open(&layout(&tmp, &owner)).await.expect("SQLite store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let cut = store.recovery_anchor().await.expect("empty source cut");
    let error = store.with_amcn_shadow_cognitive_cut(&access, &scope, &cut, || {
        Err::<(), _>(CognitiveStoreError::Invalid("model shadow rejected".into()))
    }).await;
    assert!(matches!(error, Err(CognitiveStoreError::Invalid(_))));
    store.append_source(&access, &source(scope, "new-after-error", "original after rejection"))
        .await.expect("error must have released original SQLite writer fence");
}
