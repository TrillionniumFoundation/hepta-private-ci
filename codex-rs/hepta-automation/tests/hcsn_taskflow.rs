#![cfg(unix)]
#![allow(clippy::expect_used, reason = "signed TaskFlow integration fixture")]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::HCSN_SUPERVISOR_SCHEMA_VERSION;
use codex_hepta_automation::HcsnJobEvidenceV1;
use codex_hepta_automation::HcsnJobIdentityV1;
use codex_hepta_automation::HcsnJobObservationV1;
use codex_hepta_automation::HcsnJobStateV1;
use codex_hepta_automation::HcsnProcessIdentityV1;
use codex_hepta_automation::HcsnSupervisor;
use codex_hepta_automation::HcsnSupervisorActionV1;
use codex_hepta_automation::HcsnSupervisorCommandV1;
use codex_hepta_automation::HcsnSupervisorError;
use codex_hepta_automation::HcsnTaskFlowActionV1;
use codex_hepta_automation::HcsnTaskFlowDriver;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SCOPE: &str = "provider:hcsn";
const PAYLOAD: &[u8] = b"{\"operation_id\":\"joint-graph-bp\"}";

struct Fixture {
    _root: tempfile::TempDir,
    layout: HeptaAgentLayout,
    owner: TaskFlowFence,
    issuer: SigningKey,
    authority: FinalUseAuthority,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().expect("root");
        let root = directory.path().canonicalize().expect("canonical root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let agent = AgentId::parse(AGENT_ID).expect("agent");
        let manifest = AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let authority_root = root.join("authority");
        std::fs::create_dir(&authority_root).expect("authority root");
        std::fs::set_permissions(&authority_root, std::fs::Permissions::from_mode(0o700))
            .expect("authority mode");
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            "security-owner".to_string(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("authority");
        Self {
            layout: registry.register(manifest).expect("register agent").layout,
            owner: TaskFlowFence::new(agent, "hcsn-owner", 1, 1, "hcsn-fence").expect("fence"),
            issuer,
            authority,
            _root: directory,
        }
    }

    fn sign(&self, effect: &AuthorizedEffectIntent, id: &str) -> SignedFinalUseGrant {
        let now = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_millis(),
        )
        .expect("milliseconds");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".to_string(),
            authority_epoch: 9,
            grant_id: id.to_string(),
            nonce: Sha256::digest(id.as_bytes()).into(),
            binding: effect.final_use_binding().expect("binding"),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = self
            .issuer
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    async fn prepare(
        &self,
        store: &AutomationStore,
        run_id: &str,
        action: HcsnTaskFlowActionV1,
        payload: &[u8],
    ) -> AuthorizedEffectIntent {
        let definition = TaskFlowDefinition::new(
            run_id,
            1,
            "effect",
            vec![
                TaskFlowNodeSpec::effect("effect", action.operation_id(), "hcsn-supervisor-v1"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("effect", "success"),
                TaskFlowEdgeSpec::new("effect", "failure"),
            ],
            vec![action.operation_id().to_string()],
            Sha256Digest::for_bytes(b"hcsn-policy"),
        )
        .expect("definition");
        store
            .register_taskflow_definition(&definition, &self.owner, 10)
            .await
            .expect("definition");
        store
            .create_taskflow_run(
                run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "hcsn-thread",
                10,
            )
            .await
            .expect("run");
        let claimed = store
            .claim_taskflow_run(run_id, &self.owner, 20, 1_000)
            .await
            .expect("claim run");
        store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    run_id,
                    format!("{run_id}:start"),
                    self.owner.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    21,
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        let effect = AuthorizedEffectIntent {
            run_id: run_id.to_string(),
            step_id: "effect".to_string(),
            attempt: 1,
            operation_id: action.operation_id().to_string(),
            subject_id: "agent-one".to_string(),
            destination_id: SCOPE.to_string(),
            payload_digest: Sha256Digest::for_bytes(payload),
            final_use_scope_digest: Sha256Digest::for_bytes(b"hcsn-training-scope"),
            policy_generation: 7,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        };
        let digest = effect.digest().expect("intent digest");
        store
            .prepare_taskflow_step(
                run_id,
                "effect",
                1,
                &self.owner,
                &digest,
                &effect.payload_digest,
                &format!("{run_id}:prepare"),
                22,
            )
            .await
            .expect("prepare step");
        store
            .claim_taskflow_step(
                run_id,
                "effect",
                1,
                &self.owner,
                &digest,
                &effect.payload_digest,
                &format!("{run_id}:claim"),
                23,
            )
            .await
            .expect("claim step");
        effect
    }
}

/// Provider test double for the real DB/authority integration. The separate
/// qualification acceptance suite exercises the actual process supervisor.
#[derive(Clone)]
struct FixtureSupervisor {
    calls: Arc<Mutex<Vec<HcsnSupervisorCommandV1>>>,
    state: Arc<Mutex<HcsnJobStateV1>>,
}

impl HcsnSupervisor for FixtureSupervisor {
    fn exchange(
        &mut self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<HcsnJobObservationV1, HcsnSupervisorError> {
        self.calls.lock().expect("calls").push(command.clone());
        let mut state = self.state.lock().expect("state");
        if command.action == HcsnSupervisorActionV1::Cancel {
            *state = HcsnJobStateV1::Cancelled;
        }
        Ok(HcsnJobObservationV1 {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            dispatch: command.dispatch.clone(),
            target: command.target.clone(),
            state: *state,
            process: Some(HcsnProcessIdentityV1 {
                host_id: Sha256Digest::for_bytes(b"fixture-host"),
                process_id: 47,
                incarnation: Sha256Digest::for_bytes(b"fixture-boot:start"),
            }),
            evidence: (*state == HcsnJobStateV1::Cancelled).then(|| HcsnJobEvidenceV1 {
                receipt_sha256: Sha256Digest::for_bytes(b"fixture-confirmed-termination"),
                candidate_sha256: None,
                handoff_sha256: None,
            }),
        })
    }
}

#[tokio::test]
async fn signed_dispatch_reopens_without_relaunch_and_distinct_cancel_reconciles() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let effect = fixture
        .prepare(
            &store,
            "hcsn-train-run",
            HcsnTaskFlowActionV1::Start,
            PAYLOAD,
        )
        .await;
    let binding = effect.final_use_binding().expect("binding");
    let signed = fixture.sign(&effect, "training-grant");
    let provider = FixtureSupervisor {
        calls: Arc::new(Mutex::new(Vec::new())),
        state: Arc::new(Mutex::new(HcsnJobStateV1::Running)),
    };
    let mut training = HcsnTaskFlowDriver::new(
        SCOPE.to_string(),
        HcsnTaskFlowActionV1::Start,
        provider.clone(),
    )
    .expect("driver");
    let mut invalid = signed.clone();
    invalid.signature[0] ^= 1;
    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &fixture.authority,
                &mut training,
                &effect,
                PAYLOAD,
                &fixture.owner,
                &invalid,
                &binding,
                "training-dispatch",
                30,
            )
            .await,
        Err(AuthorizedEffectError::FinalUse(_))
    ));
    assert!(provider.calls.lock().expect("calls").is_empty());

    let first = store
        .execute_authorized_taskflow_effect(
            &fixture.authority,
            &mut training,
            &effect,
            PAYLOAD,
            &fixture.owner,
            &signed,
            &binding,
            "training-dispatch",
            30,
        )
        .await
        .expect("authorized dispatch");
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending");
    assert_eq!(pending.len(), 1);
    assert!(
        reopened
            .execute_authorized_taskflow_effect(
                &fixture.authority,
                &mut training,
                &effect,
                PAYLOAD,
                &fixture.owner,
                &signed,
                &binding,
                "training-dispatch",
                31,
            )
            .await
            .is_err()
    );
    assert_eq!(provider.calls.lock().expect("calls").len(), 1);
    assert_eq!(
        training.lookup(&pending[0], PAYLOAD),
        AuthorizedProviderEffectLookup::Unresolved
    );

    let original = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &effect.run_id,
        &effect.step_id,
        effect.payload_digest.clone(),
    )
    .expect("original job");
    let cancel_payload = serde_json::to_vec(&original).expect("cancel payload");
    let cancel_effect = fixture
        .prepare(
            &reopened,
            "hcsn-cancel-run",
            HcsnTaskFlowActionV1::Cancel,
            &cancel_payload,
        )
        .await;
    let cancel_grant = fixture.sign(&cancel_effect, "cancellation-grant");
    let mut cancellation = HcsnTaskFlowDriver::new(
        SCOPE.to_string(),
        HcsnTaskFlowActionV1::Cancel,
        provider.clone(),
    )
    .expect("cancel driver");
    let cancelled = reopened
        .execute_authorized_taskflow_effect(
            &fixture.authority,
            &mut cancellation,
            &cancel_effect,
            &cancel_payload,
            &fixture.owner,
            &cancel_grant,
            &cancel_effect.final_use_binding().expect("cancel binding"),
            "cancel-dispatch",
            32,
        )
        .await
        .expect("authorized cancellation");
    assert_eq!(
        cancelled.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    let AuthorizedProviderEffectLookup::Observed(terminal) = training.lookup(&pending[0], PAYLOAD)
    else {
        panic!("original training must observe its confirmed cancellation");
    };
    assert_eq!(terminal.outcome, AuthorizedEffectOutcome::Failed);
    let recovered = reopened
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &fixture.owner,
            AuthorizedEffectRecovery::Observed(terminal),
            33,
        )
        .await
        .expect("recover original attempt");
    assert!(matches!(
        recovered,
        AuthorizedEffectRecoveryResult::Observed(_)
    ));
    assert!(
        reopened
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("settled scan")
            .is_empty()
    );
    assert_eq!(
        reopened
            .taskflow_run(&effect.run_id)
            .await
            .expect("training run")
            .expect("run")
            .state,
        TaskFlowRunState::Failed
    );
    assert_eq!(
        reopened
            .taskflow_run(&cancel_effect.run_id)
            .await
            .expect("cancel run")
            .expect("run")
            .state,
        TaskFlowRunState::Succeeded
    );
    {
        let calls = provider.calls.lock().expect("calls");
        assert_eq!(
            calls
                .iter()
                .map(|command| command.action)
                .collect::<Vec<_>>(),
            vec![
                HcsnSupervisorActionV1::Start,
                HcsnSupervisorActionV1::Status,
                HcsnSupervisorActionV1::Cancel,
                HcsnSupervisorActionV1::Status,
            ]
        );
        assert_eq!(calls[2].target, original);
        assert_ne!(calls[0].dispatch.key, calls[2].dispatch.key);
    }
    reopened.close().await;
}
