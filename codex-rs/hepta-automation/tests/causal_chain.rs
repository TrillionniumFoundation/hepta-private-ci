#![allow(
    clippy::expect_used,
    reason = "causal-chain integration fixtures should fail loudly"
)]

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationEffectProvider;
use codex_hepta_automation::AutomationOccurrenceState;
use codex_hepta_automation::AutomationProviderObservation;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_automation::DurableStepExecutionRequest;
use codex_hepta_automation::EffectFuture;
use codex_hepta_automation::FinalUseAuthorityDecision;
use codex_hepta_automation::FinalUseAuthorityRequest;
use codex_hepta_automation::FinalUseAuthorityVerifier;
use codex_hepta_automation::ProviderDispatchOutcome;
use codex_hepta_automation::ProviderDispatchReceipt;
use codex_hepta_automation::ProviderDispatchRequest;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_automation::VerifiedFinalUseAuthority;
use codex_hepta_automation::deterministic_occurrence_id;
use codex_hepta_automation::execute_durable_taskflow_step;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const TASK_ID: &str = "019153a4-3088-7000-a56a-9b1964f75991";
const THREAD_ID: &str = "thread-causal-chain";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register agent").layout,
        }
    }
}

fn definition() -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "automation-causal",
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
        Sha256Digest::for_bytes(b"causal-policy"),
    )
    .expect("definition")
}

fn fence() -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "causal-owner",
        1,
        1,
        "causal-fence",
    )
    .expect("fence")
}

struct EchoVerifier;

impl FinalUseAuthorityVerifier for EchoVerifier {
    fn verify(
        &self,
        request: FinalUseAuthorityRequest,
    ) -> EffectFuture<'_, FinalUseAuthorityDecision> {
        Box::pin(async move {
            Ok(FinalUseAuthorityDecision::Granted {
                operation_id: request.operation_id,
                authority_epoch: request.authority_epoch,
                semantic_digest: request.semantic_digest,
                payload_digest: request.payload_digest,
                expires_at_ms: request.deadline_ms,
                verifier_receipt_digest: Sha256Digest::for_bytes(b"verified-authority"),
            })
        })
    }
}

#[derive(Default)]
struct CountingProvider {
    calls: AtomicUsize,
}

impl AutomationEffectProvider for CountingProvider {
    fn dispatch(
        &self,
        _request: ProviderDispatchRequest,
        _authority: &VerifiedFinalUseAuthority,
    ) -> EffectFuture<'_, ProviderDispatchOutcome> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Ok(ProviderDispatchOutcome::Observed(ProviderDispatchReceipt {
                receipt_digest: Sha256Digest::for_bytes(b"provider-receipt"),
                observation: AutomationProviderObservation::Succeeded,
            }))
        })
    }
}

#[tokio::test]
async fn queue_admission_is_non_terminal_and_taskflow_terminal_advances_once() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let mut draft = AutomationTaskDraft::new(
        THREAD_ID,
        "perform durable work",
        AutomationSchedule::Once,
        100,
        1,
    );
    draft.task_id = AutomationTaskId::parse(TASK_ID).expect("task id");
    store.create_task(&draft).await.expect("create task");

    let lease = store
        .claim_due(100, 1, 60_000)
        .await
        .expect("claim")
        .expect("due");
    let occurrence_id = deterministic_occurrence_id(draft.task_id, 1, 100).expect("occurrence id");
    let occurrence = store
        .causal_occurrence(&occurrence_id)
        .await
        .expect("read occurrence")
        .expect("occurrence");
    assert_eq!(occurrence.state, AutomationOccurrenceState::Materialized);

    let flow = definition();
    let owner = fence();
    store
        .register_taskflow_definition(&flow, &owner, 101)
        .await
        .expect("register definition");
    let run = store
        .ensure_occurrence_taskflow_run(
            &occurrence_id,
            &flow.workflow_id,
            flow.version,
            flow.definition_digest(),
            102,
        )
        .await
        .expect("ensure run");
    let claimed = store
        .claim_taskflow_run(&run.run_id, &owner, 103, 60_000)
        .await
        .expect("claim run");

    let intent = Sha256Digest::for_bytes(b"intent");
    let payload = Sha256Digest::for_bytes(b"payload");
    let provider = CountingProvider::default();
    let execution = DurableStepExecutionRequest {
        occurrence_id: occurrence_id.clone(),
        run_id: run.run_id.clone(),
        step_id: "work".to_string(),
        attempt: 1,
        intent_digest: intent.clone(),
        payload_digest: payload.clone(),
        authority: FinalUseAuthorityRequest {
            operation_id: "op-1".to_string(),
            authority_epoch: 1,
            semantic_digest: intent,
            payload_digest: payload.clone(),
            grant_payload_digest: payload,
            deadline_ms: 10_000,
        },
        command_id_prefix: "op-1".to_string(),
        now_ms: 104,
    };

    let first = execute_durable_taskflow_step(&store, &owner, &EchoVerifier, &provider, execution.clone())
        .await
        .expect("execute durable step");
    assert!(first.provider_dispatched);
    assert_eq!(first.step.state, TaskFlowStepState::Recorded);

    let replay = execute_durable_taskflow_step(&store, &owner, &EchoVerifier, &provider, execution)
        .await
        .expect("replay durable step");
    assert!(!replay.provider_dispatched);
    assert_eq!(provider.calls.load(Ordering::SeqCst), 1);

    let still_open = store
        .task(draft.task_id)
        .await
        .expect("read task")
        .expect("task");
    assert_eq!(still_open.state, AutomationTaskState::Enabled);
    assert_eq!(still_open.next_run_at_ms, None);

    let start = TaskFlowCommand::new(
        run.run_id.clone(),
        "run-start",
        owner.clone(),
        claimed.revision,
        TaskFlowTransition::Start,
        105,
    )
    .expect("start");
    let started = store
        .apply_taskflow_command(&start)
        .await
        .expect("start run");
    let succeed = TaskFlowCommand::new(
        run.run_id.clone(),
        "run-succeed",
        owner,
        started.revision,
        TaskFlowTransition::Succeed {
            output_digest: Sha256Digest::for_bytes(b"output"),
        },
        106,
    )
    .expect("succeed");
    store
        .apply_taskflow_command(&succeed)
        .await
        .expect("terminal run");

    let terminal = store
        .reconcile_occurrence_from_taskflow(&occurrence_id, 107)
        .await
        .expect("reconcile occurrence");
    assert_eq!(terminal.state, AutomationOccurrenceState::Succeeded);
    let completed = store
        .task(draft.task_id)
        .await
        .expect("read completed task")
        .expect("task");
    assert_eq!(completed.state, AutomationTaskState::Completed);

    // The scheduler lease remains a queue-admission journal. It is not the
    // semantic terminal source and cannot create a second occurrence.
    assert_eq!(lease.occurrence, 1);
    assert!(
        store
            .claim_due(100_000, 2, 60_000)
            .await
            .expect("claim after terminal")
            .is_none()
    );
}
