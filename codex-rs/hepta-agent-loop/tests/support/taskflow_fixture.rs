#[cfg(feature = "context-v2")]
use super::v2_fixture;
use codex_hepta_agent_loop::*;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio_util::sync::CancellationToken;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}
pub(super) fn clock() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis()
        .try_into()
        .expect("clock fits")
}
pub(super) fn request(round: u32) -> ModelRequest {
    let payload = format!("original compiled context {round}");
    ModelRequest {
        request_id: id(&format!("model:{round}")),
        context_digest: Digest32::of_bytes(payload.as_bytes()),
        payload: payload.into(),
        input_tokens: 3,
        maximum_provider_input_tokens: 20,
        maximum_output_tokens: 8,
    }
}
pub(super) fn output(text: &str, calls: Vec<ToolCall>) -> ModelOutput {
    ModelOutput {
        request_id: id("model:0"),
        continuation_digest: Digest32::of_bytes(b"retained opaque provider continuation"),
        text: text.into(),
        calls,
        usage: Usage {
            input_tokens: 10,
            output_tokens: 2,
        },
    }
}
fn call() -> ToolCall {
    ToolCall {
        call_id: id("call:0"),
        name: id("owned.read"),
        arguments: "{}".into(),
    }
}

pub(super) struct Fixture {
    _temp: tempfile::TempDir,
    pub(super) layout: HeptaAgentLayout,
}
impl Fixture {
    pub(super) fn new() -> Self {
        let temp = tempfile::tempdir().expect("temporary root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            WorkspaceBinding::new(
                workspace.canonicalize().expect("canonical workspace"),
                &fleet_root,
            )
            .expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register").layout,
        }
    }

    pub(super) async fn store(&self) -> (AutomationStore, TaskFlowFence, TurnBinding) {
        let store = AutomationStore::open(&self.layout)
            .await
            .expect("existing automation store");
        let fence = TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent"),
            "native-owner",
            1,
            1,
            "native-fence-1",
        )
        .expect("existing owner fence");
        let definition = TaskFlowDefinition::new(
            "native-test",
            1,
            "work",
            vec![
                TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("work", "success"),
                TaskFlowEdgeSpec::new("work", "failure"),
            ],
            Vec::new(),
            Sha256Digest::for_bytes(b"fixture policy"),
        )
        .expect("definition");
        let now = clock();
        store
            .register_taskflow_definition(&definition, &fence, now)
            .await
            .expect("register definition");
        store
            .create_taskflow_run(
                "native-run",
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "native-thread",
                now,
            )
            .await
            .expect("create fixture run");
        store
            .claim_taskflow_run("native-run", &fence, now, 600_000)
            .await
            .expect("claim fixture run");
        transition(&store, &fence, TaskFlowTransition::Start).await;
        let binding = TurnBinding {
            run_id: id("native-run"),
            turn_id: id("turn:0"),
            generation: Generation::new(1).expect("generation"),
            admission_digest: Digest32::of_bytes(b"existing admission"),
            deadline_unix_ms: now + 120_000,
        };
        (store, fence, binding)
    }
}

pub(super) async fn transition(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    transition: TaskFlowTransition,
) {
    let run = store
        .taskflow_run("native-run")
        .await
        .expect("run")
        .expect("present");
    let command = TaskFlowCommand::new(
        "native-run",
        format!("fixture-transition-{}", run.revision),
        fence.clone(),
        run.revision,
        transition,
        clock(),
    )
    .expect("command");
    store
        .apply_taskflow_command(&command)
        .await
        .expect("transition");
}

/// This is a controlled source-owner fixture, not a production admission
/// verifier or model. With context-v2 it invokes the actual existing V2 compiler
/// and preparation API over the isolated fixture receipts in support/.
pub(super) struct Compiler {
    calls: Arc<AtomicUsize>,
    pub(super) repeat_initial: bool,
}
impl Compiler {
    pub(super) fn new(calls: &Arc<AtomicUsize>) -> Self {
        Self {
            calls: calls.clone(),
            repeat_initial: false,
        }
    }
}
impl TaskFlowContextPreparer for Compiler {
    async fn prepare_next(
        &mut self,
        _: &TurnBinding,
        initial: &ModelRequest,
        history: &[RetainedObservation],
    ) -> Result<ModelRequest> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        assert!(
            matches!(&history.last().expect("latest observation").transition,
            Transition::ToolCompleted { output, .. } if output == "result")
        );
        assert!(history.iter().any(|entry| matches!(&entry.transition,
            Transition::ModelCompleted(observed) if observed.continuation_digest == Digest32::of_bytes(b"retained opaque provider continuation")
                && observed.usage.input_tokens == 10)));
        if self.repeat_initial {
            return Ok(initial.clone());
        }
        #[cfg(feature = "context-v2")]
        {
            Ok(v2_fixture::request("model:1"))
        }
        #[cfg(not(feature = "context-v2"))]
        {
            Ok(request(1))
        }
    }
}

#[derive(Default)]
pub(super) struct Inference {
    response: Option<ModelOutput>,
    pub(super) opens: usize,
    pub(super) cancels: usize,
}
impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
    ) -> Result<ModelSession> {
        self.opens += 1;
        Ok(self
            .response
            .take()
            .map_or(ModelSession::Unresolved, ModelSession::Completed))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancels += 1;
        Ok(StopObservation::Stopped)
    }
}
#[derive(Default)]
pub(super) struct Effects {
    pub(super) keys: Vec<Digest32>,
    pub(super) cancels: usize,
}
impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        key: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        self.keys.push(key);
        Ok(EffectObservation::Unresolved)
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancels += 1;
        Ok(StopObservation::Stopped)
    }
}

pub(super) async fn pending_tool(
    owner: &mut impl TurnOwner,
    binding: &TurnBinding,
) -> (Frame, Digest32) {
    let mut model = Inference {
        response: Some(output("thinking", vec![call()])),
        ..Inference::default()
    };
    let mut effects = Effects::default();
    let outcome = run(
        owner,
        &mut model,
        &mut effects,
        binding,
        &Limits::default(),
        &CancellationToken::new(),
    )
    .await
    .expect("loop reaches existing unresolved tool");
    assert!(matches!(outcome, Outcome::Paused));
    let frame = owner.load(binding).await.expect("retained tool frame");
    (
        frame,
        *effects.keys.first().expect("actual loop operation key"),
    )
}
