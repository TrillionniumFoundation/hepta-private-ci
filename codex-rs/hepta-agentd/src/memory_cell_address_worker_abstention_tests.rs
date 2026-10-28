//! Real Python and control-socket regression for the typed host time boundary.
//! No classifier, model, fixture corpus or quality threshold is changed here.

use std::sync::Arc;

use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_memory::CognitiveScope;
use pretty_assertions::assert_eq;
use serde_json::Value;

use crate::AgentdMemoryCellRuntimeV1;
use crate::MemoryCellAddressResolverV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::request;

use super::MemoryCellAddressWorkerV1;
use super::test_support::WorkerFixture;

#[tokio::test]
async fn multiple_cutoffs_abstain_without_masking_a_real_worker_failure() {
    let owner = ControlFixture::new().await;
    let snapshot = owner.snapshot().await;
    let release = ReleaseFixture::new(&snapshot);
    let fixture = WorkerFixture::new();
    let worker = Arc::new(
        MemoryCellAddressWorkerV1::start(fixture.config)
            .await
            .unwrap(),
    );
    let resolver: Arc<dyn MemoryCellAddressResolverV1> = worker.clone();
    owner
        .state
        .attach_memory_cells(Arc::new(
            AgentdMemoryCellRuntimeV1::new(
                owner.state.identity().agent_id.clone(),
                /*spawn_generation*/ 1,
                CognitiveScope::AgentPrivate,
                Arc::clone(&release.host),
                resolver,
            )
            .unwrap(),
        ))
        .unwrap();
    owner.ready();
    let before = worker.metrics();
    let mut query = request(snapshot.scope().clone());
    for text in [
        "Read saved samples at 2000-01-01 and 2000-02-01.",
        "读取20000101和20000201的已存记录。",
    ] {
        query.text = text.to_string();
        assert!(worker.resolve(&query, &snapshot).await.unwrap().is_none());
        let readout = owner.client.memory_cell_read(query.clone()).await.unwrap();
        readout.validate().unwrap();
        assert_eq!(
            (
                readout.status,
                readout.operation,
                readout.value,
                readout.source_ids,
                readout.cell_digests
            ),
            (
                MemoryReadStatusV1::Abstain,
                None,
                Value::Null,
                vec![],
                vec![]
            )
        );
        assert_eq!(
            readout.reason.as_deref(),
            Some("address resolver declined the request")
        );
    }
    let after = worker.metrics();
    assert_eq!(
        (
            after.attempted_requests - before.attempted_requests,
            after.host_time_abstentions - before.host_time_abstentions,
            after.validated_responses - before.validated_responses
        ),
        (4, 4, 0)
    );
    assert_eq!(
        (after.stdin_bytes, after.stdout_bytes, after.process_starts),
        (
            before.stdin_bytes,
            before.stdout_bytes,
            before.process_starts
        )
    );

    // The unchanged actual Python wire fixture reports unavailable. Both calls
    // must remain errors, not be relabeled as a valid unsupported request.
    query.text = "unavailable".to_string();
    assert_eq!(
        worker.resolve(&query, &snapshot).await.unwrap_err(),
        "address worker reported unavailable"
    );
    let failed = owner.client.memory_cell_read(query.clone()).await.unwrap();
    failed.validate().unwrap();
    assert_eq!(
        (
            failed.status,
            failed.operation,
            failed.value,
            failed.source_ids,
            failed.cell_digests
        ),
        (
            MemoryReadStatusV1::Unavailable,
            None,
            Value::Null,
            vec![],
            vec![]
        )
    );
    assert_eq!(
        failed.reason.as_deref(),
        Some("configured address resolver is unavailable")
    );
    assert_eq!(
        worker.metrics().host_time_abstentions,
        after.host_time_abstentions
    );

    // A later genuine worker rejection still uses the pipe and its validated
    // response counter; it does not become a synthetic host abstention.
    query.text = "decline".to_string();
    assert!(worker.resolve(&query, &snapshot).await.unwrap().is_none());
    let declined = owner.client.memory_cell_read(query).await.unwrap();
    assert_eq!(declined.status, MemoryReadStatusV1::Abstain);
    let final_metrics = worker.metrics();
    assert_eq!(
        (
            final_metrics.attempted_requests - before.attempted_requests,
            final_metrics.host_time_abstentions - before.host_time_abstentions,
            final_metrics.validated_responses - before.validated_responses
        ),
        (8, 4, 2)
    );
    owner.finish().await;
}
