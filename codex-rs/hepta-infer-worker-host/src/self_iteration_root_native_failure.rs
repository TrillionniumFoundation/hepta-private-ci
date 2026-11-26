//! Typed failure requires both original native release and independent Root facts.
use super::*;
use codex_hepta_infer_core::SelfIterationModelFailureFactsV1;
use codex_hepta_infer_core::SelfIterationModelFailureKindV1;
use codex_hepta_infer_core::SelfIterationModelFailureV1;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_infer_core::durable_control::native::NativeTerminalPublicationPhase;
use codex_hepta_infer_core::encode_self_iteration_model_failure_facts_v1;
use codex_hepta_supervisor::RootModelFailureV1;
use codex_hepta_supervisor::RootModelOutcomeReceiptV1;

/// Pure join only. The installed Root port authenticates the current original
/// native reader and independently loads the protected provider outcome.
pub fn validate_root_native_failure_facts_v1(
    facts: &SelfIterationModelFailureFactsV1,
    scope: &RootNativeAssessmentScopeV1<'_>,
) -> Result<SelfIterationModelFailureV1, SelfIterationModelErrorV1> {
    let invalid = || SelfIterationModelErrorV1::InvalidResponse;
    let request = &facts.request;
    request.validate(
        request
            .deadline_ms
            .checked_sub(1)
            .ok_or(SelfIterationModelErrorV1::InvalidRequest)?,
    )?;
    let encoded = encode_self_iteration_model_failure_facts_v1(facts)?;
    let root: RootModelOutcomeReceiptV1 =
        serde_json::from_slice(&facts.root_outcome_bytes).map_err(|_| invalid())?;
    if serde_json::to_vec(&root).map_err(|_| invalid())? != facts.root_outcome_bytes {
        return Err(invalid());
    }
    let RootModelOutcomeReceiptV1::Failed {
        admission,
        observed_at_ms,
        stream_sha256,
        failure,
    } = root
    else {
        return Err(invalid());
    };
    let kind = match failure {
        RootModelFailureV1::HttpRejection { status }
            if (100..=599).contains(&status) && !(200..=299).contains(&status) =>
        {
            SelfIterationModelFailureKindV1::HttpRejection { status }
        }
        RootModelFailureV1::ProviderFailed { .. } => {
            SelfIterationModelFailureKindV1::ProviderFailed
        }
        RootModelFailureV1::ProviderIncomplete { .. } => {
            SelfIterationModelFailureKindV1::ProviderIncomplete
        }
        RootModelFailureV1::ProviderError => SelfIterationModelFailureKindV1::ProviderError,
        _ => return Err(invalid()),
    };
    let prompt = bound_prompt(request)?;
    let source = crate::native_app_server::native_source_payload_digest(
        &prompt,
        &None,
        scope.agentd_socket,
        scope.native_timeout_ms,
        /*intelligence*/ None,
        crate::native_app_server::NativeDeadlinePolicy::Absolute(request.deadline_ms),
    )
    .map_err(|_| invalid())?;
    let record = &facts.native_record;
    let dispatch = record.dispatch.as_ref().ok_or_else(invalid)?;
    let output = record.observation.as_ref().ok_or_else(invalid)?;
    let binding = &admission.binding;
    let digest_present = |value: Option<&str>| {
        value.is_some_and(|value| {
            value
                .parse::<Digest32>()
                .is_ok_and(|digest| !digest.is_zero())
        })
    };
    if scope.subject.is_empty()
        || scope.model.is_empty()
        || scope.model_provider.is_empty()
        || scope.app_server_executable_digest.is_zero()
        || scope.cgroup.is_empty()
        || !scope.agentd_socket.is_absolute()
        || scope.native_timeout_ms == 0
        || record.request.request_id != request.request_id.as_str()
        || record.request.principal_id != scope.subject
        || record.request.worker_generation == 0
        || record.request.model != scope.model
        || record.request.payload_digest != source
        || record.revision == 0
        || record.state != NativeReservationState::Released
        || record.cancel_requested
        || record.pre_dispatch_stop.is_some()
        || record.pre_effect_abort.is_some()
        || record.dispatch_rejection.is_some()
        || dispatch.codex_source_admission_digest.as_deref() != Some(source.as_str())
        || dispatch.model_provider != scope.model_provider
        || dispatch.protocol_id.as_deref()
            != Some(codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID)
        || dispatch.codex_connection_id.is_none_or(|id| id == 0)
        || dispatch
            .codex_session_id
            .as_ref()
            .is_none_or(String::is_empty)
        || dispatch.codex_deadline_ms.is_none_or(|deadline| {
            deadline == 0 || deadline > request.deadline_ms || deadline <= admission.admitted_at_ms
        })
        || !digest_present(dispatch.codex_payload_digest.as_deref())
        || !digest_present(dispatch.codex_request_digest.as_deref())
        || !digest_present(dispatch.codex_home_digest.as_deref())
        || !digest_present(dispatch.codex_authority_witness_sha256.as_deref())
        || !digest_present(dispatch.codex_revocation_head_sha256.as_deref())
        || dispatch
            .codex_authority_epoch
            .is_none_or(|epoch| epoch == 0)
        || dispatch
            .codex_revocation_revision
            .is_none_or(|revision| revision == 0)
        || dispatch
            .app_server_version
            .as_ref()
            .is_none_or(String::is_empty)
        || output.status != NativeRunStatus::Failed
        || output.boundary_status != NativeBoundaryStatus::Failed
        || !output.terminal_observed
        || output.owner_authority != NativeOwnerAuthority::ObservedReady
        || output.thread_id != dispatch.thread_id
        || record.turn_id.as_deref() != Some(output.turn_id.as_str())
        || output.turn_id.is_empty()
        || output.model != scope.model
        || output.model_provider != scope.model_provider
        || !digest_present(output.codex_terminal_correlation_digest.as_deref())
        || admission.schema != "hepta.root-model-terminal.v1"
        || admission.subject != scope.subject
        || admission.model != scope.model
        || admission.executable_sha256 != scope.app_server_executable_digest.to_string()
        || admission.cgroup != scope.cgroup
        || admission.pid == 0
        || admission.start_ticks == 0
        || admission.native_prompt != prompt
        || binding.request_id != request.request_id.as_str()
        || binding.role != format!("{:?}", request.role)
        || binding.envelope_digest != request.envelope_digest.to_string()
        || binding.candidate_digest != request.candidate_digest.map(|value| value.to_string())
        || binding.deadline_ms != request.deadline_ms
        || binding.maximum_response_bytes != request.maximum_response_bytes
        || admission.admitted_at_ms == 0
        || admission.admitted_at_ms >= request.deadline_ms
        || observed_at_ms < admission.admitted_at_ms
        || observed_at_ms > facts.observed_at_ms
        || admission.completed_at_ms != 0
        || !admission.response_id.is_empty()
        || admission.stream_sha256 != [0; 32]
        || admission.model_output_sha256 != [0; 32]
        || admission.model_output_bytes != 0
        || stream_sha256 == [0; 32]
        || admission.request_sha256 == [0; 32]
        || admission.scope_sha256 == [0; 32]
        || admission.payload_sha256 == [0; 32]
    {
        return Err(invalid());
    }
    match (&record.terminal_owner, &record.terminal_publication) {
        (None, None) => {}
        (Some(owner), Some(publication))
            if &publication.owner == owner
                && publication.phase == NativeTerminalPublicationPhase::Failed
                && publication.terminal_observed
                && publication
                    .acknowledged_revision
                    .is_some_and(|revision| revision > owner.owner_dispatch_revision)
                && digest_present(Some(&publication.publication_digest)) => {}
        _ => return Err(invalid()),
    }
    let result = SelfIterationModelFailureV1 {
        request_id: request.request_id.clone(),
        role: request.role,
        envelope_digest: request.envelope_digest,
        candidate_digest: request.candidate_digest,
        kind,
        native_run_digest: native_failure_record_digest(request, record)?,
        provider_failure_digest: Digest32::of_bytes(&facts.root_outcome_bytes),
        facts_digest: Digest32::of_bytes(&encoded),
        observed_at_ms: facts.observed_at_ms,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.validate(request)?;
    Ok(result)
}
