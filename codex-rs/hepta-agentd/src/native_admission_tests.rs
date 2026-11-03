//! Admission uses real original owners; no runtime or external effect is opened.

use pretty_assertions::assert_ne;

use super::*;
use crate::NativeTurnAdmission;
use crate::native_ports::NativeProductionPorts;
use codex_hepta_memory::ProductionEntryCurrentness;
use codex_hepta_native_agent::ModelPort;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn invalid_native_scope_preserves_original_run_and_queued_input() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    let mut handoff = fixture.handoff().await?;
    handoff.scope.final_scope_id = StableId::new("foreign:final-scope")?;
    let binding = fixture.anchor.queue.as_ref().context("original queue binding")?;
    let queued = fixture.queue.list_page(fixture.anchor.checkpoint.thread_id,
        /*offset*/ 0, /*limit*/ 16).await?;
    assert_eq!(queued.len(), 1);
    let queue_binding = fixture.queue.reserve_client_binding(fixture.anchor.checkpoint.thread_id,
        binding.client_id.clone(), binding.payload_sha256.clone(), fixture.payload.clone()).await?;
    assert!(matches!(&queue_binding, QueuedClientBindingReserveOutcome::Dispatching(_)));
    let history = serde_json::to_vec(&fixture.history().await?.items)?;

    let error = match fixture.native.run_turn(&agent(), handoff, &CancellationToken::new()).await {
        Ok(_) => anyhow::bail!("an invalid organ scope reached native execution"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("final payload scope"));
    assert_eq!(fixture.state.native_run_receipt(&fixture.run.run_id)?, fixture.run,
        "scope validation must precede consuming the coordinator dispatch");
    assert_eq!(fixture.queue.list_page(fixture.anchor.checkpoint.thread_id,
        /*offset*/ 0, /*limit*/ 16).await?, queued);
    assert_eq!(fixture.queue.reserve_client_binding(fixture.anchor.checkpoint.thread_id,
        binding.client_id.clone(), binding.payload_sha256.clone(), fixture.payload.clone()).await?, queue_binding,
        "invalid input cannot complete or re-admit its original queue binding");
    assert_eq!(serde_json::to_vec(&fixture.history().await?.items)?, history);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 0);
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    fixture.live.shutdown().await?;
    Ok(())
}

struct SameProcessCompiler;

impl NativeToolCompiler for SameProcessCompiler {
    fn compile(&self, call: &ToolCall) -> Result<ProcessStartParams> {
        ensure!(call.name == "same_process" && call.arguments == b"{}", "unexpected fixture tool");
        Ok(serde_json::from_value(json!({
            "host":"same-original-host", "executable":"/usr/bin/true", "args":[],
        }))?)
    }
}

#[tokio::test]
async fn independent_native_owners_keep_distinct_keys_and_exact_same_owner_retries() -> Result<()> {
    let endpoint = "http://127.0.0.1:9/v1/responses".to_owned();
    let mut first = Fixture::new(endpoint.clone()).await?;
    let mut second = Fixture::new_with_agent(endpoint,
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c82")?).await?;
    first.native.compiler = Arc::new(SameProcessCompiler);
    second.native.compiler = Arc::new(SameProcessCompiler);
    assert_eq!(first.run.run_id, second.run.run_id);
    assert_eq!(first.anchor.checkpoint.turn_id, second.anchor.checkpoint.turn_id);
    assert_ne!(first.writer.owner_agent_id(), second.writer.owner_agent_id());
    assert_ne!(first.anchor.checkpoint.thread_id, second.anchor.checkpoint.thread_id);
    let _first_active = first.state.dispatch_native_run(&first.run)?;
    let _second_active = second.state.dispatch_native_run(&second.run)?;
    let first_admission = first.native.admission(first.anchor.checkpoint.clone(), first.scope.clone(),
        &first.state.native_run_receipt(&first.run.run_id)?)?;
    let second_admission = second.native.admission(second.anchor.checkpoint.clone(), second.scope.clone(),
        &second.state.native_run_receipt(&second.run.run_id)?)?;
    let call = ToolCall { call_id: "same-local-call".to_owned(), name: "same_process".to_owned(), arguments: b"{}".to_vec() };
    assert_eq!(serde_json::to_vec(&first.native.compiler.compile(&call)?)?,
        serde_json::to_vec(&second.native.compiler.compile(&call)?)?);
    let admitted = first_admission.admit_tool(&first.initial.binding, &call).await?;
    let other = second_admission.admit_tool(&second.initial.binding, &call).await?;
    let repeated = first_admission.admit_tool(&first.initial.binding, &call).await?;
    assert_eq!((&admitted.intent, &admitted.arguments), (&repeated.intent, &repeated.arguments));
    assert_ne!(admitted.intent.idempotency_key, other.intent.idempotency_key,
        "owner-local run/turn/call ids cannot alias one shared runtime job");
    let mut first_params: ProcessStartParams = serde_json::from_slice(&admitted.arguments)?;
    let mut second_params: ProcessStartParams = serde_json::from_slice(&other.arguments)?;
    first_params.idempotency_key = None;
    second_params.idempotency_key = None;
    assert_eq!(serde_json::to_vec(&first_params)?, serde_json::to_vec(&second_params)?,
        "only the original owner domain distinguishes these otherwise identical tools");
    assert_eq!(first.writer.status(admitted.intent.idempotency_key.as_str()).await?, LocalOutcomeState::Queued);
    assert_eq!(second.writer.status(other.intent.idempotency_key.as_str()).await?, LocalOutcomeState::Queued);
    assert_eq!((first.issuer.grants.load(Ordering::SeqCst), second.issuer.grants.load(Ordering::SeqCst)), (0, 0));
    first.live.shutdown().await?;
    second.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn final_entry_rejects_another_live_run_or_scope_under_the_same_writer() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    let _first_active = fixture.state.dispatch_native_run(&fixture.run)?;
    let first = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(),
        &fixture.state.native_run_receipt(&fixture.run.run_id)?)?;

    // Admit and dispatch a second real coordinator run under the same owner.
    // Its live readiness must not make the first run's operation transferable.
    let recovery = fixture.state.native_recovery_record(&fixture.run.run_id)?;
    let mut snapshot: crate::AgentRunSnapshot = serde_json::from_value(serde_json::to_value(&recovery.snapshot)?)?;
    snapshot.run_id = "run.native.another".to_owned();
    fixture.state.response(/*request_id*/ 3, /*spawn_generation*/ 1,
        crate::AgentdMethod::RunStart { snapshot: snapshot.clone() }).await?;
    let admitted = fixture.state.native_run_receipt(&snapshot.run_id)?;
    fixture.state.response(/*request_id*/ 4, /*spawn_generation*/ 1, crate::AgentdMethod::RunAttachContext {
        expected_revision: admitted.revision, attachment: crate::AgentContextAttachment {
            run_id: snapshot.run_id.clone(), request_digest: snapshot.request_digest,
            objective_digest: snapshot.objective_digest, body_digest: snapshot.body_digest,
            artifact_set_digest: snapshot.artifact_set_digest, authority_epoch: snapshot.authority_epoch,
            generation: snapshot.generation, fence_digest: snapshot.fence_digest,
            deadline_ms: snapshot.deadline_ms, context_digest: recovery.context_digest,
            compilation_receipt_digest: recovery.compilation_receipt_digest,
        },
    }).await?;
    let second_run = fixture.state.native_run_receipt(&snapshot.run_id)?;
    let _second_active = fixture.state.dispatch_native_run(&second_run)?;
    let mut second_binding = fixture.anchor.checkpoint.clone();
    second_binding.operation_id = second_run.run_id.clone();
    second_binding.turn_id = "turn:native-another".to_owned();
    let second = fixture.native.admission(second_binding, fixture.scope.clone(),
        &fixture.state.native_run_receipt(&second_run.run_id)?)?;
    let mut other_scope = fixture.scope.clone();
    other_scope.cell_id = StableId::new("cell:native-another")?;
    let changed_scope = fixture.native.admission(fixture.anchor.checkpoint.clone(), other_scope,
        &fixture.state.native_run_receipt(&fixture.run.run_id)?)?;
    assert_eq!((fixture.state.require_native_effect(&fixture.run.run_id)?.phase,
        fixture.state.require_native_effect(&second_run.run_id)?.phase),
        (RunPhase::Dispatched, RunPhase::Dispatched));

    let exact_body = b"{\n \"model\":\"native-fixture-model\", \"stream\":true\n}";
    for (index, wrong) in [second, changed_scope].into_iter().enumerate() {
        assert_ne!(first.scope_digest, wrong.scope_digest);
        let request = first.admit_model(&fixture.initial.binding, index, exact_body).await?;
        let original = fixture.writer.resolve_operation_request(&request.operation_id,
            fixture.native.model.destination_id()).await?;
        assert_eq!((original.operation_subject_id.as_str(), original.payload_json.as_bytes()),
            (fixture.writer.owner_agent_id().as_str(), exact_body.as_slice()));
        first.verify_request(&original)?;
        assert!(wrong.verify_request(&original).is_err());
        let swapped = NativeProductionPorts { entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
            admission: wrong.clone(), model: fixture.native.model.clone(), runtime: fixture.native.runtime.clone(),
        };
        assert!(swapped.open(&request).await.is_err());
        assert_eq!((fixture.issuer.grants.load(Ordering::SeqCst), fixture.final_use.capacity()?.used_nonces),
            (index, 0), "the port rejects a cross-binding before requesting any grant");
        assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Queued);

        // Deliberately bypass that early port check to exercise the actual
        // transport's final seam using the original writer's real handoff.
        let (entry, observation) = fixture.native.host.begin_native_effect(
            fixture.native.model.destination_id(), &request.operation_id).await?;
        assert_eq!((fixture.issuer.grants.load(Ordering::SeqCst), fixture.final_use.capacity()?.used_nonces),
            (index + 1, 0), "preparation retains a signed grant without consuming FinalUse");
        let mut callbacks = 0;
        assert!(wrong.enter(entry.request(), &mut || { callbacks += 1; Ok(()) }).is_err());
        assert_eq!(callbacks, 0, "a mismatched scope cannot reach FinalUse consumption");
        let error = match fixture.native.model.open_effect_entry(entry, wrong.as_ref()).await {
            Ok(_) => anyhow::bail!("another run or scope reached the provider"),
            Err(error) => error,
        };
        assert!(error.to_string().contains("another native run or policy"));
        assert!(!observation.started(), "the prepared handoff never entered the effect");
        // Final owner rejection consumes no nonce. The original durable
        // operation nevertheless stays indeterminate and cannot be resent.
        assert_eq!((fixture.issuer.grants.load(Ordering::SeqCst), fixture.final_use.capacity()?.used_nonces),
            (index + 1, 0));
        assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Indeterminate);
        assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
        drop(observation);
        assert!(fixture.native.host.begin_native_effect(
            fixture.native.model.destination_id(), &request.operation_id).await.is_err(),
            "refusing the final owner must not reopen the original dispatch claim");
        assert_eq!((fixture.issuer.grants.load(Ordering::SeqCst), fixture.final_use.capacity()?.used_nonces),
            (index + 1, 0), "duplicate refusal must not request another grant or consume a nonce");
        assert_eq!(fixture.writer.resolve_operation_request(&request.operation_id,
            fixture.native.model.destination_id()).await?, original);
        assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Indeterminate);
        assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    }
    fixture.live.shutdown().await?;
    Ok(())
}
