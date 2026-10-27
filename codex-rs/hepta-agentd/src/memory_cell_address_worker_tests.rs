use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_memory::CognitiveScope;
use serde_json::json;

use crate::MemoryCellAddressResolverV1;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::record;
use crate::memory_cell_test_support::request;

use super::MemoryCellAddressWorkerV1;
use super::test_support::WorkerFixture;

#[tokio::test]
async fn actual_python_worker_preserves_canonical_hashes_serializes_calls_and_reports_pipe_cost() {
    let owner = ControlFixture::new().await;
    let snapshot = owner.snapshot().await;
    let fixture = WorkerFixture::new();
    let worker = MemoryCellAddressWorkerV1::start(fixture.config).await.unwrap();
    let mut first = request(snapshot.scope().clone()); first.text = "Unicode 测试😀 and exact request spelling".to_string();
    let mut second = first.clone(); second.text = "needs-alias".to_string();
    let (one, two) = tokio::join!(worker.resolve(&first, &snapshot), worker.resolve(&second, &snapshot));
    assert_eq!(one.unwrap().unwrap().request, first);
    assert_eq!(two.unwrap().unwrap().request, second);
    let mut rejected = first.clone(); rejected.text = "decline".to_string();
    assert!(worker.resolve(&rejected, &snapshot).await.unwrap().is_none());
    let mut flooded = first; flooded.text = "stderr-flood".to_string();
    assert_eq!(worker.resolve(&flooded, &snapshot).await.unwrap().unwrap().operation, MemoryOperationV1::Apply);
    let metrics = worker.metrics();
    assert_eq!((metrics.attempted_requests, metrics.validated_responses, metrics.process_starts), (4, 4, 1));
    assert!(metrics.stdin_bytes > 1_000 && metrics.stdout_bytes > 1_000 && metrics.host_request_nanoseconds > 0);
    assert_eq!((metrics.reported_cpu_nanoseconds, metrics.reported_wall_nanoseconds), (4_000_000, 8_000_000));
    owner.finish().await;
}

#[tokio::test]
async fn malicious_python_decisions_are_rejected_and_the_process_is_not_reused() {
    let owner = ControlFixture::new().await;
    let snapshot = owner.snapshot().await;
    let fixture = WorkerFixture::new();
    let worker = MemoryCellAddressWorkerV1::start(fixture.config).await.unwrap();
    let good = request(snapshot.scope().clone());
    let attacks = ["authority", "unknown", "wrong-query", "wrong-request", "wrong-model", "wrong-registry",
        "bad-plan", "substitute", "missing-nullable", "nonfinite", "duplicate", "duplicate-score", "oversize", "incomplete", "unsolicited", "unavailable"];
    for attack in attacks {
        let mut bad = good.clone(); bad.text = attack.to_string();
        assert!(worker.resolve(&bad, &snapshot).await.is_err(), "accepted malformed worker case {attack}");
        assert_eq!(worker.resolve(&good, &snapshot).await.unwrap().unwrap().request, good);
    }
    assert_eq!(worker.metrics().process_starts, attacks.len() as u64 + 1);
    owner.finish().await;
}

#[tokio::test]
async fn address_decision_cannot_reuse_an_older_real_owner_cut() {
    let owner = ControlFixture::new().await;
    let before = owner.snapshot().await;
    let fixture = WorkerFixture::new();
    let worker = MemoryCellAddressWorkerV1::start(fixture.config).await.unwrap();
    let mut query = request(before.scope().clone());
    assert!(worker.resolve(&query, &before).await.unwrap().is_some());
    owner.store.write_memory_cell(&owner.access(), &CognitiveScope::AgentPrivate,
        &record(MemoryCellKindV1::Event, /*effective_at*/ 30, json!(11)), MemoryCellWriteModeV1::Create).await.unwrap();
    let after = owner.snapshot().await;
    assert_ne!(before.owner_cut_digest(), after.owner_cut_digest());
    query.text = "old-cut".to_string();
    assert!(worker.resolve(&query, &after).await.is_err());
    query.text = "fresh request after failed cut binding".to_string();
    let result = worker.resolve(&query, &after).await.unwrap().unwrap();
    assert_eq!((result.request, result.owner_cut_digest), (query, after.owner_cut_digest()));
    assert_eq!(worker.metrics().process_starts, 2);
    owner.finish().await;
}

#[tokio::test]
async fn timeout_and_external_cancellation_discard_the_exact_inflight_child() {
    let owner = ControlFixture::new().await;
    let snapshot = owner.snapshot().await;
    let fixture = WorkerFixture::new();
    let worker = Arc::new(MemoryCellAddressWorkerV1::start(fixture.config).await.unwrap());
    let good = request(snapshot.scope().clone());
    let mut hung = good.clone(); hung.text = "hang".to_string();
    assert!(worker.resolve(&hung, &snapshot).await.is_err());
    assert!(worker.resolve(&good, &snapshot).await.unwrap().is_some());
    let sent = worker.metrics().stdin_bytes;
    let child_worker = Arc::clone(&worker);
    let child_snapshot = snapshot.clone();
    let pending = tokio::spawn(async move { child_worker.resolve(&hung, &child_snapshot).await });
    tokio::time::timeout(Duration::from_secs(1), async {
        while worker.metrics().stdin_bytes == sent { tokio::time::sleep(Duration::from_millis(1)).await; }
    }).await.unwrap();
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    assert!(worker.resolve(&good, &snapshot).await.unwrap().is_some());
    let metrics = worker.metrics();
    assert_eq!((metrics.attempted_requests, metrics.validated_responses, metrics.process_starts), (4, 2, 3));
    assert!(metrics.host_request_nanoseconds >= 1_500_000_000);
    owner.finish().await;
}

#[tokio::test]
async fn code_and_model_pins_are_checked_at_start_and_before_every_restart() {
    let mut missing = WorkerFixture::new();
    let importer = missing.config.worker_script.parent().unwrap().join("contracts.py");
    missing.config.code_pins.remove(&importer);
    assert!(MemoryCellAddressWorkerV1::start(missing.config).await.is_err());
    let changed = WorkerFixture::new();
    std::fs::write(changed.config.model_directory.join("manifest.json"), b"{}").unwrap();
    assert!(MemoryCellAddressWorkerV1::start(changed.config).await.is_err());
    let owner = ControlFixture::new().await;
    let snapshot = owner.snapshot().await;
    let fixture = WorkerFixture::new();
    let script = fixture.config.worker_script.clone();
    let worker = MemoryCellAddressWorkerV1::start(fixture.config).await.unwrap();
    let mut query = request(snapshot.scope().clone()); query.text = "exit".to_string();
    assert!(worker.resolve(&query, &snapshot).await.is_err());
    std::fs::write(script, "raise RuntimeError('changed code must never execute')\n").unwrap();
    query.text = "good".to_string();
    assert!(worker.resolve(&query, &snapshot).await.is_err());
    assert_eq!(worker.metrics().process_starts, 1);
    owner.finish().await;
}
