//! Bounded exact terminal recovery and durable cancellation observations.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use tokio_util::sync::CancellationToken;

use super::input::bounded_utf8_prefix;

/// Retain a UTF-8 prefix without discarding already verified physical terminal
/// truth when provider text exceeds the existing local output budget.
pub(super) fn retain_recovered_output<'a>(
    output: &mut NativeRunOutput,
    agent_messages: impl IntoIterator<Item = &'a str>,
    maximum_bytes: usize,
) {
    for text in agent_messages {
        let remaining = maximum_bytes.saturating_sub(output.output.len());
        if text.len() > remaining {
            output.output.push_str(bounded_utf8_prefix(text, remaining));
            output.boundary_status = NativeBoundaryStatus::Quarantined;
            output.stop_reason = Some("reconciled output byte limit exceeded".to_string());
            return;
        }
        output.output.push_str(text);
    }
}

/// Sample cancellation on both sides of a recovery await, before propagating
/// its result or error. A terminal historical fastpath never calls this helper.
pub(super) fn record_recovery_cancellation(
    control: &mut DurableInferenceControl,
    request_id: &str,
    cancellation: &CancellationToken,
) -> std::result::Result<NativeRunRecord, Error> {
    if cancellation.is_cancelled() {
        control.cancel_native(request_id)?;
    }
    control
        .native_record(request_id)
        .cloned()
        .ok_or(Error::RequestNotFound)
}

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Persist cancellation before and after the actual recovery future, including
/// error exits, then normalize any newly recovered fact against current intent.
pub(super) async fn reconcile_with_cancellation<Recover, Recovery>(
    control: &mut DurableInferenceControl,
    request_id: &str,
    cancellation: &CancellationToken,
    recover: Recover,
) -> Result<(NativeRunRecord, Option<NativeRunOutput>)>
where
    Recover: FnOnce(NativeRunRecord) -> Recovery,
    Recovery: std::future::Future<Output = Result<Option<NativeRunOutput>>>,
{
    let record = record_recovery_cancellation(control, request_id, cancellation)?;
    let recovery = recover(record).await;
    let record = record_recovery_cancellation(control, request_id, cancellation)?;
    let mut output = recovery?;
    if let Some(output) = output.as_mut() {
        preserve_recovery_evidence(&record, output)?;
    }
    Ok((record, output))
}

pub(super) fn apply_recovery_cancellation(
    output: &mut NativeRunOutput,
    cancellation: &CancellationToken,
) {
    if cancellation.is_cancelled()
        && matches!(
            output.boundary_status,
            NativeBoundaryStatus::Succeeded | NativeBoundaryStatus::Indeterminate
        )
    {
        output.boundary_status = NativeBoundaryStatus::Cancelled;
        output.stop_reason = Some("cancelled during recovery".to_string());
    }
}

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
    if record.cancel_requested
        && matches!(
            output.boundary_status,
            NativeBoundaryStatus::Succeeded | NativeBoundaryStatus::Indeterminate
        )
    {
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
