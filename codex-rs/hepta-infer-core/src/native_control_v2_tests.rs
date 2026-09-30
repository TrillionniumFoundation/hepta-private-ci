use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

use crate::control_contracts::ControlSignature;
use crate::control_contracts::ControlTrustStore;
use crate::control_contracts::ExecutionAuthorityBundle;
use crate::control_contracts::ExecutionManifest;
use crate::control_contracts::IndeterminateRetirement;
use crate::control_contracts::OutputClassification;
use crate::control_contracts::OutputDataPolicy;
use crate::control_contracts::OutputStorageMode;
use crate::control_contracts::QuotaLease;
use crate::control_contracts::ReconciledTerminalStatus;
use crate::control_contracts::ReconciliationReceipt;
use crate::control_contracts::ResourceLease;
use crate::control_contracts::SignedExecutionAuthorityBundle;
use crate::control_contracts::SignedIndeterminateRetirement;
use crate::control_contracts::SignedReconciliationReceipt;
use crate::control_contracts::TrustKey;
use crate::control_contracts::TrustRole;
use crate::control_contracts::VerifiedExecutionPlan;
use crate::control_contracts::verify_execution_plan;
use crate::control_contracts::verify_indeterminate_retirement;
use crate::control_contracts::verify_reconciliation_receipt;

use super::*;

const NOW: u64 = 1_000_000;

struct TestPaths {
    directory: PathBuf,
    journal: PathBuf,
}

impl TestPaths {
    fn new(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-inference-control-v2-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).unwrap();
        Self {
            journal: directory.join("control.journal"),
            directory,
        }
    }
}

impl Drop for TestPaths {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "principal-1".to_string(),
        worker_generation: 4,
        model: "model-1".to_string(),
        payload_digest: "6".repeat(64),
    }
}

fn dispatch(thread_id: &str) -> NativeDispatch {
    NativeDispatch {
        thread_id: thread_id.to_string(),
        model_provider: "provider-1".to_string(),
        context_digest: "a".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: None,
        codex_request_digest: None,
        app_server_version: None,
        protocol_id: None,
        codex_source_admission_digest: None,
        codex_home_digest: None,
        codex_connection_id: None,
        codex_session_id: None,
        codex_deadline_ms: None,
        codex_authority_epoch: None,
        codex_revocation_revision: None,
        codex_revocation_head_sha256: None,
        codex_authority_witness_sha256: None,
    }
}

fn terminal_output(thread_id: &str, turn_id: &str, text: &str) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: thread_id.to_string(),
        turn_id: turn_id.to_string(),
        model: "model-1".to_string(),
        model_provider: "provider-1".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: text.to_string(),
        observed_output_tokens: Some(7),
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("d".repeat(64)),
    }
}

fn indeterminate_output(thread_id: &str, turn_id: &str) -> NativeRunOutput {
    NativeRunOutput {
        thread_id: thread_id.to_string(),
        turn_id: turn_id.to_string(),
        model: "model-1".to_string(),
        model_provider: "provider-1".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        stop_reason: Some("provider terminal state unavailable".to_string()),
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: None,
    }
}

fn digest(domain: &[u8], payload: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((payload.len() as u64).to_be_bytes());
    hash.update(payload);
    format!("{:x}", hash.finalize())
}

struct AuthorityFixture {
    trust: ControlTrustStore,
    plan: VerifiedExecutionPlan,
    reconciliation_key: SigningKey,
    operator_a: SigningKey,
    operator_b: SigningKey,
}

fn trust_key(key_id: &str, signer_id: &str, role: TrustRole, key: &SigningKey) -> TrustKey {
    TrustKey {
        key_id: key_id.to_string(),
        signer_id: signer_id.to_string(),
        role,
        verifying_key: key.verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 9,
        revoked_at_authority_epoch: None,
    }
}

fn signature(key_id: &str, signer_id: &str, key: &SigningKey, message: &[u8]) -> ControlSignature {
    ControlSignature {
        key_id: key_id.to_string(),
        signer_id: signer_id.to_string(),
        signature: key.sign(message).to_bytes().to_vec(),
    }
}

fn authority_fixture(request_id: &str) -> AuthorityFixture {
    let manifest_key = SigningKey::from_bytes(&[1; 32]);
    let quota_key = SigningKey::from_bytes(&[2; 32]);
    let resource_key = SigningKey::from_bytes(&[3; 32]);
    let data_key = SigningKey::from_bytes(&[4; 32]);
    let reconciliation_key = SigningKey::from_bytes(&[5; 32]);
    let operator_a = SigningKey::from_bytes(&[6; 32]);
    let operator_b = SigningKey::from_bytes(&[7; 32]);
    let trust = ControlTrustStore::new(vec![
        trust_key(
            "manifest-key",
            "manifest-authority",
            TrustRole::ManifestAuthority,
            &manifest_key,
        ),
        trust_key(
            "quota-key",
            "quota-authority",
            TrustRole::QuotaAuthority,
            &quota_key,
        ),
        trust_key(
            "resource-key",
            "resource-authority",
            TrustRole::ResourceAuthority,
            &resource_key,
        ),
        trust_key(
            "data-key",
            "data-authority",
            TrustRole::DataAuthority,
            &data_key,
        ),
        trust_key(
            "reconciliation-key",
            "provider-reconciler",
            TrustRole::ReconciliationIssuer,
            &reconciliation_key,
        ),
        trust_key(
            "operator-key-a",
            "operator-a",
            TrustRole::RetirementOperator,
            &operator_a,
        ),
        trust_key(
            "operator-key-b",
            "operator-b",
            TrustRole::RetirementOperator,
            &operator_b,
        ),
    ])
    .unwrap();

    let manifest = ExecutionManifest {
        schema_version: 1,
        manifest_id: "manifest-1".to_string(),
        issuer_id: "manifest-authority".to_string(),
        authority_epoch: 3,
        provider_id: "provider-1".to_string(),
        model_id: "model-1".to_string(),
        model_revision: "revision-1".to_string(),
        model_digest: "1".repeat(64),
        tokenizer_id: "tokenizer-1".to_string(),
        tokenizer_version: "version-1".to_string(),
        tokenizer_digest: "2".repeat(64),
        template_id: "template-1".to_string(),
        template_digest: "3".repeat(64),
        runtime_abi: "runtime.v1".to_string(),
        runtime_digest: "4".repeat(64),
        adapter_abi: "adapter.v1".to_string(),
        adapter_digest: "5".repeat(64),
        payload_digest: "6".repeat(64),
        policy_digest: "7".repeat(64),
    };
    let manifest_digest = digest(
        b"hepta.inference-control.manifest.v1\0",
        &serde_json::to_vec(&manifest).unwrap(),
    );
    let bundle = ExecutionAuthorityBundle {
        schema_version: 1,
        request_id: request_id.to_string(),
        principal_id: "principal-1".to_string(),
        manifest,
        quota_lease: QuotaLease {
            schema_version: 1,
            lease_id: format!("quota-{request_id}"),
            authority_id: "quota-authority".to_string(),
            authority_epoch: 3,
            request_id: request_id.to_string(),
            principal_id: "principal-1".to_string(),
            manifest_digest: manifest_digest.clone(),
            maximum_input_tokens: 100,
            maximum_output_tokens: 200,
            maximum_cost_microunits: 50_000,
            valid_from_unix_ms: NOW - 10,
            valid_until_unix_ms: NOW + 1_000,
        },
        resource_lease: ResourceLease {
            schema_version: 1,
            lease_id: format!("resource-{request_id}"),
            authority_id: "resource-authority".to_string(),
            authority_epoch: 3,
            request_id: request_id.to_string(),
            worker_id: "worker-1".to_string(),
            worker_generation: 4,
            manifest_digest,
            cpu_millis: 1_000,
            memory_bytes: 1024 * 1024,
            accelerator_count: 1,
            accelerator_profile_digest: "8".repeat(64),
            valid_from_unix_ms: NOW - 10,
            valid_until_unix_ms: NOW + 1_000,
        },
        output_policy: OutputDataPolicy {
            schema_version: 1,
            policy_id: format!("policy-{request_id}"),
            authority_id: "data-authority".to_string(),
            authority_epoch: 3,
            classification: OutputClassification::Internal,
            storage_mode: OutputStorageMode::DigestOnly,
            maximum_retention_ms: 2_000,
            delete_after_unix_ms: NOW + 1_000,
            encryption_key_id: None,
            encrypted_store_namespace: None,
        },
    };
    let message = bundle.signing_bytes().unwrap();
    let signed = SignedExecutionAuthorityBundle {
        bundle,
        signatures: vec![
            signature(
                "manifest-key",
                "manifest-authority",
                &manifest_key,
                &message,
            ),
            signature("quota-key", "quota-authority", &quota_key, &message),
            signature(
                "resource-key",
                "resource-authority",
                &resource_key,
                &message,
            ),
            signature("data-key", "data-authority", &data_key, &message),
        ],
    };
    let plan = verify_execution_plan(NOW, &trust, &signed).unwrap();
    AuthorityFixture {
        trust,
        plan,
        reconciliation_key,
        operator_a,
        operator_b,
    }
}

fn start_bound(
    control: &mut DurableInferenceControl,
    fixture: &AuthorityFixture,
    request_id: &str,
    thread_id: &str,
    turn_id: &str,
) {
    control.reserve_native(request(request_id), 1).unwrap();
    control
        .bind_native_execution(request_id, &fixture.plan, NOW)
        .unwrap();
    control
        .dispatch_native_authorized(request_id, dispatch(thread_id), &fixture.plan, NOW)
        .unwrap();
    control
        .native_started(request_id, turn_id.to_string())
        .unwrap();
}

#[test]
fn pre_effect_abort_token_cannot_release_another_journal() {
    let first_paths = TestPaths::new("pre-effect-owner-first");
    let second_paths = TestPaths::new("pre-effect-owner-second");
    let mut first = DurableInferenceControl::open(&first_paths.journal, 8).unwrap();
    let mut second = DurableInferenceControl::open(&second_paths.journal, 8).unwrap();
    first.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = first
        .dispatch_native_with_pre_effect_abort("r1", dispatch("thread-1"))
        .unwrap();
    second.reserve_native(request("r1"), 1).unwrap();
    let expected = second.dispatch_native("r1", dispatch("thread-1")).unwrap();
    let bytes_before = fs::metadata(&second_paths.journal).unwrap().len();
    assert_eq!(
        second.abort_native_before_effect(token, "wrong owner".to_string()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(second.native_record("r1"), Some(&expected));
    assert_eq!(
        fs::metadata(&second_paths.journal).unwrap().len(),
        bytes_before
    );
    assert_eq!(
        second.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn retained_pre_effect_abort_token_cannot_release_reopened_owner() {
    let paths = TestPaths::new("pre-effect-retained-recovery");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (expected, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch("thread-1"))
        .unwrap();
    drop(control);
    let mut reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    let bytes_before = fs::metadata(&paths.journal).unwrap().len();
    assert_eq!(
        reopened.abort_native_before_effect(token, "stale owner".to_string()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(reopened.native_record("r1"), Some(&expected));
    assert_eq!(fs::metadata(&paths.journal).unwrap().len(), bytes_before);
    assert_eq!(
        reopened.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn locally_aborted_dispatch_cannot_be_resurrected_by_observation() {
    let paths = TestPaths::new("pre-effect-late-observation");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch("thread-1"))
        .unwrap();
    let stopped = control
        .abort_native_before_effect(token, "not sent".to_string())
        .unwrap();
    let active = control.reserve_native(request("r2"), 1).unwrap();
    let bytes_before = fs::metadata(&paths.journal).unwrap().len();
    for observed in [
        indeterminate_output("thread-1", "turn-1"),
        terminal_output("thread-1", "turn-1", "observed text"),
    ] {
        assert_eq!(
            control.settle_native("r1", observed),
            Err(Error::InvalidTransition)
        );
    }
    assert_eq!(control.native_record("r1"), Some(&stopped));
    assert_eq!(control.native_record("r2"), Some(&active));
    assert_eq!(fs::metadata(&paths.journal).unwrap().len(), bytes_before);
    assert_eq!(
        control.reserve_native(request("r3"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&stopped));
    assert_eq!(reopened.native_record("r2"), Some(&active));
}

#[test]
fn terminal_usage_refinement_cannot_clear_success_denial() {
    let paths = TestPaths::new("late-usage-stop-reason");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch("thread-1")).unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    let mut terminal = terminal_output("thread-1", "turn-1", "observed text");
    terminal.observed_output_tokens = None;
    terminal.stop_reason = Some("Agentd terminal reconciliation required".to_string());
    control.settle_native("r1", terminal.clone()).unwrap();
    terminal.observed_output_tokens = Some(27);
    let refined = control.settle_native("r1", terminal.clone()).unwrap();
    assert!(!refined.observation.as_ref().unwrap().succeeded());
    let bytes_before = fs::metadata(&paths.journal).unwrap().len();
    terminal.stop_reason = None;
    assert!(terminal.succeeded());
    assert_eq!(control.settle_native("r1", terminal), Err(Error::Conflict));
    assert_eq!(control.native_record("r1"), Some(&refined));
    assert_eq!(fs::metadata(&paths.journal).unwrap().len(), bytes_before);
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&refined));
}

#[test]
fn ambiguous_native_append_fences_idempotent_mutations() {
    let paths = TestPaths::new("native-writer-poison");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch("thread-1")).unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    control.cancel_native("r1").unwrap();
    let terminal = terminal_output("thread-1", "turn-1", "observed text");
    let expected = control.settle_native("r1", terminal.clone()).unwrap();
    control.file = fs::File::open(&paths.journal).unwrap();
    let mut later = terminal.clone();
    later.observed_output_tokens = Some(8);
    assert!(matches!(
        control.settle_native("r1", later),
        Err(Error::Io(_))
    ));
    let fixture = authority_fixture("r1");
    for result in [
        control.settle_native("r1", terminal),
        control.cancel_native("r1"),
        control.bind_native_execution("r1", &fixture.plan, NOW),
        control.dispatch_native("r1", dispatch("thread-1")),
        control.native_started("r1", "turn-1".to_string()),
    ] {
        assert_eq!(result, Err(Error::WriterUnavailable));
    }
    assert_eq!(control.native_record("r1"), Some(&expected));
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&expected));
}

#[test]
fn compaction_preserves_indeterminate_capacity_and_exact_state() {
    let paths = TestPaths::new("indeterminate-compaction");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("request-1"), 1).unwrap();
    control
        .dispatch_native("request-1", dispatch("thread-1"))
        .unwrap();
    control
        .native_started("request-1", "turn-1".to_string())
        .unwrap();
    let held = control
        .settle_native("request-1", indeterminate_output("thread-1", "turn-1"))
        .unwrap();
    let receipt = control.compact_native_journal().unwrap();
    assert_eq!(receipt.generation, 1);
    assert_eq!(receipt.record_count, 1);
    assert!(receipt.active_journal_bytes < 4096);
    drop(control);

    let mut reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&held));
    assert_eq!(
        reopened.reserve_native(request("request-2"), 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(reopened.native_metrics(NOW).indeterminate, 1);
}

#[test]
fn every_compaction_failpoint_reopens_a_complete_generation() {
    let before_rename = [
        NativeMaintenanceStage::BeforeArchiveWrite,
        NativeMaintenanceStage::AfterArchiveSync,
        NativeMaintenanceStage::BeforeCheckpointWrite,
        NativeMaintenanceStage::AfterCheckpointSync,
        NativeMaintenanceStage::BeforeGenerationWrite,
        NativeMaintenanceStage::AfterGenerationSync,
    ];
    for (index, stage) in before_rename.into_iter().enumerate() {
        let paths = TestPaths::new(&format!("before-rename-{index}"));
        let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
        control.reserve_native(request("request-1"), 1).unwrap();
        control
            .stop_native_before_dispatch("request-1", "test stop".to_string())
            .unwrap();
        let mut failpoint = |observed| {
            if observed == stage {
                Err(Error::Io("deterministic maintenance failure".to_string()))
            } else {
                Ok(())
            }
        };
        assert!(matches!(
            control.compact_native_journal_with_failpoint(NOW, &mut failpoint),
            Err(Error::Io(_))
        ));
        drop(control);
        let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
        assert_eq!(
            reopened.native_record("request-1").unwrap().state,
            NativeReservationState::Released
        );
    }

    for (index, stage) in [
        NativeMaintenanceStage::AfterGenerationRename,
        NativeMaintenanceStage::AfterParentSync,
    ]
    .into_iter()
    .enumerate()
    {
        let paths = TestPaths::new(&format!("after-rename-{index}"));
        let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
        control.reserve_native(request("request-1"), 1).unwrap();
        control
            .stop_native_before_dispatch("request-1", "test stop".to_string())
            .unwrap();
        let mut failpoint = |observed| {
            if observed == stage {
                Err(Error::Io("deterministic maintenance failure".to_string()))
            } else {
                Ok(())
            }
        };
        assert!(matches!(
            control.compact_native_journal_with_failpoint(NOW, &mut failpoint),
            Err(Error::Io(_))
        ));
        drop(control);
        let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
        assert_eq!(reopened.native_metrics(NOW).checkpoint_generation, 1);
        assert_eq!(
            reopened.native_record("request-1").unwrap().state,
            NativeReservationState::Released
        );
    }
}

#[test]
fn checkpoint_tampering_is_rejected_on_reopen() {
    let paths = TestPaths::new("checkpoint-tamper");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    control.reserve_native(request("request-1"), 1).unwrap();
    control
        .stop_native_before_dispatch("request-1", "test stop".to_string())
        .unwrap();
    let receipt = control.compact_native_journal().unwrap();
    drop(control);

    let checkpoint = PathBuf::from(format!("{}.checkpoints", paths.journal.display()))
        .join(format!("{}.json", receipt.checkpoint_digest));
    let mut bytes = fs::read(&checkpoint).unwrap();
    bytes[0] ^= 1;
    fs::write(&checkpoint, bytes).unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&paths.journal, 8),
        Err(Error::CorruptJournal("native checkpoint digest"))
    ));
}

#[test]
fn authorized_settlement_never_persists_raw_output() {
    let paths = TestPaths::new("protected-output");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    let secret = "top secret model output that must not enter the journal";
    let settled = control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            terminal_output("thread-1", "turn-1", secret),
            None,
        )
        .unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert!(settled.protected_output.is_some());
    drop(control);

    let journal = fs::read(&paths.journal).unwrap();
    assert!(
        !journal
            .windows(secret.len())
            .any(|window| window == secret.as_bytes())
    );
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert!(
        reopened
            .native_record("request-1")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .output
            .starts_with("hepta-protected-output-v1:")
    );
}

#[test]
fn signed_reconciliation_releases_indeterminate_without_blind_replay() {
    let paths = TestPaths::new("signed-reconciliation");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            indeterminate_output("thread-1", "turn-1"),
            None,
        )
        .unwrap();
    let dispatch_digest = native_dispatch_digest(
        control
            .native_record("request-1")
            .unwrap()
            .dispatch
            .as_ref()
            .unwrap(),
    )
    .unwrap();
    let receipt = ReconciliationReceipt {
        schema_version: 1,
        issuer_id: "provider-reconciler".to_string(),
        authority_epoch: 3,
        request_id: "request-1".to_string(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: fixture.plan.execution_binding_digest().to_string(),
        dispatch_digest,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        provider_id: "provider-1".to_string(),
        model_digest: fixture.plan.manifest().model_digest.clone(),
        terminal_sequence: 9,
        terminal_status: ReconciledTerminalStatus::Completed,
        output_digest: Some("b".repeat(64)),
        encrypted_output_reference: None,
        observed_output_tokens: Some(17),
        usage_microunits: Some(23),
        issued_at_unix_ms: NOW - 1,
        expires_at_unix_ms: NOW + 100,
    };
    let signed = SignedReconciliationReceipt {
        signature: signature(
            "reconciliation-key",
            "provider-reconciler",
            &fixture.reconciliation_key,
            &receipt.signing_bytes().unwrap(),
        ),
        receipt,
    };
    let verified =
        verify_reconciliation_receipt(NOW, &fixture.trust, &fixture.plan, &signed).unwrap();
    let settled = control
        .reconcile_native("request-1", &fixture.plan, NOW, &verified)
        .unwrap();
    assert_eq!(settled.state, NativeReservationState::Released);
    assert_eq!(
        settled.reconciliation.as_ref().unwrap().terminal_sequence,
        9
    );
    drop(control);
    let original = fs::read_to_string(&paths.journal).unwrap();
    for mutation in 0..5 {
        let mut journal = String::new();
        for line in original.lines() {
            let json = line.strip_prefix(JOURNAL_PREFIX).unwrap();
            let mut event: Event = serde_json::from_str(json).unwrap();
            if let Event::Reconcile { output, audit, .. } = &mut event {
                match mutation {
                    0 => output.terminal_observed = false,
                    1 => output.codex_terminal_correlation_digest = Some("a".repeat(64)),
                    2 => output.output = "raw output bypassing protected storage".to_string(),
                    3 => {
                        audit.output_digest = None;
                        output.output.clear();
                    }
                    4 => audit.output_digest = Some("c".repeat(64)),
                    _ => unreachable!(),
                }
            }
            journal.push_str(JOURNAL_PREFIX);
            journal.push_str(&serde_json::to_string(&event).unwrap());
            journal.push('\n');
        }
        fs::write(&paths.journal, journal).unwrap();
        assert!(
            DurableInferenceControl::open(&paths.journal, 8).is_err(),
            "mutation {mutation}"
        );
    }
    fs::write(&paths.journal, original).unwrap();
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&settled));
}

fn retirement_for_record(
    fixture: &AuthorityFixture,
    held: &NativeRunRecord,
) -> SignedIndeterminateRetirement {
    let dispatch_digest = native_dispatch_digest(held.dispatch.as_ref().unwrap()).unwrap();
    let retirement = IndeterminateRetirement {
        schema_version: 1,
        authority_epoch: 3,
        request_id: held.request.request_id.clone(),
        principal_id: "principal-1".to_string(),
        execution_binding_digest: fixture.plan.execution_binding_digest().to_string(),
        dispatch_digest,
        record_revision: held.revision,
        reason_code: "provider_unrecoverable".to_string(),
        reason: "provider has no independently recoverable terminal record".to_string(),
        issued_at_unix_ms: NOW - 1,
        expires_at_unix_ms: NOW + 100,
    };
    let message = retirement.signing_bytes().unwrap();
    SignedIndeterminateRetirement {
        retirement,
        approvals: vec![
            signature(
                "operator-key-a",
                "operator-a",
                &fixture.operator_a,
                &message,
            ),
            signature(
                "operator-key-b",
                "operator-b",
                &fixture.operator_b,
                &message,
            ),
        ],
    }
}

#[test]
fn indeterminate_retirement_is_revision_bound_and_dual_controlled() {
    let paths = TestPaths::new("dual-retirement");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    let held = control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            indeterminate_output("thread-1", "turn-1"),
            None,
        )
        .unwrap();
    let signed = retirement_for_record(&fixture, &held);
    let verified =
        verify_indeterminate_retirement(NOW, &fixture.trust, &fixture.plan, &signed).unwrap();
    let retired = control
        .retire_native_indeterminate("request-1", &fixture.plan, NOW, &verified)
        .unwrap();
    assert_eq!(retired.state, NativeReservationState::Released);
    assert_eq!(
        retired.retirement.as_ref().unwrap().operator_ids,
        ["operator-a".to_string(), "operator-b".to_string()]
    );
    let active = control.reserve_native(request("request-2"), 1).unwrap();
    let mut late = indeterminate_output("thread-1", "turn-1");
    late.stop_reason = Some("late observation after retirement".to_string());
    assert_eq!(
        control.settle_native("request-1", late),
        Err(Error::InvalidTransition)
    );
    assert_eq!(control.native_record("request-1"), Some(&retired));
    assert_eq!(control.native_record("request-2"), Some(&active));
    assert_eq!(
        control.reserve_native(request("request-3"), 1),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn legacy_retirement_holds_capacity_until_fresh_independent_approval() {
    let paths = TestPaths::new("legacy-retirement");
    let fixture = authority_fixture("request-1");
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    start_bound(&mut control, &fixture, "request-1", "thread-1", "turn-1");
    let held = control
        .settle_native_authorized(
            "request-1",
            &fixture.plan,
            NOW,
            indeterminate_output("thread-1", "turn-1"),
            None,
        )
        .unwrap();
    let old_signed = retirement_for_record(&fixture, &held);
    let old_verified =
        verify_indeterminate_retirement(NOW, &fixture.trust, &fixture.plan, &old_signed).unwrap();
    control
        .retire_native_indeterminate("request-1", &fixture.plan, NOW, &old_verified)
        .unwrap();
    drop(control);

    // Recreate the historical wire format: operator/key IDs, without actual keys.
    let mut journal = String::new();
    for line in fs::read_to_string(&paths.journal).unwrap().lines() {
        let json = line.strip_prefix(JOURNAL_PREFIX).unwrap();
        let mut value: serde_json::Value = serde_json::from_str(json).unwrap();
        if let Some(retirement) = value.get_mut("Retire") {
            retirement
                .get_mut("audit")
                .unwrap()
                .as_object_mut()
                .unwrap()
                .remove("independent_operator_key_digests");
        }
        journal.push_str(JOURNAL_PREFIX);
        journal.push_str(&serde_json::to_string(&value).unwrap());
        journal.push('\n');
    }
    fs::write(&paths.journal, journal).unwrap();
    let mut control = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    let legacy = control.native_record("request-1").unwrap().clone();
    assert_eq!(legacy.state, NativeReservationState::Indeterminate);
    assert!(
        legacy
            .retirement
            .as_ref()
            .unwrap()
            .independent_operator_key_digests
            .is_none()
    );
    assert_eq!(
        control.reserve_native(request("request-2"), 1),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.retire_native_indeterminate("request-1", &fixture.plan, NOW, &old_verified),
        Err(Error::InvalidTransition),
    );

    let fresh_signed = retirement_for_record(&fixture, &legacy);
    let fresh_verified =
        verify_indeterminate_retirement(NOW, &fixture.trust, &fixture.plan, &fresh_signed).unwrap();
    let mut duplicate_key_audit = legacy.retirement.clone().unwrap();
    duplicate_key_audit.independent_operator_key_digests = Some(["a".repeat(64), "a".repeat(64)]);
    assert_eq!(
        control.commit_native(
            "request-1",
            Event::Retire {
                request_id: "request-1".to_string(),
                audit: duplicate_key_audit,
            }
        ),
        Err(Error::InvalidTransition),
    );
    assert_eq!(control.native_record("request-1"), Some(&legacy));
    let released = control
        .retire_native_indeterminate("request-1", &fixture.plan, NOW, &fresh_verified)
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(
        released
            .retirement
            .as_ref()
            .unwrap()
            .independent_operator_key_digests
            .as_ref(),
        Some(fresh_verified.key_fingerprints()),
    );
    assert_eq!(
        control.retire_native_indeterminate("request-1", &fixture.plan, NOW, &fresh_verified),
        Err(Error::InvalidTransition),
    );
    control.reserve_native(request("request-2"), 1).unwrap();
    drop(control);
    let reopened = DurableInferenceControl::open(&paths.journal, 8).unwrap();
    assert_eq!(reopened.native_record("request-1"), Some(&released));
}

#[test]
#[ignore = "qualification soak; executed by hepta-inference-maintenance"]
fn post_compaction_multi_generation_curve() {
    let paths = TestPaths::new("multi-generation-soak");
    let mut control = DurableInferenceControl::open(&paths.journal, 4096).unwrap();
    let mut largest_active = 0_u64;
    let mut previous_chain = None;
    for index in 0..1024 {
        let request_id = format!("request-{index}");
        control.reserve_native(request(&request_id), 8).unwrap();
        control
            .stop_native_before_dispatch(&request_id, "soak terminal".to_string())
            .unwrap();
        if (index + 1) % 64 == 0 {
            let receipt = control.compact_native_journal().unwrap();
            assert!(receipt.active_journal_bytes < 4096);
            assert_ne!(
                previous_chain.as_deref(),
                Some(receipt.archive_chain_digest.as_str())
            );
            previous_chain = Some(receipt.archive_chain_digest);
            largest_active = largest_active.max(receipt.active_journal_bytes);
            drop(control);
            control = DurableInferenceControl::open(&paths.journal, 4096).unwrap();
        }
    }
    let metrics = control.native_metrics(NOW);
    assert_eq!(metrics.checkpoint_generation, 16);
    assert_eq!(metrics.released, 1024);
    assert!(largest_active < 4096);
}

#[path = "native_checkpoint_migration_tests.rs"]
mod checkpoint_migration_tests;
