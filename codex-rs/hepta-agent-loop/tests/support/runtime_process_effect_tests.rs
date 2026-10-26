//! Contract qualification uses explicit fixture owners/issuer. The separate
//! runtime composition canary must supply real process, log and artifact proof.

use super::*;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Default)]
struct ProcessState {
    dispatches: usize,
    cancellations: usize,
    request: Option<(ProviderEffectIntent, Vec<u8>)>,
    terminal: Option<RuntimeProcessResult>,
}

#[derive(Clone, Default)]
struct Process(Arc<Mutex<ProcessState>>);

impl RuntimeProcessOwner for Process {
    async fn dispatch(
        &self,
        intent: &ProviderEffectIntent,
        bytes: &[u8],
    ) -> RuntimeProcessObservation {
        let mut state = self.0.lock().expect("process fixture lock");
        state.dispatches += 1;
        assert!(
            state.request.is_none(),
            "fixture detects physical redispatch"
        );
        state.request = Some((intent.clone(), bytes.to_vec()));
        state.terminal.clone().map_or(
            RuntimeProcessObservation::Unresolved,
            RuntimeProcessObservation::Terminal,
        )
    }

    async fn observe(
        &self,
        intent: &ProviderEffectIntent,
        bytes: &[u8],
    ) -> RuntimeProcessObservation {
        let state = self.0.lock().expect("process fixture lock");
        if state.request.is_none() {
            return RuntimeProcessObservation::Unresolved;
        }
        assert_eq!(
            state.request.as_ref(),
            Some(&(intent.clone(), bytes.to_vec()))
        );
        state.terminal.clone().map_or(
            RuntimeProcessObservation::Unresolved,
            RuntimeProcessObservation::Terminal,
        )
    }

    async fn cancel(
        &self,
        intent: &ProviderEffectIntent,
        bytes: &[u8],
    ) -> RuntimeProcessObservation {
        let mut state = self.0.lock().expect("process fixture lock");
        if state.request.is_none() {
            return RuntimeProcessObservation::Unresolved;
        }
        assert_eq!(
            state.request.as_ref(),
            Some(&(intent.clone(), bytes.to_vec()))
        );
        state.cancellations += 1;
        // Deliberately overclaims: the adapter must independently observe the
        // original owner; this reply alone may never terminalize cancellation.
        RuntimeProcessObservation::Terminal(result(
            RuntimeProcessStatus::Failed,
            "cancel reply only",
        ))
    }
}

fn result(status: RuntimeProcessStatus, stdout: &str) -> RuntimeProcessResult {
    RuntimeProcessResult {
        status,
        job_identity_digest: Sha256Digest::for_bytes(b"fixture original job"),
        owner_receipt_digest: Sha256Digest::for_bytes(b"fixture terminal witness"),
        output: serde_json::json!({"stdout":stdout, "stderr":"", "artifacts":[]}).to_string(),
    }
}

fn prebound(
    frame: &Frame,
    intent: &AuthorizedEffectIntent,
    fence: &TaskFlowFence,
    grant: &SignedFinalUseGrant,
) -> PreboundRuntimeProcessEffect {
    PreboundRuntimeProcessEffect::new(
        frame,
        intent.clone(),
        call(frame).arguments.as_bytes().to_vec(),
        fence.clone(),
        grant.clone(),
        "fixture-process-dispatch".into(),
    )
    .expect("original admitted process")
}

struct OutputContext;
impl TaskFlowContextPreparer for OutputContext {
    async fn prepare_next(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
        history: &[RetainedObservation],
    ) -> codex_hepta_agent_loop::Result<ModelRequest> {
        let Some(RetainedObservation {
            transition: Transition::ToolCompleted { output, .. },
            ..
        }) = history.last()
        else {
            return Err(codex_hepta_agent_loop::Error::Contract(
                "fixture requires process output",
            ));
        };
        let value: serde_json::Value = serde_json::from_str(output).expect("output JSON");
        assert_eq!(value["schema"], "hepta-native-runtime-process:v1");
        assert_eq!(value["output"]["stdout"], "real owner fixture stdout");
        Ok(ModelRequest {
            request_id: id("fixture-model:1"),
            payload: output.clone().into(),
            context_digest: Digest32::of_bytes(output.as_bytes()),
            input_tokens: output.len() as u64,
            maximum_provider_input_tokens: 4096,
            maximum_output_tokens: 256,
        })
    }
}

#[tokio::test]
async fn output_is_bound_to_original_receipt_cursor_and_replay() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    assert!(automation_status_effect_run_id(&frame).is_err());
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    process.0.lock().expect("lock").terminal = Some(result(
        RuntimeProcessStatus::Succeeded,
        "real owner fixture stdout",
    ));
    let admitted = prebound(&frame, &intent, &fence, &grant);
    let key = admitted.operation_key();
    let mut effects = RuntimeProcessEffectOwner::new(&store, &authority, process.clone(), admitted);
    let observed = effects
        .execute_or_observe(&frame.binding, key, call(&frame))
        .await
        .expect("authorized dispatch");
    let EffectObservation::Completed(output) = &observed else {
        panic!("terminal output");
    };
    let value: serde_json::Value = serde_json::from_str(output).expect("JSON");
    assert_eq!(value["output"]["stdout"], "real owner fixture stdout");
    assert_eq!(value["native_operation_key"], key.to_string());
    assert!(!output.contains(&fence.fencing_token));
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        OutputContext,
    )
    .await
    .expect("same original turn");
    let next = turn
        .commit(
            &frame,
            Transition::ToolCompleted {
                operation_key: key,
                output: output.clone(),
            },
        )
        .await
        .expect("output and cursor committed atomically");
    assert!(matches!(next.phase, Phase::Model(_)));
    assert_eq!(
        store
            .taskflow_run(NATIVE_RUN)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Running
    );
    drop(turn);
    drop(effects);
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen original database");
    let mut effects = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process.clone(),
        prebound(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("read original result"),
        observed
    );
    process.0.lock().expect("lock").terminal = Some(result(
        RuntimeProcessStatus::Succeeded,
        "changed output bytes",
    ));
    assert!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .is_err()
    );
    assert_eq!(process.0.lock().expect("lock").dispatches, 1);
}

#[tokio::test]
async fn lost_reply_reopens_original_attempt_without_a_new_dispatch() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    let admitted = prebound(&frame, &intent, &fence, &grant);
    let key = admitted.operation_key();
    let mut effects = RuntimeProcessEffectOwner::new(&store, &authority, process.clone(), admitted);
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("accepted but unresolved"),
        EffectObservation::Unresolved
    );
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Indeterminate
    );
    drop(effects);
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen original database");
    let mut effects = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process.clone(),
        prebound(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("still unresolved"),
        EffectObservation::Unresolved
    );
    process.0.lock().expect("lock").terminal = Some(result(
        RuntimeProcessStatus::Succeeded,
        "late original stdout",
    ));
    assert!(matches!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("recover original"),
        EffectObservation::Completed(_)
    ));
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert_eq!(process.0.lock().expect("lock").dispatches, 1);
}

#[tokio::test]
async fn cancellation_requires_independent_original_terminal_observation() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    let admitted = prebound(&frame, &intent, &fence, &grant);
    let key = admitted.operation_key();
    let mut effects = RuntimeProcessEffectOwner::new(&store, &authority, process.clone(), admitted);
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("dispatch"),
        EffectObservation::Unresolved
    );
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("original native cancellation owner");
    let cancelling = turn
        .commit(&frame, Transition::CancelRequested)
        .await
        .expect("durable native cancellation first");
    assert_eq!(cancelling.phase, Phase::CancelRequested);
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("request original cancel"),
        StopObservation::Unresolved
    );
    assert_eq!(
        turn.observe().await.expect("original cursor").frame.phase,
        Phase::CancelRequested
    );
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Indeterminate
    );
    process.0.lock().expect("lock").terminal = Some(result(
        RuntimeProcessStatus::Failed,
        "original cancellation witnessed",
    ));
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("observe actual stop"),
        StopObservation::Stopped
    );
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Failed
    );
    let state = process.0.lock().expect("lock");
    assert_eq!(state.dispatches, 1);
    assert_eq!(state.cancellations, 2);
}

#[tokio::test]
async fn changed_tool_and_cancel_identity_never_contact_runtime() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    let admitted = prebound(&frame, &intent, &fence, &grant);
    let key = admitted.operation_key();
    let mut effects = RuntimeProcessEffectOwner::new(&store, &authority, process.clone(), admitted);
    let mut changed = call(&frame).clone();
    changed.arguments.push(' ');
    assert!(
        effects
            .execute_or_observe(&frame.binding, key, &changed)
            .await
            .is_err()
    );
    let mut changed_binding = frame.binding.clone();
    changed_binding.turn_id = id("different-turn");
    assert!(effects.cancel(&changed_binding).await.is_err());
    assert!(effects.cancel(&frame.binding).await.is_err());
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("original native cancellation owner");
    turn.commit(&frame, Transition::CancelRequested)
        .await
        .expect("durable native cancellation");
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("original admission atomically cancelled"),
        StopObservation::Stopped
    );
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("original run")
            .expect("present")
            .state,
        TaskFlowRunState::Cancelled
    );
    drop(effects);
    let mut effects = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process.clone(),
        prebound(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("original cancellation replay"),
        StopObservation::Stopped
    );
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("fresh contact disabled"),
        EffectObservation::Unresolved
    );
    let state = process.0.lock().expect("lock");
    assert_eq!(state.dispatches, 0);
    assert_eq!(state.cancellations, 0);
}

#[path = "runtime_process_admission_race_tests.rs"]
mod admission_race_tests;
