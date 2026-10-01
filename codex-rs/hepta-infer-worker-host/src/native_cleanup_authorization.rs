//! Promote an existing cleanup obligation only from the original control cut.
//! Released provider execution does not imply Intelligence publication ACK.
use super::AppServerModelDriver;
use super::NativeWorkerConfig;
use super::Result;
use crate::native_cleanup_store::CleanupClaim;
use crate::native_cleanup_store::CleanupState;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

pub(crate) fn cleanup_operation_id(request_id: &str) -> String {
    format!("native.request.v1:{request_id}")
}

pub(crate) fn cleanup_claim_matches_control(
    control: &DurableInferenceControl,
    config: &NativeWorkerConfig,
    claim: &CleanupClaim,
) -> Result<bool> {
    let Some(request_id) = claim.operation_id.strip_prefix("native.request.v1:") else {
        // Legacy opaque SHA-only identities cannot prove their original record.
        return Ok(false);
    };
    let Some(record) = control.native_record_resolved(request_id)? else {
        return Ok(false);
    };
    if record.request.principal_id != config.agent_id.to_string()
        || record.request.worker_generation != config.generation
        || record.request.model != config.model
    {
        return Ok(false);
    }
    if claim.resume_state == CleanupState::Prepared
        && record.dispatch.is_none()
        && record.observation.is_none()
        && record.terminal_owner.is_none()
        && record.terminal_publication.is_none()
        && (record.state == NativeReservationState::Reserved
            || (record.state == NativeReservationState::Released
                && record.pre_dispatch_stop.is_some()))
    {
        // The original control has not admitted any dispatch. This retains the
        // existing known-unsent cleanup path; no timeout infers this fact.
        return Ok(true);
    }
    Ok(terminal_cleanup_eligible(&record)
        && record.dispatch.as_ref().is_some_and(|dispatch| {
            dispatch.thread_id == claim.thread_id
                && dispatch.codex_session_id.as_deref() == Some(claim.session_id.as_str())
        }))
}

pub(crate) fn terminal_cleanup_eligible(record: &NativeRunRecord) -> bool {
    if record.state != NativeReservationState::Released {
        return false;
    }
    let observed = record
        .observation
        .as_ref()
        .is_some_and(|v| v.terminal_observed && v.codex_terminal_correlation_digest.is_some());
    match (&record.terminal_owner, &record.terminal_publication) {
        // The native reference path has no Intelligence owner. It must not
        // acquire fictitious Intelligence authority from an absent outbox.
        (None, None) => {
            observed
                || record.pre_dispatch_stop.is_some()
                || record
                    .dispatch_rejection
                    .as_ref()
                    .is_some_and(|r| r.retry_safe_before_admission)
        }
        (Some(owner), Some(publication)) => {
            observed && publication.owner == *owner && !publication.pending()
        }
        // This separate protocol commits Released only after Agentd has ACKed
        // the original unsent-abort proof. It has no provider-terminal outbox.
        (Some(owner), None) => record.pre_effect_abort.as_ref().is_some_and(|abort| {
            abort.owner_run_id == owner.run_id
                && abort.owner_dispatch_revision == owner.owner_dispatch_revision
                && record.pre_dispatch_stop.as_ref() == Some(&abort.reason)
        }),
        (None, Some(_)) => false,
    }
}

impl AppServerModelDriver {
    pub(super) async fn mark_cleanup_after_ack(
        &self,
        control: &DurableInferenceControl,
        request_id: &str,
    ) -> Result<()> {
        let Some(record) = control.native_record_resolved(request_id)? else {
            return Ok(());
        };
        if !terminal_cleanup_eligible(&record) {
            return Ok(());
        }
        if record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
        {
            return Err("cleanup no longer matches its original Agent/model owner".into());
        }
        let Some(dispatch) = &record.dispatch else {
            return Err("terminal cleanup omitted its original dispatch".into());
        };
        let Some(session) = &dispatch.codex_session_id else {
            // Historical dispatches without this binding cannot authorize the
            // new exact-session disposal protocol.
            return Ok(());
        };
        let operation = cleanup_operation_id(request_id);
        let store = self.cleanup_owner.get().await?;
        let Some(obligation) = store.obligation(&operation).await? else {
            return Ok(());
        };
        if obligation.thread_id != dispatch.thread_id || obligation.session_id != *session {
            return Err("cleanup obligation differs from the complete original dispatch".into());
        }
        if obligation.state == crate::native_cleanup_store::CleanupState::EffectPossible {
            store.mark_terminal_durable(&obligation).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_cleanup_authorization_tests.rs"]
mod tests;
