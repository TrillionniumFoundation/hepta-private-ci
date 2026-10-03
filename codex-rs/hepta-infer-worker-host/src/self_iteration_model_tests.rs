use super::*;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::StableId;

fn request() -> SelfIterationModelRequestV1 {
    SelfIterationModelRequestV1 {
        request_id: StableId::new("assessment-1").unwrap(),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: Digest32::of_bytes(b"envelope"),
        candidate_digest: None,
        prompt: "Suggest one bounded change".to_string(),
        deadline_ms: 10_000,
        maximum_response_bytes: 1024,
    }
}

// These exercise the adapter's receipt boundary with real durable journal
// transitions and reopening. Provider execution is covered by product E2E;
// this fixture does not claim to establish provider or issuer authority.
pub(super) fn settle_fixture(control: &mut DurableInferenceControl) -> NativeRunOutput {
    control
        .reserve_native(
            NativeRequest {
                request_id: "assessment-1".to_string(),
                principal_id: "agent-1".to_string(),
                worker_generation: 1,
                model: "fixture-model".to_string(),
                payload_digest: "a".repeat(64),
            },
            1,
        )
        .unwrap();
    control
        .dispatch_native(
            "assessment-1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "fixture-provider".to_string(),
                context_digest: "b".repeat(64),
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
            },
        )
        .unwrap();
    control
        .native_started("assessment-1", "turn-1".to_string())
        .unwrap();
    let output = NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "fixture-model".to_string(),
        model_provider: "fixture-provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "bounded candidate".to_string(),
        observed_output_tokens: Some(3),
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some("c".repeat(64)),
    };
    control
        .settle_native("assessment-1", output.clone())
        .unwrap();
    output
}

#[test]
fn assessment_resolves_exact_durable_terminal_after_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("native.journal");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let output = settle_fixture(&mut control);
    let original = assessment_from_record(
        &request(),
        control.native_record("assessment-1").unwrap(),
        output.clone(),
    )
    .unwrap();
    assert!(!original.authority.grants_any());
    assert_ne!(
        original.native_run_digest,
        Digest32::of_bytes(original.model_output.as_bytes())
    );
    drop(control);
    let control = DurableInferenceControl::open(&path, 8).unwrap();
    let reopened = assessment_from_record(
        &request(),
        control.native_record("assessment-1").unwrap(),
        output,
    )
    .unwrap();
    assert_eq!(original, reopened);
}

#[test]
fn mismatched_unverified_or_oversized_output_cannot_be_an_assessment() {
    let directory = tempfile::tempdir().unwrap();
    let mut control =
        DurableInferenceControl::open(directory.path().join("native.journal"), 8).unwrap();
    let output = settle_fixture(&mut control);
    let record = control.native_record("assessment-1").unwrap();
    let mut unrelated = output.clone();
    unrelated.output = "other text".to_string();
    assert!(assessment_from_record(&request(), record, unrelated).is_err());
    let mut unverified = output.clone();
    unverified.owner_authority = NativeOwnerAuthority::Unverified;
    assert!(assessment_from_record(&request(), record, unverified).is_err());
    let mut capped = request();
    capped.maximum_response_bytes = 1;
    assert!(assessment_from_record(&capped, record, output).is_err());
}

#[test]
fn roles_and_frozen_inputs_change_native_input_and_oversize_is_rejected() {
    let original = request();
    let prompt = bound_prompt(&original).unwrap();
    for mutation in 0..4 {
        let mut changed = original.clone();
        match mutation {
            0 => changed.role = SelfIterationModelRoleV1::Evaluator,
            1 => changed.envelope_digest = Digest32::of_bytes(b"other envelope"),
            2 => changed.candidate_digest = Some(Digest32::of_bytes(b"candidate")),
            _ => changed.maximum_response_bytes += 1,
        }
        assert_ne!(bound_prompt(&changed).unwrap(), prompt);
    }
    let mut oversized = original;
    oversized.prompt = "x".repeat(NATIVE_PROMPT_LIMIT);
    assert!(bound_prompt(&oversized).is_err());
}
