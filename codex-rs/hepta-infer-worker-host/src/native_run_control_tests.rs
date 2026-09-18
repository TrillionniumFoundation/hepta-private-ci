use super::*;
use crate::native_app_server::NativeWorkerConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Principal;
use codex_hepta_contracts::QuotaReservation;
use codex_hepta_contracts::QuotaReservationState;
use codex_hepta_contracts::ResourceAdvertisement;
use codex_hepta_contracts::ResourceAdvertisementState;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SubjectRef;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn fixture(label: &str) -> (AppServerModelDriver, PathBuf, tempfile::TempDir) {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("hepta-native-host-{label}-{nonce}.journal"));
    let authority_state = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[73; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        authority_state.path(),
        "test-inference-issuer".to_string(),
        signer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .unwrap();
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: path.with_extension("nonexistent-socket"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "model".to_string(),
        timeout: Duration::from_secs(5),
        final_use_authority: authority,
    })
    .unwrap();
    (driver, path, authority_state)
}

fn request(driver: &AppServerModelDriver, admission: &NativeAdmission) -> NativeRequest {
    NativeRequest {
        request_id: "r1".to_string(),
        principal_id: driver.config.agent_id.to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: {
            let binding = admission
                .policy
                .admission_binding(
                    current_unix_seconds(),
                    &driver.config.agent_id.to_string(),
                    driver.config.generation,
                    &driver.config.model,
                    admission.maximum_output_tokens,
                    admission.maximum_budget_units,
                )
                .unwrap();
            digest(
                &serde_json::to_vec(&(
                    "hepta.native-request.v2",
                    "prompt",
                    Option::<String>::None,
                    &driver.config.agentd_socket,
                    driver.config.timeout.as_millis(),
                    admission.maximum_output_tokens,
                    admission.maximum_budget_units,
                    &binding,
                ))
                .unwrap(),
            )
        },
        maximum_output_tokens: admission.maximum_output_tokens,
        maximum_budget_units: admission.maximum_budget_units,
        admission: Some(
            admission
                .policy
                .admission_binding(
                    current_unix_seconds(),
                    &driver.config.agent_id.to_string(),
                    driver.config.generation,
                    &driver.config.model,
                    admission.maximum_output_tokens,
                    admission.maximum_budget_units,
                )
                .unwrap(),
        ),
    }
}

fn current_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

fn admission(driver: &AppServerModelDriver) -> NativeAdmission {
    let now = current_unix_seconds();
    let subject = SubjectRef::new(
        "tenant",
        "workspace",
        driver.config.agent_id.to_string(),
        "inference.control",
        driver.config.generation,
    )
    .unwrap();
    let quota = QuotaReservation {
        schema_version: 1,
        reservation_id: "reservation:test".to_string(),
        operation_sha256: Sha256Digest::for_bytes(b"operation"),
        decision_sha256: Sha256Digest::for_bytes(b"decision"),
        subject: subject.clone(),
        resource_sha256: Sha256Digest::for_bytes(b"resource"),
        reserved_requests: 4,
        reserved_tokens: 4096,
        reserved_concurrency: 1,
        reserved_day_budget: 1,
        state: QuotaReservationState::Held,
        expected_revision: 1,
        revision: 1,
        authority_epoch: 7,
        owner_epoch: 1,
        generation: driver.config.generation,
        fencing_token_sha256: Sha256Digest::for_bytes(b"fence"),
        not_before_unix_seconds: now.saturating_sub(1),
        expires_at_unix_seconds: now + 60,
        authority: false,
    };
    let resource = ResourceAdvertisement {
        schema_version: 1,
        advertisement_id: "advertisement:test".to_string(),
        resource_id: "resource:test".to_string(),
        owner: Principal::new("owner:test").unwrap(),
        subject: Some(subject),
        provider_id: "provider".to_string(),
        model: Some(driver.config.model.clone()),
        resource_sha256: Sha256Digest::for_bytes(b"resource"),
        quota_sha256: quota.digest().expect("quota digest"),
        capability_sha256: vec![Sha256Digest::for_bytes(b"infer")],
        state: ResourceAdvertisementState::Available,
        revision: 1,
        authority_epoch: 7,
        owner_epoch: 1,
        generation: driver.config.generation,
        fencing_token_sha256: Sha256Digest::for_bytes(b"fence"),
        not_before_unix_seconds: now.saturating_sub(1),
        expires_at_unix_seconds: now + 60,
        authority: false,
    };
    NativeAdmission {
        request_id: "r1".to_string(),
        maximum_in_flight: 1,
        maximum_output_tokens: 512,
        maximum_budget_units: 1,
        policy: NativeExecutionPolicy { quota, resource },
    }
}

fn deny_grant(_: &FinalUseBinding) -> Result<SignedFinalUseGrant, GrantResolveError> {
    Err(std::io::Error::other("grant resolver must not be called").into())
}

#[tokio::test]
async fn reopened_dispatch_and_completed_duplicate_never_connect_to_provider() {
    let (driver, path, _authority_state) = fixture("reopen");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let admission = admission(&driver);
    control
        .reserve_native(request(&driver, &admission), 1)
        .unwrap();
    control
        .dispatch_native(
            "r1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "a".repeat(64),
                final_use: Some(
                    codex_hepta_infer_core::durable_control::native::NativeFinalUseWitness {
                        grant_id: "grant:test".to_string(),
                        authority_epoch: 7,
                        expires_at_unix_ms: u64::MAX,
                        binding_digest: "a".repeat(64),
                    },
                ),
            },
        )
        .unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let cancellation = CancellationToken::new();
    // The nonexistent socket makes any accidental second dispatch fail.
    let unknown = driver
        .run(
            &mut control,
            admission.clone(),
            "prompt".to_string(),
            None,
            &cancellation,
            &deny_grant,
        )
        .await
        .unwrap();
    assert_eq!(unknown.status, NativeRunStatus::Indeterminate);
    assert_eq!(unknown.observed_output_tokens, None);
    assert!(!unknown.terminal_observed);
    assert_eq!(
        control.native_record("r1").unwrap().state,
        NativeReservationState::Indeterminate
    );
    assert_eq!(
        driver
            .run(
                &mut control,
                admission.clone(),
                "prompt".to_string(),
                None,
                &cancellation,
                &deny_grant
            )
            .await
            .unwrap(),
        unknown
    );
    assert!(
        driver
            .run(
                &mut control,
                admission.clone(),
                "changed prompt".to_string(),
                None,
                &cancellation,
                &deny_grant
            )
            .await
            .is_err()
    );
    let terminal = NativeRunOutput {
        turn_id: "turn-1".to_string(),
        status: NativeRunStatus::Failed,
        terminal_observed: true,
        observed_output_tokens: Some(17),
        stop_reason: Some("observed terminal failure".to_string()),
        ..unknown
    };
    control.settle_native("r1", terminal.clone()).unwrap();
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        driver
            .run(
                &mut control,
                admission.clone(),
                "prompt".to_string(),
                None,
                &cancellation,
                &deny_grant
            )
            .await
            .unwrap(),
        terminal
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[tokio::test]
async fn pre_dispatch_cancellation_and_connection_failure_release_without_usage_claims() {
    for cancelled in [true, false] {
        let (driver, path, _authority_state) =
            fixture(if cancelled { "cancel" } else { "connection" });
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let admission = admission(&driver);
        let cancellation = CancellationToken::new();
        if cancelled {
            cancellation.cancel();
        }
        assert!(
            driver
                .run(
                    &mut control,
                    admission.clone(),
                    "prompt".to_string(),
                    None,
                    &cancellation,
                    &deny_grant,
                )
                .await
                .is_err()
        );
        let stopped = control.native_record("r1").unwrap().clone();
        assert_eq!(stopped.state, NativeReservationState::Released);
        assert_eq!(stopped.observation, None);
        assert!(stopped.pre_dispatch_stop.is_some());
        drop(control);
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        assert!(
            driver
                .run(
                    &mut control,
                    admission.clone(),
                    "prompt".to_string(),
                    None,
                    &CancellationToken::new(),
                    &deny_grant
                )
                .await
                .is_err()
        );
        assert_eq!(control.native_record("r1"), Some(&stopped));
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}
