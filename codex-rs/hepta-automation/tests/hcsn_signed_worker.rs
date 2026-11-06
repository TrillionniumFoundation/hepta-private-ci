//! Explicit CPU engineering qualification. The supervisor and worker are real;
//! only the signing key and the lost first reply are synthetic test inputs.
#![cfg(target_os = "linux")]
#![allow(clippy::expect_used, reason = "explicit signed real-worker qualification")]

#[path = "support/hcsn_signed_worker.rs"]
mod support;

use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_automation::AuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedEffectRequest;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::HcsnJobIdentityV1;
use codex_hepta_automation::HcsnJobStateV1;
use codex_hepta_automation::HcsnProcessSupervisor;
use codex_hepta_automation::HcsnProcessSupervisorConfig;
use codex_hepta_automation::HcsnSupervisor;
use codex_hepta_automation::HcsnSupervisorCommandV1;
use codex_hepta_automation::HcsnTaskFlowActionV1;
use codex_hepta_automation::HcsnTaskFlowDriver;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use support::Fixture;
use support::SCOPE;
use support::now_ms;
use support::write_new;

const ROOT_ENV: &str = "HEPTA_HCSN_SIGNED_WORKER_ROOT";
const PHASE_ENV: &str = "HEPTA_HCSN_SIGNED_WORKER_PHASE";
const TEST_NAME: &str = "signed_authority_real_worker_cold_recovery";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SupervisorFile {
    python_executable: PathBuf,
    python_sha256: Sha256Digest,
    repository_root: PathBuf,
    supervisor_sha256: Sha256Digest,
    durable_root: PathBuf,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DispatchRecord {
    intent: AuthorizedEffectIntent,
    signed: SignedFinalUseGrant,
    payload_sha256: Sha256Digest,
    config_sha256: Sha256Digest,
    parent_pid: u32,
}

/// Fault injection after real provider contact, never a supervisor test double.
/// The ledger must retain uncertainty even if the actual first reply was terminal.
struct LostReply {
    real: HcsnTaskFlowDriver<HcsnProcessSupervisor>,
    contacts: usize,
}

impl AuthorizedEffectDriver for LostReply {
    fn dispatch(&mut self, request: &AuthorizedEffectRequest<'_>)
        -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError>
    {
        let actual = self.real.dispatch(request)?;
        self.contacts += 1;
        Ok(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: Sha256Digest::for_bytes(format!("qualification-lost-reply:{}", actual.receipt_digest.as_str()).as_bytes()),
        })
    }
}

fn real_driver(config: &HcsnProcessSupervisorConfig) -> HcsnTaskFlowDriver<HcsnProcessSupervisor> {
    HcsnTaskFlowDriver::new(SCOPE.to_string(), HcsnTaskFlowActionV1::Start,
        HcsnProcessSupervisor::new(config.clone()).expect("pinned real supervisor")).expect("driver")
}

#[tokio::test]
#[ignore = "requires HEPTA_HCSN_SIGNED_WORKER_ROOT from verify_bridge --signed-worker-executable; invokes real CPU worker"]
async fn signed_authority_real_worker_cold_recovery() {
    let root = PathBuf::from(std::env::var_os(ROOT_ENV).expect("explicit qualification requires HEPTA_HCSN_SIGNED_WORKER_ROOT"));
    assert!(root.is_absolute());
    assert_eq!(root.canonicalize().expect("canonical fixture"), root);
    let config_bytes = fs::read(root.join("supervisor-config.json")).expect("supervisor config");
    let file: SupervisorFile = serde_json::from_slice(&config_bytes).expect("strict supervisor config");
    // The fixture can never target an existing production or CUDA campaign store.
    assert_eq!(file.durable_root, root.join("supervisor-store"));
    let config = HcsnProcessSupervisorConfig {
        python_executable: file.python_executable, python_sha256: file.python_sha256,
        repository_root: file.repository_root, supervisor_sha256: file.supervisor_sha256,
        durable_root: file.durable_root, deadline: Duration::from_secs(10),
    };
    let payload = fs::read(root.join("request.json")).expect("exact worker request");
    match std::env::var(PHASE_ENV).as_deref() {
        Ok("recover") => recover(&root, &config, &config_bytes, &payload).await,
        Err(std::env::VarError::NotPresent) => dispatch(&root, &config, &config_bytes, &payload).await,
        other => panic!("unexpected qualification phase: {other:?}"),
    }
}

async fn dispatch(root: &Path, config: &HcsnProcessSupervisorConfig, config_bytes: &[u8], payload: &[u8]) {
    assert_eq!(fs::read_dir(config.durable_root.join("jobs")).expect("initialized jobs").count(), 0);
    assert_eq!(fs::read_dir(config.durable_root.join("cancellations")).expect("initialized cancellations").count(), 0);
    let state = root.join("signed-taskflow-state");
    let fixture = Fixture::initialize(&state);
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let intent = fixture.prepare(&store, payload).await;
    let binding = intent.final_use_binding().expect("binding");
    let signed = fixture.sign(&intent);
    let mut driver = LostReply { real: real_driver(config), contacts: 0 };
    let mut invalid = signed.clone();
    invalid.signature[0] ^= 1;
    assert!(matches!(store.execute_authorized_taskflow_effect(
        &fixture.authority, &mut driver, &intent, payload, &fixture.owner, &invalid,
        &binding, "signed-worker-dispatch", now_ms(),
    ).await, Err(AuthorizedEffectError::FinalUse(FinalUseError::InvalidSignature))));
    assert_eq!(driver.contacts, 0);
    assert_eq!(fs::read_dir(config.durable_root.join("jobs")).expect("jobs after rejected grant").count(), 0);
    assert_eq!(fixture.authority.capacity().expect("authority capacity").used_nonces, 0);
    write_new(&state.join("dispatch.json"), &DispatchRecord {
        intent: intent.clone(), signed: signed.clone(), payload_sha256: Sha256Digest::for_bytes(payload),
        config_sha256: Sha256Digest::for_bytes(config_bytes), parent_pid: std::process::id(),
    });
    let receipt = store.execute_authorized_taskflow_effect(
        &fixture.authority, &mut driver, &intent, payload, &fixture.owner, &signed,
        &binding, "signed-worker-dispatch", now_ms(),
    ).await.expect("signed real supervisor dispatch");
    assert_eq!(receipt.observation, Some(TaskFlowStepObservation::Indeterminate));
    assert_eq!(driver.contacts, 1);
    assert_eq!(fs::read_dir(config.durable_root.join("jobs")).expect("reserved job").count(), 1);
    assert_eq!(fixture.authority.capacity().expect("authority capacity").used_nonces, 1);
    store.close().await;
    drop(store);
    drop(driver);
    drop(fixture);
    let child = Command::new(std::env::current_exe().expect("test executable"))
        .args(["--ignored", "--exact", TEST_NAME, "--nocapture"])
        .env(PHASE_ENV, "recover")
        .output().expect("fresh native recovery process");
    write_new(&root.join("signed-taskflow-child.json"), &serde_json::json!({
        "success": child.status.success(), "stdout": String::from_utf8_lossy(&child.stdout),
        "stderr": String::from_utf8_lossy(&child.stderr),
    }));
    assert!(child.status.success(), "fresh recovery process failed: {}", String::from_utf8_lossy(&child.stderr));
    let result: serde_json::Value = serde_json::from_slice(&fs::read(root.join("signed-taskflow.json")).expect("completed evidence")).expect("result JSON");
    assert_eq!(result["status"], "passed");
}

async fn recover(root: &Path, config: &HcsnProcessSupervisorConfig, config_bytes: &[u8], payload: &[u8]) {
    let state = root.join("signed-taskflow-state");
    let record: DispatchRecord = serde_json::from_slice(&fs::read(state.join("dispatch.json")).expect("retained dispatch")).expect("dispatch JSON");
    assert_ne!(record.parent_pid, std::process::id());
    assert_eq!(record.payload_sha256, Sha256Digest::for_bytes(payload));
    assert_eq!(record.config_sha256, Sha256Digest::for_bytes(config_bytes));
    let fixture = Fixture::reopen(&state);
    let store = AutomationStore::open(&fixture.layout).await.expect("cold store");
    let binding = record.intent.final_use_binding().expect("retained binding");
    assert!(matches!(fixture.authority.claim(&record.signed, &binding), Err(FinalUseError::AlreadyClaimed)));
    assert_eq!(fixture.authority.capacity().expect("cold nonce journal").used_nonces, 1);
    let pending = store.pending_authorized_taskflow_effects(8).await.expect("cold pending");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].intent_digest, record.intent.digest().expect("retained intent digest"));
    let mut replay = LostReply { real: real_driver(config), contacts: 0 };
    assert!(store.execute_authorized_taskflow_effect(
        &fixture.authority, &mut replay, &record.intent, payload, &fixture.owner, &record.signed,
        &binding, "signed-worker-dispatch", now_ms(),
    ).await.is_err());
    assert_eq!(replay.contacts, 0, "the consumed logical attempt must never contact its provider again");
    let mut driver = real_driver(config);
    assert_eq!(driver.lookup(&pending[0], b"substituted request"), AuthorizedProviderEffectLookup::Unresolved);
    let deadline = Instant::now() + Duration::from_secs(60);
    let terminal = loop {
        match driver.lookup(&pending[0], payload) {
            AuthorizedProviderEffectLookup::Observed(receipt) => break receipt,
            AuthorizedProviderEffectLookup::Unresolved => {
                assert!(Instant::now() < deadline, "real worker remains unresolved; retain the existing job, never relaunch");
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            AuthorizedProviderEffectLookup::ProvenAbsent { .. } => panic!("HCSN must never infer absence"),
        }
    };
    assert_eq!(terminal.outcome, AuthorizedEffectOutcome::Succeeded);
    let identity = HcsnJobIdentityV1::for_taskflow(SCOPE, &record.intent.run_id, &record.intent.step_id, record.intent.payload_digest.clone()).expect("same job identity");
    let command = HcsnSupervisorCommandV1::start(identity.clone(), String::from_utf8(payload.to_vec()).expect("request UTF-8")).expect("original command");
    let mut supervisor = HcsnProcessSupervisor::new(config.clone()).expect("cold supervisor");
    let observation = supervisor.exchange(&command.status()).expect("bound terminal observation");
    assert_eq!(observation.state, HcsnJobStateV1::Succeeded);
    let job = config.durable_root.join("jobs").join(Sha256Digest::for_bytes(identity.key.as_str().as_bytes()).as_str());
    let runner = fs::read(job.join("runner.json")).expect("actual runner incarnation");
    let worker = fs::read(job.join("worker.json")).expect("actual worker incarnation");
    let evidence = observation.evidence.as_ref().expect("terminal evidence");
    let output = job.join(identity.output_id.as_str());
    for (name, digest) in [
        ("candidate.pt", evidence.candidate_sha256.as_ref().expect("candidate digest")),
        ("receipt.json", &evidence.receipt_sha256),
        ("handoff.bin", evidence.handoff_sha256.as_ref().expect("handoff digest")),
    ] {
        assert_eq!(Sha256Digest::for_bytes(&fs::read(output.join(name)).expect("actual worker output")), *digest);
    }
    let recovered = store.recover_authorized_taskflow_effect(
        &record.intent.run_id, &record.intent.step_id, record.intent.attempt, &fixture.owner,
        AuthorizedEffectRecovery::Observed(terminal.clone()), now_ms(),
    ).await.expect("recover original logical attempt");
    let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else { panic!("must recover observation"); };
    // Reconciliation preserves the first uncertain observation in the immutable
    // step history. Its terminal result is carried separately by final_outcome.
    assert_eq!(
        (receipt.state, receipt.observation, receipt.final_outcome, receipt.receipt_digest.as_ref()),
        (TaskFlowStepState::Reconciled, Some(TaskFlowStepObservation::Indeterminate),
            Some(TaskFlowReconcileOutcome::Succeeded), Some(&terminal.receipt_digest)),
    );
    assert!(store.pending_authorized_taskflow_effects(8).await.expect("settled scan").is_empty());
    assert_eq!(store.taskflow_run(&record.intent.run_id).await.expect("run query").expect("run").state, TaskFlowRunState::Succeeded);
    assert_eq!(driver.lookup(&pending[0], payload), AuthorizedProviderEffectLookup::Observed(terminal.clone()));
    assert_eq!(supervisor.exchange(&command.status()).expect("repeat terminal lookup"), observation);
    assert_eq!(fs::read(job.join("runner.json")).expect("retained runner"), runner);
    assert_eq!(fs::read(job.join("worker.json")).expect("retained worker"), worker);
    assert_eq!(fs::read_dir(config.durable_root.join("jobs")).expect("single job").count(), 1);
    store.close().await;
    let settled = AutomationStore::open(&fixture.layout).await.expect("reopen terminal projection");
    assert_eq!(
        settled.read_authorized_taskflow_effect_receipt(&record.intent, "signed-worker-dispatch")
            .await.expect("owner terminal receipt readback"),
        Some(receipt.clone()),
    );
    settled.close().await;
    write_new(&root.join("signed-taskflow.json"), &serde_json::json!({
        "schema_version": 1, "status": "passed", "observation": observation,
        "intent_digest": record.intent.digest().expect("intent digest"),
        "request_file_sha256": record.payload_sha256, "supervisor_config_sha256": record.config_sha256,
        "grant_id": record.signed.grant.grant_id, "authority_epoch": record.signed.grant.authority_epoch,
        "parent_pid": record.parent_pid, "cold_native_pid": std::process::id(),
        "provider_receipt_digest": terminal.receipt_digest, "taskflow_receipt_digest": receipt.receipt_digest,
        "taskflow_step_receipt": receipt, "terminal_step_readback_exact": true,
        "historical_observation_preserved": true,
        "invalid_signature_rejected_before_contact": true, "lost_first_reply_injected": true,
        "cold_sqlite_recovery": true, "cold_authority_nonce_recovery": true, "replay_contacts": replay.contacts,
        "retained_job_count": 1, "runner_sha256": Sha256Digest::for_bytes(&runner), "worker_sha256": Sha256Digest::for_bytes(&worker),
        "actual_output_digests_verified": true, "candidate_only": true,
        "host_registration_exercised": false, "authority_profile": "synthetic_ed25519_v1",
        "production_ml_dsa65_v2": "unavailable_on_this_baseline",
        "synthetic_test_key_only": true, "production_trust": false, "production_adoption": false,
        "scope": "real signed AutomationStore to pinned supervisor and actual CPU worker; synthetic Ed25519 engineering authority, no production PQ qualification",
    }));
}
