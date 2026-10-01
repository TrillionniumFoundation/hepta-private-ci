//! Monotonic native recovery evidence and owner-loss qualification.

use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

/// thread/read may refine physical terminal truth, but it does not erase usage,
/// a local stop, or owner loss already committed before the connection died.
pub(super) fn preserve_recovery_evidence(
    record: &NativeRunRecord,
    output: &mut NativeRunOutput,
) -> std::result::Result<(), String> {
    if let Some(previous) = &record.observation {
        if !output.output.starts_with(&previous.output) {
            return Err("reconciled output contradicts the durable observed prefix".to_string());
        }
        if let Some(previous_tokens) = previous.observed_output_tokens {
            if output
                .observed_output_tokens
                .is_some_and(|tokens| tokens < previous_tokens)
            {
                return Err("reconciled usage regressed from durable observation".to_string());
            }
            output.observed_output_tokens =
                Some(output.observed_output_tokens.unwrap_or(previous_tokens));
        }
        if matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. }) {
            output.owner_authority = previous.owner_authority.clone();
        }
        if matches!(
            previous.boundary_status,
            NativeBoundaryStatus::Cancelled
                | NativeBoundaryStatus::TimedOut
                | NativeBoundaryStatus::Quarantined
        ) {
            output.boundary_status = previous.boundary_status;
            output.stop_reason = previous.stop_reason.clone().or(output.stop_reason.take());
        }
    }
    if record.cancel_requested && output.boundary_status == NativeBoundaryStatus::Succeeded {
        output.boundary_status = NativeBoundaryStatus::Cancelled;
        output.stop_reason =
            Some("cancellation was durably requested before reconciliation".to_string());
    }
    if output.boundary_status == NativeBoundaryStatus::Succeeded
        && record.dispatch.as_ref().is_some_and(|dispatch| {
            dispatch.codex_request_digest.is_some()
                && (dispatch.codex_authority_epoch.is_none()
                    || dispatch.codex_revocation_revision.is_none()
                    || dispatch.codex_revocation_head_sha256.is_none())
        })
    {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        output.stop_reason = Some(
            "historical runtime.codex dispatch lacks claim-time authority frontier; terminal truth retained but success qualification denied"
                .to_string(),
        );
    }
    downgrade_for_owner_loss(output);
    Ok(())
}

pub(super) fn downgrade_for_owner_loss(output: &mut NativeRunOutput) {
    if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
    }
}

#[cfg(test)]
#[path = "native_recovery_tests.rs"]
mod tests;
