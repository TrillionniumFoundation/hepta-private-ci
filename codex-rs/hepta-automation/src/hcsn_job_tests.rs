#![allow(
    clippy::expect_used,
    reason = "HCSN protocol fixtures should fail loudly"
)]

use super::*;

fn start() -> HcsnSupervisorCommandV1 {
    let payload = "{\"operation_id\":\"joint-graph\"}".to_string();
    let identity = HcsnJobIdentityV1::for_taskflow(
        "provider:hcsn",
        "run-one",
        "training",
        Sha256Digest::for_bytes(payload.as_bytes()),
    )
    .expect("identity");
    HcsnSupervisorCommandV1::start(identity, payload).expect("start")
}

fn completed(command: &HcsnSupervisorCommandV1) -> HcsnJobObservationV1 {
    HcsnJobObservationV1 {
        schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
        dispatch: command.dispatch.clone(),
        target: command.target.clone(),
        state: HcsnJobStateV1::Succeeded,
        process: Some(HcsnProcessIdentityV1 {
            host_id: Sha256Digest::for_bytes(b"host"),
            process_id: 47,
            incarnation: Sha256Digest::for_bytes(b"boot-id:start-ticks"),
        }),
        evidence: Some(HcsnJobEvidenceV1 {
            receipt_sha256: Sha256Digest::for_bytes(b"receipt"),
            candidate_sha256: Some(Sha256Digest::for_bytes(b"candidate")),
            handoff_sha256: Some(Sha256Digest::for_bytes(b"handoff")),
        }),
    }
}

#[test]
fn immutable_identity_uses_existing_taskflow_key_and_binds_exact_bytes() {
    let command = start();
    assert_eq!(
        command.dispatch.key,
        ProviderEffectKey::for_logical_effect("provider:hcsn", "taskflow:run-one:training",)
            .expect("provider key")
    );
    let changed = HcsnJobIdentityV1::for_key(
        command.dispatch.key.clone(),
        Sha256Digest::for_bytes(b" {\"operation_id\":\"joint-graph\"}"),
    )
    .expect("changed identity");
    assert_eq!(changed.key, command.dispatch.key);
    assert_ne!(changed.job_id, command.dispatch.job_id);
    assert_ne!(changed.output_id, command.dispatch.output_id);
    assert_eq!(
        HcsnSupervisorCommandV1::start(changed, command.payload.expect("payload")),
        Err(HcsnSupervisorError::BeforeContact)
    );
}

#[test]
fn legacy_taskflow_key_separator_cannot_alias_two_jobs() {
    let digest = Sha256Digest::for_bytes(b"{}");
    let allowed = HcsnJobIdentityV1::for_taskflow("provider:hcsn", "a:b", "c", digest.clone());
    assert!(allowed.is_ok());
    assert_eq!(
        HcsnJobIdentityV1::for_taskflow("provider:hcsn", "a", "b:c", digest),
        Err(HcsnSupervisorError::BeforeContact)
    );
}

#[test]
fn deserialized_identity_and_digest_tampering_are_rejected() {
    let command = start();
    let mut value = serde_json::to_value(&command).expect("serialize");
    value["dispatch"]["output_id"] = serde_json::json!(Sha256Digest::for_bytes(b"foreign-output"));
    let tampered: HcsnSupervisorCommandV1 = serde_json::from_value(value).expect("decode identity");
    assert_eq!(tampered.validate(), Err(HcsnSupervisorError::BeforeContact));

    let mut value = serde_json::to_value(completed(&command)).expect("serialize");
    value["evidence"]["candidate_sha256"] = serde_json::json!("invalid-digest");
    let tampered: HcsnJobObservationV1 = serde_json::from_value(value).expect("decode receipt");
    assert_eq!(
        tampered.validate_for(&command),
        Err(HcsnSupervisorError::Unknown)
    );
}

#[test]
fn completion_requires_matching_dispatch_process_and_all_output_hashes() {
    let command = start();
    let observation = completed(&command);
    assert_eq!(observation.validate_for(&command), Ok(()));
    let mut missing_candidate = observation.clone();
    missing_candidate
        .evidence
        .as_mut()
        .expect("evidence")
        .candidate_sha256 = None;
    let mut missing_handoff = observation.clone();
    missing_handoff
        .evidence
        .as_mut()
        .expect("evidence")
        .handoff_sha256 = None;
    let mut missing_process = observation.clone();
    missing_process.process = None;
    let mut wrong_target = observation;
    wrong_target.target = HcsnJobIdentityV1::for_taskflow(
        "provider:hcsn",
        "other-run",
        "training",
        command.target.payload_sha256.clone(),
    )
    .expect("other target");
    for invalid in [
        missing_candidate,
        missing_handoff,
        missing_process,
        wrong_target,
    ] {
        assert_eq!(
            invalid.validate_for(&command),
            Err(HcsnSupervisorError::Unknown)
        );
    }
}

#[test]
fn cancellation_is_a_distinct_dispatch_and_status_carries_no_start_payload() {
    let original = start();
    let bytes = serde_json::to_vec(&original.target).expect("cancel payload");
    let cancel_identity = HcsnJobIdentityV1::for_taskflow(
        "provider:hcsn",
        "run-one",
        "cancel-training",
        Sha256Digest::for_bytes(&bytes),
    )
    .expect("cancel identity");
    let cancel = HcsnSupervisorCommandV1::cancel(cancel_identity.clone(), original.target.clone())
        .expect("cancel command");
    assert_eq!(
        cancel.status(),
        HcsnSupervisorCommandV1 {
            schema_version: HCSN_SUPERVISOR_SCHEMA_VERSION,
            action: HcsnSupervisorActionV1::Status,
            dispatch: cancel_identity,
            target: original.target.clone(),
            payload: None,
        }
    );
    assert_eq!(
        HcsnSupervisorCommandV1::cancel(original.target.clone(), original.target),
        Err(HcsnSupervisorError::BeforeContact)
    );
}

#[test]
fn terminal_failure_or_cancel_needs_a_durable_receipt() {
    let command = start();
    let mut observation = completed(&command);
    for state in [HcsnJobStateV1::Failed, HcsnJobStateV1::Cancelled] {
        observation.state = state;
        observation.evidence = None;
        assert_eq!(
            observation.validate_for(&command),
            Err(HcsnSupervisorError::Unknown)
        );
        observation.evidence = Some(HcsnJobEvidenceV1 {
            receipt_sha256: Sha256Digest::for_bytes(b"terminal-with-cost"),
            candidate_sha256: None,
            handoff_sha256: None,
        });
        assert_eq!(observation.validate_for(&command), Ok(()));
    }
}

#[test]
fn reserved_and_unknown_never_accept_terminal_evidence() {
    let command = start();
    let mut observation = completed(&command);
    for state in [HcsnJobStateV1::Reserved, HcsnJobStateV1::Unknown] {
        observation.state = state;
        assert_eq!(
            observation.validate_for(&command),
            Err(HcsnSupervisorError::Unknown)
        );
    }
    observation.evidence = None;
    observation.process = None;
    assert_eq!(observation.validate_for(&command), Ok(()));
}
