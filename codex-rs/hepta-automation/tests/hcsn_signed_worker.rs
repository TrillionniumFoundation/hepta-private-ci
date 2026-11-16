//! Explicit CPU engineering qualification. The supervisor and worker are real;
//! only the signing key and the lost first reply are synthetic test inputs.
#![cfg(target_os = "linux")]
#![allow(
    clippy::expect_used,
    reason = "explicit signed real-worker qualification"
)]

#[path = "support/hcsn_signed_cancel.rs"]
mod cancel;
#[path = "support/hcsn_signed_recovery.rs"]
mod recovery;
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
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        let actual = self.real.dispatch(request)?;
        self.contacts += 1;
        Ok(AuthorizedEffectProviderReceipt {
            outcome: AuthorizedEffectOutcome::Indeterminate,
            receipt_digest: Sha256Digest::for_bytes(
                format!(
                    "qualification-lost-reply:{}",
                    actual.receipt_digest.as_str()
                )
                .as_bytes(),
            ),
        })
    }
}

fn real_driver(config: &HcsnProcessSupervisorConfig) -> HcsnTaskFlowDriver<HcsnProcessSupervisor> {
    HcsnTaskFlowDriver::new(
        SCOPE.to_string(),
        HcsnTaskFlowActionV1::Start,
        HcsnProcessSupervisor::new(config.clone()).expect("pinned real supervisor"),
    )
    .expect("driver")
}

#[tokio::test]
#[ignore = "requires HEPTA_HCSN_SIGNED_WORKER_ROOT from verify_bridge --signed-worker-executable; invokes real CPU worker"]
async fn signed_authority_real_worker_cold_recovery() {
    let (root, config, config_bytes, payload) = inputs();
    match std::env::var(PHASE_ENV).as_deref() {
        Ok("recover") => recovery::recover(&root, &config, &config_bytes, &payload).await,
        Err(std::env::VarError::NotPresent) => {
            dispatch(&root, &config, &config_bytes, &payload).await
        }
        other => panic!("unexpected qualification phase: {other:?}"),
    }
}

#[tokio::test]
#[ignore = "requires a fresh CPU fixture from verify_cancel; cancels a real running worker"]
async fn signed_authority_real_worker_cancel_cold_recovery() {
    let (root, config, config_bytes, payload) = inputs();
    cancel::run(&root, &config, &config_bytes, &payload).await;
}

fn inputs() -> (PathBuf, HcsnProcessSupervisorConfig, Vec<u8>, Vec<u8>) {
    let root = PathBuf::from(
        std::env::var_os(ROOT_ENV)
            .expect("explicit qualification requires HEPTA_HCSN_SIGNED_WORKER_ROOT"),
    );
    assert!(root.is_absolute());
    assert_eq!(root.canonicalize().expect("canonical fixture"), root);
    let config_bytes = fs::read(root.join("supervisor-config.json")).expect("supervisor config");
    let file: SupervisorFile =
        serde_json::from_slice(&config_bytes).expect("strict supervisor config");
    // The fixture can never target an existing production or CUDA campaign store.
    assert_eq!(file.durable_root, root.join("supervisor-store"));
    let config = HcsnProcessSupervisorConfig {
        python_executable: file.python_executable,
        python_sha256: file.python_sha256,
        repository_root: file.repository_root,
        supervisor_sha256: file.supervisor_sha256,
        durable_root: file.durable_root,
        deadline: Duration::from_secs(10),
    };
    let payload = fs::read(root.join("request.json")).expect("exact worker request");
    (root, config, config_bytes, payload)
}

async fn dispatch(
    root: &Path,
    config: &HcsnProcessSupervisorConfig,
    config_bytes: &[u8],
    payload: &[u8],
) {
    assert_eq!(
        fs::read_dir(config.durable_root.join("jobs"))
            .expect("initialized jobs")
            .count(),
        0
    );
    assert_eq!(
        fs::read_dir(config.durable_root.join("cancellations"))
            .expect("initialized cancellations")
            .count(),
        0
    );
    let state = root.join("signed-taskflow-state");
    let fixture = Fixture::initialize(&state);
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let intent = fixture.prepare(&store, payload).await;
    let binding = intent.final_use_binding().expect("binding");
    let signed = fixture.sign(&intent);
    let mut driver = LostReply {
        real: real_driver(config),
        contacts: 0,
    };
    let mut invalid = signed.clone();
    invalid.signature[0] ^= 1;
    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &fixture.authority,
                &mut driver,
                &intent,
                payload,
                &fixture.owner,
                &invalid,
                &binding,
                "signed-worker-dispatch",
                now_ms(),
            )
            .await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::InvalidSignature
        ))
    ));
    assert_eq!(driver.contacts, 0);
    assert_eq!(
        fs::read_dir(config.durable_root.join("jobs"))
            .expect("jobs after rejected grant")
            .count(),
        0
    );
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("authority capacity")
            .used_nonces,
        0
    );
    write_new(
        &state.join("dispatch.json"),
        &DispatchRecord {
            intent: intent.clone(),
            signed: signed.clone(),
            payload_sha256: Sha256Digest::for_bytes(payload),
            config_sha256: Sha256Digest::for_bytes(config_bytes),
            parent_pid: std::process::id(),
        },
    );
    let receipt = store
        .execute_authorized_taskflow_effect(
            &fixture.authority,
            &mut driver,
            &intent,
            payload,
            &fixture.owner,
            &signed,
            &binding,
            "signed-worker-dispatch",
            now_ms(),
        )
        .await
        .expect("signed real supervisor dispatch");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(driver.contacts, 1);
    assert_eq!(
        fs::read_dir(config.durable_root.join("jobs"))
            .expect("reserved job")
            .count(),
        1
    );
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("authority capacity")
            .used_nonces,
        1
    );
    store.close().await;
    drop(store);
    drop(driver);
    drop(fixture);
    let child = Command::new(std::env::current_exe().expect("test executable"))
        .args(["--ignored", "--exact", TEST_NAME, "--nocapture"])
        .env(PHASE_ENV, "recover")
        .output()
        .expect("fresh native recovery process");
    write_new(
        &root.join("signed-taskflow-child.json"),
        &serde_json::json!({
            "success": child.status.success(), "stdout": String::from_utf8_lossy(&child.stdout),
            "stderr": String::from_utf8_lossy(&child.stderr),
        }),
    );
    assert!(
        child.status.success(),
        "fresh recovery process failed: {}",
        String::from_utf8_lossy(&child.stderr)
    );
    let result: serde_json::Value = serde_json::from_slice(
        &fs::read(root.join("signed-taskflow.json")).expect("completed evidence"),
    )
    .expect("result JSON");
    assert_eq!(result["status"], "passed");
}
