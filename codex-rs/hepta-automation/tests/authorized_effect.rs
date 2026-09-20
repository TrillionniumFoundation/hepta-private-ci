#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "final-use integration fixtures should fail loudly"
)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
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

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

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
        "authorized-effect",
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect("effect", "matrix.send", "matrix-send-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec!["matrix.send".to_string()],
        Sha256Digest::for_bytes(b"authorized-effect-policy"),
    )
    .expect("definition")
}

fn fence() -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "authorized-effect-owner",
        1,
        1,
        "authorized-effect-fence",
    )
    .expect("fence")
}

fn intent() -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: "authorized-effect-run".to_string(),
        step_id: "effect".to_string(),
        attempt: 1,
        operation_id: "matrix.send".to_string(),
        subject_id: "agent-one".to_string(),
        destination_id: "provider:matrix".to_string(),
        payload_digest: Sha256Digest::for_bytes(b"effect-payload"),
        final_use_scope_digest: Sha256Digest::for_bytes(b"matrix-room-scope"),
        policy_generation: 7,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

fn digest_bytes(digest: &Sha256Digest) -> [u8; 32] {
    let value = digest.as_str().as_bytes();
    assert_eq!(value.len(), 64);
    let mut output = [0_u8; 32];
    for (index, pair) in value.chunks_exact(2).enumerate() {
        output[index] = (hex(pair[0]) << 4) | hex(pair[1]);
    }
    output
}

fn hex(value: u8) -> u8 {
    match value {
        b'0'..=b'9' => value - b'0',
        b'a'..=b'f' => value - b'a' + 10,
        _ => panic!("non-canonical sha256"),
    }
}

fn binding(intent: &AuthorizedEffectIntent) -> FinalUseBinding {
    FinalUseBinding {
        subject_id: intent.subject_id.clone(),
        destination_id: intent.destination_id.clone(),
        request_sha256: digest_bytes(&intent.digest().expect("intent digest")),
        scope_sha256: digest_bytes(&intent.final_use_scope_digest),
        payload_sha256: digest_bytes(&intent.payload_digest),
    }
}

fn final_use(
    binding: FinalUseBinding,
    grant_id: &str,
    nonce: u8,
) -> (
    FinalUseAuthority,
    SignedFinalUseGrant,
    tempfile::TempDir,
) {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("wall clock milliseconds fit u64");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch: 9,
        grant_id: grant_id.to_string(),
        nonce: [nonce; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority state dir");
    std::fs::set_permissions(
        directory.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private authority dir");
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    )
}

async fn prepared_effect_store(
    fixture: &Fixture,
) -> (
    AutomationStore,
    TaskFlowFence,
    AuthorizedEffectIntent,
    FinalUseBinding,
) {
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence();
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "authorized-effect-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-authorized-effect",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("authorized-effect-run", &owner, 20, 1_000)
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "authorized-effect-run",
                "authorized-effect-start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                21,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    assert_eq!(started.state, TaskFlowRunState::Running);

    let effect = intent();
    let intent_digest = effect.digest().expect("intent digest");
    store
        .prepare_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            &intent_digest,
            &effect.payload_digest,
            "authorized-effect-prepare",
            22,
        )
        .await
        .expect("prepare step");
    let claimed = store
        .claim_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            &intent_digest,
            &effect.payload_digest,
            "authorized-effect-claim",
            23,
        )
        .await
        .expect("claim step");
    assert_eq!(claimed.receipt.state, TaskFlowStepState::Claimed);
    let expected = binding(&effect);
    (store, owner, effect, expected)
}

enum DriverResult {
    Receipt(AuthorizedEffectOutcome, Sha256Digest),
    BeforeProviderContact,
}

struct RecordingDriver {
    calls: usize,
    result: DriverResult,
}

impl RecordingDriver {
    fn receipt(outcome: AuthorizedEffectOutcome, label: &[u8]) -> Self {
        Self {
            calls: 0,
            result: DriverResult::Receipt(outcome, Sha256Digest::for_bytes(label)),
        }
    }

    fn before_provider_contact() -> Self {
        Self {
            calls: 0,
            result: DriverResult::BeforeProviderContact,
        }
    }
}

impl AuthorizedEffectDriver for RecordingDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        self.calls += 1;
        assert_eq!(
            request.intent_digest,
            &request.intent.digest().expect("driver intent digest")
        );
        assert_eq!(
            request.binding.subject_id.as_str(),
            request.intent.subject_id.as_str()
        );
        assert_eq!(
            request.binding.destination_id.as_str(),
            request.intent.destination_id.as_str()
        );
        match &self.result {
            DriverResult::Receipt(outcome, receipt_digest) => {
                Ok(AuthorizedEffectProviderReceipt {
                    outcome: *outcome,
                    receipt_digest: receipt_digest.clone(),
                })
            }
            DriverResult::BeforeProviderContact => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
        }
    }
}

#[tokio::test]
async fn final_use_binding_drift_rejects_before_dispatch_and_does_not_burn_grant() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) =
        final_use(expected.clone(), "binding-drift", 1);
    let mut wrong = expected.clone();
    wrong.destination_id = "provider:other".to_string();
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                &owner,
                &signed,
                &wrong,
                "authorized-effect-dispatch",
                30,
            )
            .await,
        Err(AuthorizedEffectError::BindingMismatch)
    ));
    assert_eq!(driver.calls, 0);

    let receipt = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await
        .expect("correct binding executes");
    assert_eq!(driver.calls, 1);
    assert_eq!(receipt.observation, Some(TaskFlowStepObservation::Succeeded));
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read run")
            .expect("run")
            .state,
        TaskFlowRunState::Succeeded
    );
}

#[tokio::test]
async fn successful_effect_is_at_most_once_for_one_durable_step_attempt() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) =
        final_use(expected.clone(), "at-most-once", 2);
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");

    let first = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            30,
        )
        .await
        .expect("first dispatch");
    assert_eq!(first.observation, Some(TaskFlowStepObservation::Succeeded));
    assert_eq!(driver.calls, 1);

    let replay = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await;
    assert!(
        replay.is_err(),
        "a settled step must reject execution re-entry"
    );
    assert_eq!(
        driver.calls, 1,
        "existing provider-attempt evidence must prevent redispatch"
    );
}

#[tokio::test]
async fn indeterminate_effect_reopens_without_redispatch_then_reconciles_terminally() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) =
        final_use(expected.clone(), "indeterminate", 3);
    let mut ambiguous =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"ambiguous");

    let first = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut ambiguous,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            30,
        )
        .await
        .expect("ambiguous dispatch");
    assert_eq!(ambiguous.calls, 1);
    assert_eq!(first.state, TaskFlowStepState::Recorded);
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read indeterminate run")
            .expect("run")
            .state,
        TaskFlowRunState::Indeterminate
    );

    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending effects");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_id, effect.run_id);

    let mut must_not_dispatch =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-dispatch");
    let replay = reopened
        .execute_authorized_taskflow_effect(
            &authority,
            &mut must_not_dispatch,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await;
    assert!(
        replay.is_err(),
        "indeterminate historical steps must use recovery, not execute re-entry"
    );
    assert_eq!(must_not_dispatch.calls, 0);

    let recovered = reopened
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(b"terminal-success"),
            }),
            32,
        )
        .await
        .expect("terminal recovery");
    let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else {
        panic!("terminal observation must reconcile the historical attempt");
    };
    assert_eq!(receipt.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        receipt.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    assert_eq!(
        reopened
            .taskflow_run(&effect.run_id)
            .await
            .expect("read recovered run")
            .expect("run")
            .state,
        TaskFlowRunState::Succeeded
    );
}

#[tokio::test]
async fn proven_pre_contact_failure_never_blindly_redispatches_same_attempt() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) =
        final_use(expected.clone(), "before-contact", 4);
    let mut driver = RecordingDriver::before_provider_contact();

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                &owner,
                &signed,
                &expected,
                "authorized-effect-dispatch",
                30,
            )
            .await,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        ))
    ));
    assert_eq!(driver.calls, 1);
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read requeued run")
            .expect("run")
            .state,
        TaskFlowRunState::Queued
    );

    let replay = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await;
    assert!(
        replay.is_err(),
        "proven absence requires a newly fenced step attempt before retry"
    );
    assert_eq!(
        driver.calls, 1,
        "same durable attempt must not cross the provider boundary twice"
    );
}
