//! Cancellation and capacity through the real signed ingress and blocking lane.

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

use super::*;

struct BlockingModel {
    inner: cell::Model,
    entered: Arc<Notify>,
    release: std::sync::mpsc::Receiver<()>,
}

impl NeuronInferenceControlPort for BlockingModel {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let receipt = self.inner.execute_feature(request);
        self.entered.notify_one();
        self.release
            .recv_timeout(Duration::from_secs(10))
            .map_err(|_| NeuronModelError::Indeterminate)?;
        receipt
    }
}

impl CellInferenceReadbackPortV1 for BlockingModel {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.inner.read_feature(request)
    }
}

#[test]
fn bootstrap_rejects_a_writer_outside_the_process_running_generation() -> anyhow::Result<()> {
    let runtime = runtime_fixture();
    for generation in [
        runtime.identity.spawn_generation,
        runtime.identity.spawn_generation + 2,
    ] {
        let (definition, bindings) = configuration();
        let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
        let calls = Arc::clone(&model.calls);
        let cells = crate::AgentdCircuitCellOwnerV1::new(
            crate::CircuitCellRegistryV1::new(definition, bindings)?,
            CellPartitionOwnerV1::new(
                /*max_partitions*/ 1, /*max_receipts_per_partition*/ 1,
            )?,
            model,
            cell::Encoder,
        );
        let fence = TaskFlowFence::new(
            runtime.identity.agent_id.clone(),
            "wrong-epoch-owner",
            /*owner_epoch*/ 1,
            generation,
            "wrong-epoch-fence",
        )?;
        let result = crate::circuit_task_channel_v1(
            &runtime.identity,
            fence,
            cells,
            Inputs(BTreeMap::new()),
            || crate::CircuitCellTimeV1 {
                circuit_millis: 20,
                cell_micros: 20,
            },
            /*capacity*/ 1,
        );
        assert!(matches!(result, Err(crate::AgentdError::Invalid(_))));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn abandoned_request_keeps_lane_and_queue_bounded_until_real_work_stops() -> anyhow::Result<()>
{
    let inner = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = Arc::clone(&inner.calls);
    let entered = Arc::new(Notify::new());
    let (release, receive) = std::sync::mpsc::channel();
    let model = BlockingModel {
        inner,
        entered: Arc::clone(&entered),
        release: receive,
    };
    let mut f = fixture_with_model(/*lose_ack*/ false, /*expire*/ false, model, calls).await?;
    let state = Arc::clone(&f.runtime.state);
    let objective = f.request.clone();
    let caller = tokio::spawn(async move {
        state
            .response(
                /*request_id*/ 1,
                /*spawn_generation*/ 1,
                AgentdMethod::ObjectiveStart { request: objective },
            )
            .await
    });
    timeout(Duration::from_secs(5), entered.notified())
        .await
        .expect("original native request reached its blocked model");
    let handle = f
        .runtime
        .state
        .circuit_task
        .get()
        .expect("attached handle")
        .clone();
    assert_eq!(handle.pending_count(), 1);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    caller.abort();
    assert_eq!(
        handle.pending_count(),
        1,
        "dropping the caller does not release its lane"
    );

    let record = f.invocation.records.lock().expect("original record")[0].clone();
    let request = f.invocation.build(&f.runtime.identity, &record)?;
    let mut queued = Vec::new();
    for _ in 0..4 {
        let handle = handle.clone();
        let request = request.clone();
        let record = record.clone();
        queued.push(tokio::spawn(
            async move { handle.submit(request, record).await },
        ));
    }
    timeout(Duration::from_secs(5), async {
        while handle.pending_count() != 5 {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("one active and four queued requests");
    assert_eq!(
        handle.submit(request, record).await,
        Err(crate::CircuitTaskErrorV1::QueueFull)
    );
    assert_eq!(handle.pending_count(), 5);
    f.cancellation.cancel();
    assert_eq!(
        handle.pending_count(),
        5,
        "cancellation does not detach the blocked owner"
    );
    assert!(f.runtime.state.circuit_task_drain_blockers().await? > 0);
    release.send(()).expect("finish the original model contact");
    f.stop().await;
    for call in queued {
        assert!(
            call.await?.is_err(),
            "cancelled queued work cannot enter another Cell"
        );
    }
    assert!(caller.await.expect_err("abandoned caller").is_cancelled());
    assert_eq!(
        (handle.pending_count(), f.calls.load(Ordering::SeqCst)),
        (0, 1)
    );
    assert!(f.invocation.receipts.lock().expect("results").is_empty());
    assert_eq!(
        f.store
            .bounded_circuit_run(RUN)
            .await?
            .expect("retained Circuit")
            .unresolved(),
        1
    );
    assert!(
        f.runtime.state.circuit_task_drain_blockers().await? > 0,
        "the durable unresolved task remains a blocker after the worker exits"
    );
    f.store.close().await;
    Ok(())
}
