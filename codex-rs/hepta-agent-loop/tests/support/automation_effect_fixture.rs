//! Explicit isolated host/issuer fixture over the real TaskFlow and final-use
//! owners. These keys, admissions and byte-token context are not production.

use codex_hepta_agent_loop::*;
use codex_hepta_automation::*;
use codex_hepta_contracts::*;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(super) const NATIVE_RUN: &str = "native-status-run";
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

pub(super) fn clock() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("fixture clock")
        .as_millis()
        .try_into()
        .expect("fixture clock fits")
}

pub(super) fn id(text: &str) -> StableId {
    StableId::new(text).expect("fixture stable ID")
}

pub(super) fn initial() -> ModelRequest {
    let text = "isolated byte-token fixture";
    ModelRequest {
        request_id: id("fixture-model:0"),
        payload: text.into(),
        context_digest: Digest32::of_bytes(text.as_bytes()),
        input_tokens: text.len() as u64,
        maximum_provider_input_tokens: 256,
        maximum_output_tokens: 256,
    }
}

pub(super) struct StatusContext;
impl TaskFlowContextPreparer for StatusContext {
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
                "fixture expected original tool status",
            ));
        };
        let status: serde_json::Value = serde_json::from_str(output)
            .map_err(|_| codex_hepta_agent_loop::Error::Contract("fixture status JSON"))?;
        if status["result_scope"] != "status_only_no_output_artifact" {
            return Err(codex_hepta_agent_loop::Error::Contract(
                "fixture status scope",
            ));
        }
        // Explicit byte-token test profile, not a claim about a provider tokenizer.
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

pub(super) struct Fixture {
    pub(super) temp: tempfile::TempDir,
    pub(super) layout: HeptaAgentLayout,
}

impl Fixture {
    pub(super) fn new() -> Self {
        let temp = tempfile::tempdir().expect("private fixture root");
        let root = temp.path().canonicalize().expect("canonical root");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet path");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("fixture registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("fixture workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT).expect("fixture agent"),
            WorkspaceBinding::new(
                workspace.canonicalize().expect("canonical workspace"),
                &fleet,
            )
            .expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry
            .register(manifest)
            .expect("register fixture agent")
            .layout;
        Self { temp, layout }
    }

    pub(super) async fn native(&self) -> (AutomationStore, TaskFlowFence, Frame) {
        let store = AutomationStore::open(&self.layout)
            .await
            .expect("original automation store");
        let fence = TaskFlowFence::new(
            AgentId::parse(AGENT).expect("agent"),
            "fixture-native-owner",
            1,
            1,
            "fixture-original-fence",
        )
        .expect("original fence");
        let definition = TaskFlowDefinition::new(
            "native-status-turn",
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
            Sha256Digest::for_bytes(b"explicit native fixture policy"),
        )
        .expect("native definition");
        let now = clock();
        store
            .register_taskflow_definition(&definition, &fence, now)
            .await
            .expect("register native definition");
        start_run(&store, &fence, &definition, NATIVE_RUN, now).await;
        let binding = TurnBinding {
            run_id: id(NATIVE_RUN),
            turn_id: id("native-status-turn:0"),
            generation: Generation::new(1).expect("generation"),
            admission_digest: Digest32::of_bytes(b"explicit fixture native admission"),
            deadline_unix_ms: now + 120_000,
        };
        let mut turn = TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            binding.clone(),
            initial(),
            Limits::default(),
            StatusContext,
        )
        .await
        .expect("actual native turn owner");
        let initial_frame = turn.load(&binding).await.expect("frozen initial request");
        let call = ToolCall {
            call_id: id("fixture-call:0"),
            name: id(AUTOMATION_STATUS_TOOL_NAME),
            arguments: "{\"value\":\"owned fixture effect\"}".into(),
        };
        let frame = turn
            .commit(
                &initial_frame,
                Transition::ModelCompleted(ModelOutput {
                    request_id: initial().request_id,
                    continuation_digest: Digest32::of_bytes(
                        b"explicit fixture provider continuation",
                    ),
                    text: String::new(),
                    calls: vec![call],
                    usage: Usage {
                        input_tokens: 32,
                        output_tokens: 5,
                    },
                }),
            )
            .await
            .expect("actual native cursor selects tool");
        drop(turn);
        (store, fence, frame)
    }

    pub(super) fn authority(
        &self,
        effect: &AuthorizedEffectIntent,
    ) -> (FinalUseAuthority, SignedFinalUseGrant) {
        let issuer = SigningKey::from_bytes(&[73; 32]); // Explicit test-only issuer.
        let now = clock();
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "explicit-test-issuer".into(),
            authority_epoch: 9,
            grant_id: "explicit-test-status-grant".into(),
            nonce: *Digest32::of_bytes(effect.run_id.as_bytes()).as_array(),
            binding: effect
                .final_use_binding()
                .expect("original intent-derived binding"),
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 120_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("original signing bytes"))
            .to_bytes()
            .to_vec();
        let directory = self.temp.path().join("explicit-test-authority");
        std::fs::create_dir(&directory).expect("isolated authority directory");
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
            .expect("private authority directory");
        let authority = FinalUseAuthority::open_state_dir(
            &directory,
            "explicit-test-issuer".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("actual original final-use owner");
        (authority, SignedFinalUseGrant { grant, signature })
    }
}

async fn start_run(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    definition: &TaskFlowDefinition,
    run: &str,
    now: u64,
) {
    store
        .create_taskflow_run(
            run,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "explicit-fixture-thread",
            now,
        )
        .await
        .expect("create admitted fixture run");
    let claimed = store
        .claim_taskflow_run(run, fence, now, 600_000)
        .await
        .expect("claim existing run");
    let command = TaskFlowCommand::new(
        run,
        "fixture-start",
        fence.clone(),
        claimed.revision,
        TaskFlowTransition::Start,
        now,
    )
    .expect("original start command");
    store
        .apply_taskflow_command(&command)
        .await
        .expect("start admitted fixture run");
}

pub(super) async fn prepare_effect(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    frame: &Frame,
) -> AuthorizedEffectIntent {
    let run = automation_status_effect_run_id(frame).expect("integrity mapping only");
    let definition = TaskFlowDefinition::new(
        "fixture-status-effect",
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect(
                "effect",
                "fixture.status-effect",
                "fixture-status-effect-v1",
            ),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec!["fixture.status-effect".into()],
        Sha256Digest::for_bytes(b"explicit effect fixture policy"),
    )
    .expect("separately admitted effect definition");
    let now = clock();
    store
        .register_taskflow_definition(&definition, fence, now)
        .await
        .expect("register effect definition");
    start_run(store, fence, &definition, &run, now).await;
    let intent = AuthorizedEffectIntent {
        run_id: run,
        step_id: "effect".into(),
        attempt: 1,
        operation_id: "fixture.status-effect".into(),
        subject_id: "explicit-test-agent".into(),
        destination_id: "provider:explicit-test-file".into(),
        payload_digest: Sha256Digest::for_bytes(call(frame).arguments.as_bytes()),
        final_use_scope_digest: Sha256Digest::for_bytes(b"explicit fixture status scope"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    let digest = intent.digest().expect("original intent digest");
    store
        .prepare_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fence,
            &digest,
            &intent.payload_digest,
            "fixture-prepare",
            now,
        )
        .await
        .expect("original durable preparation");
    store
        .claim_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fence,
            &digest,
            &intent.payload_digest,
            "fixture-claim",
            now,
        )
        .await
        .expect("original durable claim");
    intent
}

pub(super) fn call(frame: &Frame) -> &ToolCall {
    match &frame.phase {
        Phase::Tools { calls, next } => &calls[*next],
        _ => panic!("fixture selected tool"),
    }
}

pub(super) fn admitted(
    frame: &Frame,
    intent: &AuthorizedEffectIntent,
    fence: &TaskFlowFence,
    grant: &SignedFinalUseGrant,
) -> PreboundAutomationStatusEffect {
    PreboundAutomationStatusEffect::new(
        frame,
        intent.clone(),
        call(frame).arguments.as_bytes().to_vec(),
        fence.clone(),
        grant.clone(),
        "fixture-effect-dispatch".into(),
    )
    .expect("pre-admitted status attachment")
}
