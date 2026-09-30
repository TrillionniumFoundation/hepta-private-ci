use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::*;

fn path(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-native-v2-{label}-{nonce}.journal"))
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "worker.local.1".to_string(),
        worker_generation: 2,
        model: "model.local.1".to_string(),
        payload_digest: "a".repeat(64),
    }
}

fn local_dispatch() -> NativeDispatch {
    NativeDispatch {
        thread_id: "local.handle.1".to_string(),
        model_provider: LOCAL_MODEL_PROVIDER_ID.to_string(),
        context_digest: "b".repeat(64),
        owner_context_digest: Some("c".repeat(64)),
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

fn quarantined_terminal() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "local.handle.1".to_string(),
        turn_id: "request.local.1".to_string(),
        model: "model.local.1".to_string(),
        model_provider: LOCAL_MODEL_PROVIDER_ID.to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Quarantined,
        output: "d".repeat(64),
        observed_output_tokens: Some(7),
        terminal_observed: true,
        stop_reason: Some("trusted terminal resource evidence missing".to_string()),
        owner_authority: NativeOwnerAuthority::Lost {
            reason: "live authority no longer current".to_string(),
        },
        codex_terminal_correlation_digest: Some("e".repeat(64)),
    }
}

fn start_local(control: &mut DurableInferenceControl) {
    control.reserve_native(request("request.local.1"), 1).unwrap();
    control
        .dispatch_native("request.local.1", local_dispatch())
        .unwrap();
    control
        .native_started_at("request.local.1", "request.local.1".to_string(), 1_100)
        .unwrap();
}

#[test]
fn local_quarantined_terminal_holds_durable_capacity_until_release_evidence() {
    let path = path("quarantine-capacity");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start_local(&mut control);
    let held = control
        .settle_native_with_evidence(
            "request.local.1",
            quarantined_terminal(),
            NativeObservationEvidence {
                observed_at_unix_ms: 1_200,
                usage_units: Some(11),
                usage_authority: NativeUsageAuthority::DriverObserved,
                resource_attestation_digest: None,
                terminal_evidence_digest: Some("e".repeat(64)),
                quarantine_reason: Some(
                    "trusted terminal resource evidence missing".to_string(),
                ),
                generation_fence_identity: Some("f".repeat(64)),
            },
        )
        .unwrap();
    assert_eq!(held.state, NativeReservationState::Indeterminate);
    assert!(held.observation.as_ref().unwrap().terminal_observed);
    assert_eq!(
        control.reserve_native(request("request.local.2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);

    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        control.native_record("request.local.1").unwrap().state,
        NativeReservationState::Indeterminate
    );
    assert_eq!(
        control.reserve_native(request("request.local.2"), 1),
        Err(Error::CapacityExceeded)
    );
    let released = control
        .release_native_quarantine(
            "request.local.1",
            NativeCapacityReleaseEvidence {
                observed_at_unix_ms: 1_300,
                evidence_digest: "1".repeat(64),
                reason: "independent zero-residency observation".to_string(),
            },
        )
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(
        released
            .observation
            .as_ref()
            .unwrap()
            .boundary_status,
        NativeBoundaryStatus::Quarantined
    );
    control
        .reserve_native(request("request.local.2"), 1)
        .unwrap();
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn authority_frontier_and_interrupt_evidence_are_durable_and_monotonic() {
    let path = path("authority-interrupt");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start_local(&mut control);
    let authority = NativeAuthorityObservation {
        issuer: "trusted.local.issuer".to_string(),
        grant_id: "grant.local.1".to_string(),
        authority_epoch: 5,
        revocation_revision: 8,
        revocation_head_digest: "2".repeat(64),
        grant_witness_digest: "3".repeat(64),
        authority_snapshot_digest: "4".repeat(64),
        observed_at_unix_ms: 1_050,
        revoked: false,
    };
    control
        .observe_native_authority("request.local.1", authority.clone())
        .unwrap();
    let mut rollback = authority.clone();
    rollback.revocation_revision = 7;
    assert_eq!(
        control.observe_native_authority("request.local.1", rollback),
        Err(Error::Conflict)
    );

    control
        .record_native_interrupt_intent(
            "request.local.1",
            "authority frontier advanced".to_string(),
            1_150,
        )
        .unwrap();
    control
        .record_native_interrupt_outcome(
            "request.local.1",
            NativeInterruptObservation {
                reason: "authority frontier advanced".to_string(),
                requested_at_unix_ms: 1_150,
                observed_at_unix_ms: Some(1_160),
                outcome: NativeInterruptOutcome::Ambiguous,
                evidence_digest: Some("5".repeat(64)),
            },
        )
        .unwrap();
    drop(control);

    let control = DurableInferenceControl::open(&path, 8).unwrap();
    let record = control.native_record("request.local.1").unwrap();
    assert_eq!(record.schema_version, NATIVE_RECORD_SCHEMA_VERSION);
    assert_eq!(record.effect_entered_at_unix_ms, Some(1_100));
    assert_eq!(record.authority_observation, Some(authority));
    assert_eq!(
        record.interrupt_observation.as_ref().unwrap().outcome,
        NativeInterruptOutcome::Ambiguous
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn provider_verified_usage_cannot_be_downgraded() {
    let path = path("usage-authority");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    start_local(&mut control);
    let mut output = quarantined_terminal();
    output.terminal_observed = false;
    output.status = NativeRunStatus::Indeterminate;
    output.boundary_status = NativeBoundaryStatus::Quarantined;
    output.output.clear();
    output.observed_output_tokens = Some(3);
    output.codex_terminal_correlation_digest = None;
    control
        .settle_native_with_evidence(
            "request.local.1",
            output.clone(),
            NativeObservationEvidence {
                observed_at_unix_ms: 1_200,
                usage_units: Some(9),
                usage_authority: NativeUsageAuthority::ProviderVerified,
                ..NativeObservationEvidence::default()
            },
        )
        .unwrap();
    assert_eq!(
        control.settle_native_with_evidence(
            "request.local.1",
            output,
            NativeObservationEvidence {
                observed_at_unix_ms: 1_201,
                usage_units: Some(10),
                usage_authority: NativeUsageAuthority::DriverObserved,
                ..NativeObservationEvidence::default()
            },
        ),
        Err(Error::Conflict)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}
