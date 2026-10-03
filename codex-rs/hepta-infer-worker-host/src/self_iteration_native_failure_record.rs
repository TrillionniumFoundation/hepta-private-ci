//! Actual released failed record, from the sole durable native owner.
use super::*;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

pub(super) fn native_failure_record_digest(
    request: &SelfIterationModelRequestV1,
    record: &NativeRunRecord,
) -> Result<Digest32, SelfIterationModelErrorV1> {
    let invalid = || SelfIterationModelErrorV1::InvalidResponse;
    let dispatch = record.dispatch.as_ref().ok_or_else(invalid)?;
    let output = record.observation.as_ref().ok_or_else(invalid)?;
    if record.request.request_id != request.request_id.as_str()
        || record.revision == 0
        || record.state != NativeReservationState::Released
        || record.turn_id.as_deref() != Some(output.turn_id.as_str())
        || output.turn_id.is_empty()
        || record.cancel_requested
        || record.pre_dispatch_stop.is_some()
        || record.pre_effect_abort.is_some()
        || record.dispatch_rejection.is_some()
        || output.status != NativeRunStatus::Failed
        || output.boundary_status != NativeBoundaryStatus::Failed
        || !output.terminal_observed
        || output.owner_authority != NativeOwnerAuthority::ObservedReady
        || output.thread_id != dispatch.thread_id
        || output.model != record.request.model
        || output.model_provider != dispatch.model_provider
        || output
            .codex_terminal_correlation_digest
            .as_ref()
            .is_none_or(|digest| {
                !digest
                    .parse::<Digest32>()
                    .is_ok_and(|digest| !digest.is_zero())
            })
    {
        return Err(invalid());
    }
    let bytes = serde_json::to_vec(&("hepta.self-iteration.native-failure-terminal.v1", record))
        .map_err(|_| invalid())?;
    Ok(Digest32::of_bytes(&bytes))
}
