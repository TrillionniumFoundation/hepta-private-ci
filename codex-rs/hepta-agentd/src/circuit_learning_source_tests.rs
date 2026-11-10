//! Real signed ingress and original file/SQLite readers; the model and keys
//! remain explicit fixtures, not production learning-owner qualification.

use anyhow::Context;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use pretty_assertions::assert_eq;

use super::*;

async fn completed_source() -> anyhow::Result<(Fixture, LearningIterationRequestV1)> {
    let f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let state = &f.runtime.state;
    state.attach_circuit_learning_source(StableId::new(RUN)?)?;
    state
        .response(
            1,
            1,
            AgentdMethod::ObjectiveStart {
                request: f.request.clone(),
            },
        )
        .await?;
    let intent = f
        .store
        .circuit_learning_delivery(RUN)
        .await
        .map_err(|error| anyhow::anyhow!("original source outbox: {error:?}"))?
        .context("original source completion is unavailable")?
        .intent;
    let (_directory, _identity, coordinator) =
        crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
    let mut request = coordinator.snapshot().request.clone();
    request.agent_id = StableId::new(state.identity().agent_id.as_str())?;
    request.source_run_id = StableId::new(RUN)?;
    request.operation_id = StableId::new(intent.operation_id)?;
    request.completed_task_receipt = intent.completed_task_receipt.as_str().parse()?;
    request.envelope.objective_digest = intent.objective_digest.as_str().parse()?;
    Ok((f, request))
}

#[tokio::test]
async fn original_learning_source_joins_signed_objective_and_committed_circuit_without_writes()
-> anyhow::Result<()> {
    let (mut f, request) = completed_source().await?;
    let path = f
        .runtime
        .identity
        .home_root
        .join("objective-run-start-v1/journal.bin");
    let original = fs::read(&path)?;
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    for _ in 0..2 {
        f.runtime
            .state
            .require_circuit_learning_source(&request)
            .await?;
    }
    assert_eq!(fs::read(path)?, original);
    assert_eq!(
        f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap(),
        pending
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    f.stop().await;
    Ok(())
}

#[tokio::test]
async fn original_learning_source_rejects_foreign_operation_result_objective_and_agent()
-> anyhow::Result<()> {
    let (mut f, request) = completed_source().await?;
    for field in ["operation", "result", "objective", "agent", "run"] {
        let mut changed = request.clone();
        match field {
            "operation" => changed.operation_id = StableId::new("another.operation")?,
            "result" => changed.completed_task_receipt = cell::d("another result"),
            "objective" => changed.envelope.objective_digest = cell::d("another objective"),
            "agent" => changed.agent_id = StableId::new("another.agent")?,
            "run" => changed.source_run_id = StableId::new("another.run")?,
            _ => unreachable!(),
        }
        assert!(
            f.runtime
                .state
                .require_circuit_learning_source(&changed)
                .await
                .is_err(),
            "{field}"
        );
    }
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    assert_eq!(pending[0].request_digest, None);
    assert_eq!(pending[0].acknowledged_head, None);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    f.stop().await;
    Ok(())
}

#[tokio::test]
async fn original_learning_source_revalidates_current_issuer_after_prior_success()
-> anyhow::Result<()> {
    let (mut f, request) = completed_source().await?;
    let state = &f.runtime.state;
    state.require_circuit_learning_source(&request).await?;
    let path = f.runtime.identity.home_root.join("circuit-trust.json");
    let mut trust: Value = serde_json::from_slice(&fs::read(&path)?)?;
    trust["revoked"] = json!(true);
    fs::write(&path, serde_json::to_vec(&trust)?)?;
    assert!(state.require_circuit_learning_source(&request).await.is_err());
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    assert_eq!(pending[0].request_digest, None);
    assert_eq!(pending[0].acknowledged_head, None);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    f.stop().await;
    Ok(())
}

#[tokio::test]
async fn original_learning_source_survives_new_consumer_generation_without_readmitting_old_task()
-> anyhow::Result<()> {
    let (mut f, request) = completed_source().await?;
    let record = f.invocation.records.lock().expect("record")[0].clone();
    f.stop().await;
    let mut generation = f.runtime.state.current_generation()?;
    for lifecycle in [
        AgentLifecycle::Draining,
        AgentLifecycle::Stopped,
        AgentLifecycle::Starting,
    ] {
        generation = f
            .runtime
            .registry
            .compare_and_transition(&f.runtime.identity.agent_id, generation, lifecycle)?
            .generation;
    }
    let mut identity = f.runtime.identity.clone();
    identity.spawn_generation = generation;
    let state = Arc::new(AgentdState::new(
        identity.clone(),
        f.runtime.registry.clone(),
        /*event_capacity*/ 16,
    )?);
    let cognitive = codex_hepta_cognitive_store::DurableCognitiveStore::open(&identity.layout).await?;
    state.attach_cognitive_store(Arc::new(cognitive.clone()))?;
    state.mark_runtime_prerequisites_ready()?;
    f.runtime.registry.compare_and_transition(
        &identity.agent_id,
        generation,
        AgentLifecycle::Running,
    )?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    state.attach_automation_store(f.store.clone())?;
    // Retain the original source owners, rather than manufacturing new
    // publications. This is a consumer-generation test, not process restart.
    assert!(state.authbus.set(Arc::clone(f.runtime.state.authbus.get().expect("original issuer"))).is_ok());
    assert!(state.objective_runtime.set(Arc::clone(f.runtime.state.objective_runtime.get().expect("original journal"))).is_ok());
    state.attach_circuit_learning_source(request.source_run_id.clone())?;
    assert_ne!(record.snapshot.generation, state.current_generation()?);
    assert!(state.require_current_run_start(&record).is_err());
    state.require_circuit_learning_source(&request).await?;
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    assert_eq!(pending[0].request_digest, None);
    assert_eq!(pending[0].acknowledged_head, None);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    cognitive.close().await;
    Ok(())
}
