use super::*;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::StableId;

fn scope() -> RootNativeAssessmentScopeV1<'static> {
    RootNativeAssessmentScopeV1 {
        subject: "original-agent",
        model: "fixture-model",
        model_provider: "fixture-provider",
        app_server_executable_digest: Digest32::of_bytes(b"original-normal-app-server"),
        cgroup: "/original-agent-generation",
        agentd_socket: Path::new("/original/agentd.sock"),
        native_timeout_ms: 3000,
    }
}

// Real local reserve/dispatch/settle/reopen; the relay and executable facts are
// explicit test fixtures, not a provider execution or installed grant proof.
fn fixture() -> (
    SelfIterationModelRequestV1,
    NativeRunRecord,
    RootModelTerminalReceiptV1,
) {
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new("original-model-request").unwrap(),
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest: Digest32::of_bytes(b"original-envelope"),
        candidate_digest: None,
        prompt: "Choose an installed candidate".into(),
        deadline_ms: 10000,
        maximum_response_bytes: 1024,
    };
    let scope = scope();
    let prompt = bound_prompt(&request).unwrap();
    let source = crate::native_app_server::native_source_payload_digest(
        &prompt,
        &None,
        scope.agentd_socket,
        scope.native_timeout_ms,
        /*intelligence*/ None,
        crate::native_app_server::NativeDeadlinePolicy::Absolute(request.deadline_ms),
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("native.journal");
    let mut owner = DurableInferenceControl::open(&path, 8).unwrap();
    owner
        .reserve_native(
            NativeRequest {
                request_id: request.request_id.to_string(),
                principal_id: scope.subject.into(),
                worker_generation: 1,
                model: scope.model.into(),
                payload_digest: source.clone(),
            },
            1,
        )
        .unwrap();
    let digest = Digest32::of_bytes(b"explicit-runtime-fixture").to_string();
    owner
        .dispatch_native(
            request.request_id.as_str(),
            NativeDispatch {
                thread_id: "original-thread".into(),
                model_provider: scope.model_provider.into(),
                context_digest: Digest32::of_bytes(b"null").to_string(),
                owner_context_digest: None,
                codex_payload_digest: Some(digest.clone()),
                codex_request_digest: Some(digest.clone()),
                app_server_version: Some("fixture-version".into()),
                protocol_id: Some(codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID.into()),
                codex_source_admission_digest: Some(source),
                codex_home_digest: Some(digest.clone()),
                codex_connection_id: Some(1),
                codex_session_id: Some("original-session".into()),
                codex_deadline_ms: Some(10000),
                codex_authority_epoch: Some(1),
                codex_revocation_revision: Some(1),
                codex_revocation_head_sha256: Some(digest.clone()),
                codex_authority_witness_sha256: Some(digest.clone()),
            },
        )
        .unwrap();
    owner
        .native_started(request.request_id.as_str(), "original-turn".into())
        .unwrap();
    let text = "  原始\ntext\t🙂  ";
    owner
        .settle_native(
            request.request_id.as_str(),
            NativeRunOutput {
                thread_id: "original-thread".into(),
                turn_id: "original-turn".into(),
                model: scope.model.into(),
                model_provider: scope.model_provider.into(),
                status: NativeRunStatus::Completed,
                boundary_status: NativeBoundaryStatus::Succeeded,
                output: text.into(),
                observed_output_tokens: None,
                terminal_observed: true,
                stop_reason: None,
                owner_authority: NativeOwnerAuthority::ObservedReady,
                codex_terminal_correlation_digest: Some(digest),
            },
        )
        .unwrap();
    drop(owner);
    let owner = DurableInferenceControl::open(&path, 8).unwrap();
    let record = owner
        .native_record(request.request_id.as_str())
        .unwrap()
        .clone();
    let witness = serde_json::from_value(serde_json::json!({
        "schema":"hepta.root-model-terminal.v1", "subject":scope.subject,
        "model":scope.model, "pid":17, "start_ticks":33, "cgroup":scope.cgroup,
        "executable_sha256":scope.app_server_executable_digest.to_string(),
        "request_sha256":vec![1_u8;32], "scope_sha256":vec![2_u8;32], "payload_sha256":vec![3_u8;32],
        "native_prompt":prompt, "admitted_at_ms":1000, "completed_at_ms":2000,
        "response_id":"original-provider-response", "stream_sha256":vec![4_u8;32],
        "model_output_sha256":Digest32::of_bytes(text.as_bytes()).as_array(),
        "model_output_bytes":text.len(),
        "binding":{"request_id":request.request_id.as_str(), "role":"Generator",
          "envelope_digest":request.envelope_digest.to_string(), "candidate_digest":null,
          "deadline_ms":request.deadline_ms,"maximum_response_bytes":request.maximum_response_bytes}
    })).unwrap();
    (request, record, witness)
}

#[test]
fn complete_original_advice_after_reopen_needs_no_intelligence_ack() {
    let (request, record, witness) = fixture();
    let actual =
        validate_root_native_assessment_facts_v1(&request, &record, &witness, &scope(), 3000)
            .unwrap();
    let expected =
        assessment_from_record(&request, &record, record.observation.clone().unwrap()).unwrap();
    assert_eq!(actual, expected);
    assert!(!actual.authority.grants_any());
    assert!(record.terminal_owner.is_none() && record.terminal_publication.is_none());
}

#[test]
fn full_prompt_socket_timeout_and_utf8_output_must_join_original_sources() {
    let (request, record, witness) = fixture();
    let mut changed = witness.clone();
    changed.native_prompt.push(' ');
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &changed, &scope(), 3000)
            .is_err()
    );
    let mut changed = scope();
    changed.agentd_socket = Path::new("/substituted/agentd.sock");
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &witness, &changed, 3000)
            .is_err()
    );
    let mut changed = scope();
    changed.native_timeout_ms += 1;
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &witness, &changed, 3000)
            .is_err()
    );
    let mut changed = record.clone();
    changed.observation.as_mut().unwrap().output = "原始text🙂".into();
    assert!(
        validate_root_native_assessment_facts_v1(&request, &changed, &witness, &scope(), 3000)
            .is_err()
    );
}

#[test]
fn historical_process_facts_remain_complete_but_late_or_backwards_use_is_denied() {
    let (request, record, witness) = fixture();
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &witness, &scope(), 3000)
            .is_ok()
    );
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &witness, &scope(), 1500)
            .is_err()
    );
    assert!(
        validate_root_native_assessment_facts_v1(
            &request,
            &record,
            &witness,
            &scope(),
            request.deadline_ms
        )
        .is_err()
    );
    let mut changed = witness.clone();
    changed.completed_at_ms = request.deadline_ms;
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &changed, &scope(), 3000)
            .is_err()
    );
    assert_eq!(witness.completed_at_ms, 2000);
}

#[test]
fn provider_success_does_not_replace_original_runtime_release_or_identity() {
    let (request, record, witness) = fixture();
    for mutation in 0..6 {
        let mut changed = record.clone();
        match mutation {
            0 => changed.state = NativeReservationState::Indeterminate,
            1 => {
                changed.observation.as_mut().unwrap().owner_authority =
                    NativeOwnerAuthority::Unverified
            }
            2 => changed.request.principal_id = "another-agent".into(),
            3 => {
                changed
                    .dispatch
                    .as_mut()
                    .unwrap()
                    .codex_authority_witness_sha256 = None
            }
            4 => {
                changed
                    .dispatch
                    .as_mut()
                    .unwrap()
                    .codex_source_admission_digest = None
            }
            _ => changed.observation.as_mut().unwrap().model_provider = "another-provider".into(),
        }
        assert!(
            validate_root_native_assessment_facts_v1(&request, &changed, &witness, &scope(), 3000)
                .is_err()
        );
    }
    let mut changed = witness;
    changed.executable_sha256 = Digest32::of_bytes(b"other-ELF").to_string();
    assert!(
        validate_root_native_assessment_facts_v1(&request, &record, &changed, &scope(), 3000)
            .is_err()
    );
}
