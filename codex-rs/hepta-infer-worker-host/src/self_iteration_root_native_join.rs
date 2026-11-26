//! Join complete facts from the original native owner and Root model relay.
//! This pure check issues no grant. The Root service must authenticate the
//! current native reader and read the immutable relay fact independently.
use super::*;
use codex_hepta_infer_core::durable_control::native::NativeTerminalPublicationPhase;
use codex_hepta_supervisor::RootModelTerminalReceiptV1;
use std::path::Path;

/// Values independently loaded from the original installed model composition.
/// Historical completed relay processes need not still be alive after their
/// ephemeral session has been disposed; authenticate the current reader anew.
pub struct RootNativeAssessmentScopeV1<'a> {
    pub subject: &'a str,
    pub model: &'a str,
    pub model_provider: &'a str,
    pub app_server_executable_digest: Digest32,
    pub cgroup: &'a str,
    pub agentd_socket: &'a Path,
    pub native_timeout_ms: u128,
}

pub fn validate_root_native_assessment_facts_v1(
    request: &SelfIterationModelRequestV1,
    record: &NativeRunRecord,
    witness: &RootModelTerminalReceiptV1,
    scope: &RootNativeAssessmentScopeV1<'_>,
    observed_at_ms: u64,
) -> Result<SelfIterationModelAssessmentV1, SelfIterationModelErrorV1> {
    request.validate(observed_at_ms)?;
    let invalid = || SelfIterationModelErrorV1::InvalidResponse;
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
    let dispatch = record.dispatch.as_ref().ok_or_else(invalid)?;
    let output = record.observation.as_ref().ok_or_else(invalid)?;
    let binding = &witness.binding;
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
        || record.request.principal_id != scope.subject
        || record.request.worker_generation == 0
        || record.request.model != scope.model
        || record.request.payload_digest != source
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
            deadline == 0 || deadline > request.deadline_ms || deadline <= witness.completed_at_ms
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
        || output.thread_id != dispatch.thread_id
        || output.model != scope.model
        || output.model_provider != scope.model_provider
        || !digest_present(output.codex_terminal_correlation_digest.as_deref())
        || witness.schema != "hepta.root-model-terminal.v1"
        || witness.subject != scope.subject
        || witness.model != scope.model
        || witness.executable_sha256 != scope.app_server_executable_digest.to_string()
        || witness.cgroup != scope.cgroup
        || witness.pid == 0
        || witness.start_ticks == 0
        || witness.native_prompt != prompt
        || binding.request_id != request.request_id.as_str()
        || binding.role != format!("{:?}", request.role)
        || binding.envelope_digest != request.envelope_digest.to_string()
        || binding.candidate_digest != request.candidate_digest.map(|value| value.to_string())
        || binding.deadline_ms != request.deadline_ms
        || binding.maximum_response_bytes != request.maximum_response_bytes
        || witness.admitted_at_ms == 0
        || witness.completed_at_ms < witness.admitted_at_ms
        || witness.completed_at_ms >= request.deadline_ms
        || witness.completed_at_ms > observed_at_ms
        || witness.response_id.is_empty()
        || witness.stream_sha256 == [0; 32]
        || witness.request_sha256 == [0; 32]
        || witness.scope_sha256 == [0; 32]
        || witness.payload_sha256 == [0; 32]
        || witness.model_output_sha256 != *Digest32::of_bytes(output.output.as_bytes()).as_array()
        || witness.model_output_bytes != output.output.len()
    {
        return Err(invalid());
    }
    match (&record.terminal_owner, &record.terminal_publication) {
        // Advice runs have no Intelligence owner or terminal outbox. Definite
        // absence is not an ACK, and must not be turned into one.
        (None, None) => {}
        (Some(owner), Some(publication))
            if &publication.owner == owner
                && publication.phase == NativeTerminalPublicationPhase::Succeeded
                && publication.terminal_observed
                && publication
                    .acknowledged_revision
                    .is_some_and(|revision| revision > owner.owner_dispatch_revision)
                && digest_present(Some(&publication.publication_digest)) => {}
        _ => return Err(invalid()),
    }
    // Reuse the native adapter's complete released-record/output digest and
    // DENY_ALL assessment; no caller supplies a native digest or success flag.
    assessment_from_record(request, record, output.clone())
}

#[cfg(test)]
#[path = "self_iteration_root_native_join_tests.rs"]
mod tests;
