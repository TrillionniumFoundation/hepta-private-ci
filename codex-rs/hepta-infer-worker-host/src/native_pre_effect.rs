//! Linear pre-effect ownership and the existing Agentd owner's negative outbox.
//! Owner Enter is durable before its ACK. After requesting it, even a local
//! denial is conservatively reconcile-only; no client can revoke a issued permit
//! merely by claiming that it did not send.

use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::CodexEffectBinding;
use codex_hepta_contracts::EnteredUseToken;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeOwnerBinding;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use tokio_util::sync::CancellationToken;

use super::Result;
use super::deadline::ExecutionDeadline;
use super::unix_time_ms;

pub(super) struct PreparedDispatch<'a> {
    proof: NativePreEffectAbortToken,
    owner: &'a AgentdClient,
    request_id: &'a str,
}

impl<'a> PreparedDispatch<'a> {
    pub(super) fn new(
        proof: NativePreEffectAbortToken,
        owner: &'a AgentdClient,
        request_id: &'a str,
    ) -> Self {
        Self {
            proof,
            owner,
            request_id,
        }
    }

    pub(super) async fn abort(
        self,
        control: &mut DurableInferenceControl,
        reason: String,
    ) -> Result<NativeRunRecord> {
        let record = control.abort_native_before_effect(self.proof, bounded_reason(&reason))?;
        if record.owner_abort.is_some() {
            reconcile_abort(control, self.request_id, self.owner).await
        } else {
            Ok(record)
        }
    }

    pub(super) async fn enter(
        self,
        control: &mut DurableInferenceControl,
        token: VerifiedUseToken,
        binding: &FinalUseBinding,
        deadline: &ExecutionDeadline,
        cancellation: &CancellationToken,
    ) -> Result<(EnteredUseToken, Option<u64>)> {
        let owner_binding = control
            .native_record(self.request_id)
            .and_then(|record| record.dispatch.as_ref())
            .and_then(|dispatch| dispatch.codex_owner_binding.clone());
        if let Some(owner_binding) = owner_binding {
            // From the first owner Enter await onward, no negative abort may
            // release this request. An owner ACK may be lost after persistence.
            drop(self.proof);
            let receipt = self
                .owner
                .run_enter_effect(wire_binding(&owner_binding))
                .await?;
            if receipt.idempotent {
                return Err("owner Enter already exists; reconcile, never send twice".into());
            }
            // Do not widen the signed token's validity by putting a remote RPC
            // after enter(). All awaited owner I/O precedes this last local check.
            deadline.remaining(unix_time_ms()?)?;
            if cancellation.is_cancelled() {
                return Err("cancelled after owner Enter; reconcile-only".into());
            }
            let entered = token.enter(binding)?;
            if !entered.matches(binding) {
                return Err("final-use binding mismatch".into());
            }
            Ok((entered, Some(receipt.owner_revision)))
        } else {
            match token.enter(binding) {
                Ok(entered) if entered.matches(binding) => {
                    drop(self.proof);
                    Ok((entered, None))
                }
                Ok(_) => {
                    self.abort(
                        control,
                        "final-use binding mismatch before send".to_string(),
                    )
                    .await?;
                    Err("final-use binding mismatch before send".into())
                }
                Err(error) => {
                    let reason = format!("final-use entry denied before send: {error}");
                    self.abort(control, reason.clone()).await?;
                    Err(reason.into())
                }
            }
        }
    }
}

pub(super) async fn reconcile_abort(
    control: &mut DurableInferenceControl,
    request_id: &str,
    owner: &AgentdClient,
) -> Result<NativeRunRecord> {
    let notice = control
        .native_record(request_id)
        .and_then(|record| record.owner_abort.clone())
        .ok_or("missing durable owner-abort outbox")?;
    let receipt = owner
        .run_abort_before_effect(wire_binding(&notice.binding), notice.reason.clone())
        .await?;
    Ok(control.acknowledge_native_owner_abort(
        request_id,
        notice.binding,
        notice.reason,
        receipt.owner_revision,
    )?)
}

pub(super) fn wire_binding(value: &NativeOwnerBinding) -> CodexEffectBinding {
    CodexEffectBinding {
        run_id: value.run_id.clone(),
        generation: value.generation,
        expected_revision: value.expected_revision,
        request_digest: value.request_digest.clone(),
        context_digest: value.context_digest.clone(),
        compilation_receipt_digest: value.compilation_receipt_digest.clone(),
    }
}

pub(super) fn bounded_reason(reason: &str) -> String {
    let mut result = String::new();
    for ch in reason.chars().filter(|ch| *ch != '\0') {
        if result.len() + ch.len_utf8() > 512 {
            break;
        }
        result.push(ch);
    }
    if result.trim().is_empty() {
        "pre-effect stop".to_string()
    } else {
        result
    }
}
