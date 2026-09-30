#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "final-use integration fixtures should fail loudly"
)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
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
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
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
static NEXT_TEST_NONCE: AtomicU64 = AtomicU64::new(1);
const EFFECT_PAYLOAD: &[u8] = b"effect-payload";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        Self::for_agent(AGENT_ID)
    }

    fn for_agent(agent_id: &str) -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(agent_id).expect("agent id"),
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

fn definition_for(step_id: &str) -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "authorized-effect",
        1,
        step_id,
        vec![
            TaskFlowNodeSpec::effect(step_id, "matrix.send", "matrix-send-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(step_id, "success"),
            TaskFlowEdgeSpec::new(step_id, "failure"),
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
        expected_predecessor_digest: None,
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
) -> (FinalUseAuthority, SignedFinalUseGrant, tempfile::TempDir) {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("wall clock milliseconds fit u64");
    let nonce_counter = NEXT_TEST_NONCE.fetch_add(1, Ordering::Relaxed);
    let nonce_material = format!("{grant_id}:{}:{now}:{nonce_counter}", std::process::id());
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch: 9,
        grant_id: grant_id.to_string(),
        nonce: digest_bytes(&Sha256Digest::for_bytes(nonce_material.as_bytes())),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority state dir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
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
    prepared_effect_store_for(fixture, intent()).await
}

async fn prepared_effect_store_for(
    fixture: &Fixture,
    effect: AuthorizedEffectIntent,
) -> (
    AutomationStore,
    TaskFlowFence,
    AuthorizedEffectIntent,
    FinalUseBinding,
) {
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let mut owner = fence();
    owner.owner_agent_id = fixture.layout.agent_id().clone();
    let definition = definition_for(&effect.step_id);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            &effect.run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-authorized-effect",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run(&effect.run_id, &owner, 20, 1_000)
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
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
        assert_eq!(request.wire_payload, EFFECT_PAYLOAD);
        assert_eq!(
            Sha256Digest::for_bytes(request.wire_payload),
            request.intent.payload_digest
        );
        assert_eq!(
            request.operation_intent.operation_id().as_str(),
            request.intent.operation_id.as_str()
        );
        assert_eq!(
            request.operation_intent.subject_id().as_str(),
            request.intent.subject_id.as_str()
        );
        assert_eq!(
            request.operation_intent.destination_id().as_str(),
            request.intent.destination_id.as_str()
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
            DriverResult::Receipt(outcome, receipt_digest) => Ok(AuthorizedEffectProviderReceipt {
                outcome: *outcome,
                receipt_digest: receipt_digest.clone(),
            }),
            DriverResult::BeforeProviderContact => {
                Err(AuthorizedEffectDriverError::BeforeProviderContact)
            }
        }
    }
}

struct RecordingProviderEffectAdapter {
    dispatch_calls: AtomicUsize,
    lookup_calls: AtomicUsize,
    seen_key: Mutex<Option<String>>,
    lookup_key: Mutex<Option<String>>,
    dispatch_result: ProviderEffectDispatch,
    lookup_result: ProviderEffectLookup,
}

impl RecordingProviderEffectAdapter {
    fn new(dispatch_result: ProviderEffectDispatch, lookup_result: ProviderEffectLookup) -> Self {
        Self {
            dispatch_calls: AtomicUsize::new(0),
            lookup_calls: AtomicUsize::new(0),
            seen_key: Mutex::new(None),
            lookup_key: Mutex::new(None),
            dispatch_result,
            lookup_result,
        }
    }
}

impl ProviderEffectAdapter for RecordingProviderEffectAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(async {
            ProviderEffectDispatch::NotDispatched {
                reason_code: "wire_payload_required".to_string(),
            }
        })
    }

    fn dispatch_with_payload<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        wire_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        self.dispatch_calls.fetch_add(1, Ordering::Relaxed);
        *self.seen_key.lock().expect("seen key lock") = Some(intent.key.as_str().to_string());
        let expected_payload = intent.payload_sha256.clone();
        let mut result = self.dispatch_result.clone();
        if let ProviderEffectDispatch::Ack(ack) = &mut result {
            ack.key = intent.key.clone();
        }
        Box::pin(async move {
            assert_eq!(Sha256Digest::for_bytes(wire_payload), expected_payload);
            result
        })
    }

    fn lookup<'a>(
        &'a self,
        key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        self.lookup_calls.fetch_add(1, Ordering::Relaxed);
        *self.lookup_key.lock().expect("lookup key") = Some(key.as_str().to_string());
        let result = self.lookup_result.clone();
        Box::pin(async move { result })
    }

    fn lookup_for_intent<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        self.lookup_calls.fetch_add(1, Ordering::Relaxed);
        *self.lookup_key.lock().expect("lookup key") = Some(intent.key.as_str().to_string());
        let result = self.lookup_result.clone();
        Box::pin(async move { result })
    }
}

async fn unknown_provider_effect(
    fixture: &Fixture,
    effect: AuthorizedEffectIntent,
) -> (
    AutomationStore,
    AuthorizedEffectPending,
    ProviderEffectTaskFlowDriver<RecordingProviderEffectAdapter>,
) {
    let (store, owner, effect, expected) = prepared_effect_store_for(fixture, effect).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "identity-unknown");
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::NotFound,
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");
    store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "identity-dispatch",
            30,
        )
        .await
        .expect("unknown dispatch");
    let pending = store
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
        .await
        .expect("durable identity")
        .expect("pending attempt");
    assert_eq!(
        driver
            .adapter()
            .seen_key
            .lock()
            .expect("seen key")
            .as_deref(),
        pending
            .provider_effect_key
            .as_ref()
            .map(ProviderEffectKey::as_str)
    );
    (store, pending, driver)
}

#[tokio::test]
async fn provider_identity_separates_delimiters_and_agent_owners() {
    let first_fixture = Fixture::new();
    let second_fixture = Fixture::new();
    let mut first = intent();
    first.run_id = "a:b".to_string();
    first.step_id = "c".to_string();
    let mut second = intent();
    second.run_id = "a".to_string();
    second.step_id = "b:c".to_string();
    let (_, first_pending, _) = unknown_provider_effect(&first_fixture, first).await;
    let (_, second_pending, _) = unknown_provider_effect(&second_fixture, second).await;
    assert_ne!(
        first_pending.provider_effect_key, second_pending.provider_effect_key,
        "separate run/step tuples must not share provider completion"
    );

    let agent_one = Fixture::new();
    let agent_two = Fixture::for_agent("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13");
    let (_, first_pending, _) = unknown_provider_effect(&agent_one, intent()).await;
    let (_, second_pending, _) = unknown_provider_effect(&agent_two, intent()).await;
    assert_ne!(
        first_pending.provider_effect_key, second_pending.provider_effect_key,
        "per-Agent databases must not alias the same provider occurrence"
    );
}

#[tokio::test]
async fn provider_lookup_after_restart_uses_original_persisted_key() {
    let fixture = Fixture::new();
    let (store, original, driver) = unknown_provider_effect(&fixture, intent()).await;
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending");
    assert_eq!(pending, vec![original.clone()]);
    assert!(matches!(
        driver.lookup(&pending[0]).await,
        AuthorizedProviderEffectLookup::ProvenAbsent { .. }
    ));
    assert_eq!(
        driver
            .adapter()
            .lookup_key
            .lock()
            .expect("lookup key")
            .as_deref(),
        original
            .provider_effect_key
            .as_ref()
            .map(ProviderEffectKey::as_str)
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn provider_absence_reconciliation_allows_fenced_retry_with_original_key() {
    let fixture = Fixture::new();
    let (store, original, mut driver) = unknown_provider_effect(&fixture, intent()).await;
    let owner = fence();
    let mut next_owner = owner.clone();
    next_owner.generation += 1;
    next_owner.fencing_token = "effect-retry-fence".to_string();
    assert!(
        store
            .claim_taskflow_run(&original.run_id, &next_owner, 31, 1_000)
            .await
            .is_err(),
        "unresolved contact must not allow a new owner"
    );
    let AuthorizedProviderEffectLookup::ProvenAbsent { proof_digest } =
        driver.lookup(&original).await
    else {
        panic!("fixture absence proof");
    };
    assert_eq!(
        store
            .recover_authorized_taskflow_effect(
                &original.run_id,
                &original.step_id,
                1,
                &owner,
                AuthorizedEffectRecovery::ProvenAbsent { proof_digest },
                32,
            )
            .await
            .expect("requeue absent effect"),
        AuthorizedEffectRecoveryResult::ProvenAbsent
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen absent run");
    let claimed = reopened
        .claim_taskflow_run(&original.run_id, &next_owner, 33, 1_000)
        .await
        .expect("reconciled absence permits takeover");
    reopened
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &original.run_id,
                "retry-start",
                next_owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                34,
            )
            .expect("retry start"),
        )
        .await
        .expect("start retry");
    let mut effect = intent();
    effect.attempt = 2;
    let digest = effect.digest().expect("retry intent");
    reopened
        .prepare_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &next_owner,
            &digest,
            &effect.payload_digest,
            "retry-prepare",
            35,
        )
        .await
        .expect("prepare new attempt");
    reopened
        .claim_taskflow_step(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &next_owner,
            &digest,
            &effect.payload_digest,
            "retry-claim",
            36,
        )
        .await
        .expect("claim new attempt");
    let expected = binding(&effect);
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "proven-absent-retry");
    reopened
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &next_owner,
            &signed,
            &expected,
            "retry-dispatch",
            37,
        )
        .await
        .expect("safely retried send");
    let retried = reopened
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 2)
        .await
        .expect("retry identity")
        .expect("second attempt");
    assert_eq!(retried.provider_effect_key, original.provider_effect_key);
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 2);
}

#[tokio::test]
async fn legacy_unscoped_identity_stays_quarantined_after_restart() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "legacy-unknown");
    let mut legacy = RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"legacy");
    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut legacy,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "legacy-dispatch",
            30,
        )
        .await
        .expect("legacy unscoped dispatch");
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("legacy pending");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].provider_effect_key, None);
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::NotFound,
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");
    assert_eq!(
        driver.lookup(&pending[0]).await,
        AuthorizedProviderEffectLookup::Unresolved
    );
    let (authority, fresh, _fresh_dir) = final_use(expected.clone(), "legacy-retry");
    assert!(matches!(
        reopened
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &fresh,
                &expected,
                "legacy-dispatch",
                31,
            )
            .await,
        Err(AuthorizedEffectError::RecoveryRequired)
    ));
    assert_eq!(driver.adapter().lookup_calls.load(Ordering::Relaxed), 0);
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 0);
    authority
        .claim(&fresh, &expected)
        .expect("quarantine must not burn a fresh grant");
}

struct RevocationRaceDriver {
    calls: usize,
    authority: FinalUseAuthority,
    grant_id: String,
    revoker: Option<thread::JoinHandle<Result<(), FinalUseError>>>,
}

impl RevocationRaceDriver {
    fn new(authority: FinalUseAuthority, grant_id: impl Into<String>) -> Self {
        Self {
            calls: 0,
            authority,
            grant_id: grant_id.into(),
            revoker: None,
        }
    }

    fn join_revoker(&mut self) {
        let result = self
            .revoker
            .take()
            .expect("revocation thread")
            .join()
            .expect("revocation thread join");
        assert_eq!(result, Err(FinalUseError::DispatchInProgress));
        self.authority
            .update_revocations(FinalUseRevocations {
                authority_epoch: 9,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([self.grant_id.clone()]),
            })
            .expect("revocation update after dispatch fence leaves");
    }
}

struct CrashAfterProviderContactDriver;

impl AuthorizedEffectDriver for CrashAfterProviderContactDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        assert_eq!(
            request.intent_digest,
            &request.intent.digest().expect("driver intent digest")
        );
        assert_eq!(request.wire_payload, EFFECT_PAYLOAD);
        assert_eq!(
            Sha256Digest::for_bytes(request.wire_payload),
            request.intent.payload_digest
        );
        panic!("simulated crash after provider contact before observation append");
    }
}

impl AuthorizedEffectDriver for RevocationRaceDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        self.calls += 1;
        assert_eq!(
            request.intent_digest,
            &request.intent.digest().expect("driver intent digest")
        );
        assert_eq!(request.wire_payload, EFFECT_PAYLOAD);
        assert_eq!(
            Sha256Digest::for_bytes(request.wire_payload),
            request.intent.payload_digest
        );
        let authority = self.authority.clone();
        let grant_id = self.grant_id.clone();
        let (started_tx, started_rx) = mpsc::channel();
        let revoker = thread::spawn(move || {
            started_tx.send(()).expect("signal revocation attempt");
            authority.update_revocations(FinalUseRevocations {
                authority_epoch: 9,
                revision: 2,
                revoked_grant_ids: BTreeSet::from([grant_id]),
            })
        });
        started_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("revocation thread reached final-use fence");
        let deadline = std::time::Instant::now() + Duration::from_secs(1);
        while !revoker.is_finished() && std::time::Instant::now() < deadline {
            thread::sleep(Duration::from_millis(1));
        }
        assert!(
            revoker.is_finished(),
            "revocation update must fail explicitly instead of blocking the provider runtime"
        );
        self.revoker = Some(revoker);
        Ok(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Succeeded,
            receipt_digest: Sha256Digest::for_bytes(b"revocation-race-success"),
        })
    }
}

#[tokio::test]
async fn wire_payload_drift_rejects_before_dispatch_and_does_not_burn_grant() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "wire-payload-drift");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                b"different-provider-bytes",
                &owner,
                &signed,
                &expected,
                "authorized-effect-dispatch",
                30,
            )
            .await,
        Err(AuthorizedEffectError::BindingMismatch)
    ));
    assert_eq!(driver.calls, 0);

    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await
        .expect("same grant remains usable after local wire mismatch");
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn async_provider_effect_binds_exact_wire_bytes_before_burning_grant() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "async-wire-binding");
    let key = ProviderEffectKey::for_logical_effect(&effect.destination_id, "fixture-response")
        .expect("fixture response key");
    let ack = ProviderEffectAck::new(
        key.clone(),
        effect.payload_digest.clone(),
        Sha256Digest::for_bytes(b"provider-operation"),
        ProviderEffectAckStatus::Completed,
    );
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Ack(ack),
        ProviderEffectLookup::NotFound,
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut driver,
                &effect,
                b"wrong-payload",
                &owner,
                &signed,
                &expected,
                "authorized-effect-async-dispatch",
                30,
            )
            .await,
        Err(AuthorizedEffectError::BindingMismatch)
    ));
    assert_eq!(
        driver.adapter().dispatch_calls.load(Ordering::Relaxed),
        0,
        "payload substitution must fail before provider entry"
    );

    let receipt = store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            b"effect-payload",
            &owner,
            &signed,
            &expected,
            "authorized-effect-async-dispatch",
            31,
        )
        .await
        .expect("exact wire payload dispatch");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
    let pending = store
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, 1)
        .await
        .expect("durable provider identity")
        .expect("attempt");
    assert_eq!(
        driver
            .adapter()
            .seen_key
            .lock()
            .expect("seen key")
            .as_deref(),
        pending
            .provider_effect_key
            .as_ref()
            .map(ProviderEffectKey::as_str)
    );
}

#[tokio::test]
async fn async_provider_unknown_is_quarantined_and_lookup_not_found_is_proven_absent() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "async-unknown");
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::NotFound,
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");

    let receipt = store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            b"effect-payload",
            &owner,
            &signed,
            &expected,
            "authorized-effect-async-unknown",
            30,
        )
        .await
        .expect("unknown provider dispatch is durable");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read run")
            .expect("run")
            .state,
        TaskFlowRunState::Indeterminate
    );

    let pending = store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending provider effect");
    assert_eq!(pending.len(), 1);
    assert!(matches!(
        driver.lookup(&pending[0]).await,
        AuthorizedProviderEffectLookup::ProvenAbsent { .. }
    ));
}

#[tokio::test]
async fn final_use_binding_drift_rejects_before_dispatch_and_does_not_burn_grant() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "binding-drift");
    let mut wrong = expected.clone();
    wrong.destination_id = "provider:other".to_string();
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
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
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await
        .expect("correct binding executes");
    assert_eq!(driver.calls, 1);
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
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
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "at-most-once");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"success");

    let first = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
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
            EFFECT_PAYLOAD,
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
async fn crash_after_provider_contact_before_observation_requires_recovery_without_redispatch() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) =
        final_use(expected.clone(), "after-send-before-record");

    let crash_store = store.clone();
    let crash_authority = authority.clone();
    let crash_effect = effect.clone();
    let crash_owner = owner.clone();
    let crash_signed = signed.clone();
    let crash_expected = expected.clone();
    let crashed = tokio::spawn(async move {
        let mut driver = CrashAfterProviderContactDriver;
        crash_store
            .execute_authorized_taskflow_effect(
                &crash_authority,
                &mut driver,
                &crash_effect,
                EFFECT_PAYLOAD,
                &crash_owner,
                &crash_signed,
                &crash_expected,
                "authorized-effect-dispatch",
                30,
            )
            .await
    })
    .await
    .expect_err("provider-contact crash must abort the execution task");
    assert!(crashed.is_panic());

    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen after provider-contact crash");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending recovery scan");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].run_id, effect.run_id);
    assert_eq!(pending[0].step_id, effect.step_id);
    assert_eq!(pending[0].attempt, effect.attempt);

    let mut must_not_dispatch =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"duplicate");
    let replay = reopened
        .execute_authorized_taskflow_effect(
            &authority,
            &mut must_not_dispatch,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            31,
        )
        .await;
    assert!(matches!(
        replay,
        Err(AuthorizedEffectError::RecoveryRequired)
    ));
    assert_eq!(must_not_dispatch.calls, 0);

    let recovered = reopened
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(b"recovered-after-crash"),
            }),
            32,
        )
        .await
        .expect("provider-owned recovery");
    assert!(matches!(
        recovered,
        AuthorizedEffectRecoveryResult::Observed(_)
    ));
}

#[tokio::test]
async fn indeterminate_effect_reopens_without_redispatch_then_reconciles_terminally() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "indeterminate");
    let mut ambiguous =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"ambiguous");

    let first = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut ambiguous,
            &effect,
            EFFECT_PAYLOAD,
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
            EFFECT_PAYLOAD,
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
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "before-contact");
    let mut driver = RecordingDriver::before_provider_contact();

    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
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
            EFFECT_PAYLOAD,
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

#[tokio::test]
async fn revocation_race_is_fenced_across_the_physical_provider_call() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let grant_id = "revocation-race";
    let (authority, signed, _authority_dir) = final_use(expected.clone(), grant_id);
    let mut driver = RevocationRaceDriver::new(authority.clone(), grant_id);

    let receipt = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "authorized-effect-dispatch",
            30,
        )
        .await
        .expect("dispatch under one final-use revocation fence");
    assert_eq!(driver.calls, 1);
    assert_eq!(receipt.state, TaskFlowStepState::Recorded);
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    assert_eq!(
        store
            .taskflow_run(&effect.run_id)
            .await
            .expect("read successful run")
            .expect("run")
            .state,
        TaskFlowRunState::Succeeded
    );

    driver.join_revoker();

    let mut must_not_dispatch =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-dispatch");
    assert!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut must_not_dispatch,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "authorized-effect-dispatch",
                31,
            )
            .await
            .is_err(),
        "a post-dispatch revocation cannot turn historical success into a fresh dispatch"
    );
    assert_eq!(must_not_dispatch.calls, 0);
}

#[tokio::test]
async fn compensation_crash_preserves_intent_identity_and_requires_reconciliation() {
    let fixture = Fixture::new();
    let mut compensation = intent();
    compensation.compensation_for = Some("matrix.original-send".to_string());
    let expected_digest = compensation.digest().expect("compensation intent digest");
    let (store, owner, compensation, expected) =
        prepared_effect_store_for(&fixture, compensation).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "compensation-crash");
    let mut ambiguous = RecordingDriver::receipt(
        AuthorizedEffectOutcome::Indeterminate,
        b"compensation-unknown",
    );

    let first = store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut ambiguous,
            &compensation,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "compensation-dispatch",
            30,
        )
        .await
        .expect("ambiguous compensation dispatch");
    assert_eq!(ambiguous.calls, 1);
    assert_eq!(first.state, TaskFlowStepState::Recorded);
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );

    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen after compensation crash");
    let pending = reopened
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending compensation");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].intent_digest, expected_digest);
    assert_eq!(pending[0].run_id, compensation.run_id);

    let recovered = reopened
        .recover_authorized_taskflow_effect(
            &compensation.run_id,
            &compensation.step_id,
            compensation.attempt,
            &owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Failed,
                receipt_digest: Sha256Digest::for_bytes(b"compensation-terminal-failure"),
            }),
            31,
        )
        .await
        .expect("reconcile compensation after crash");
    let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else {
        panic!("compensation recovery must append terminal provider evidence");
    };
    assert_eq!(receipt.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        receipt.final_outcome,
        Some(TaskFlowReconcileOutcome::Failed)
    );

    let mut must_not_dispatch =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-dispatch");
    assert!(
        reopened
            .execute_authorized_taskflow_effect(
                &authority,
                &mut must_not_dispatch,
                &compensation,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "compensation-dispatch",
                32,
            )
            .await
            .is_err(),
        "reconciled compensation must never be replayed as a new effect"
    );
    assert_eq!(must_not_dispatch.calls, 0);
}
