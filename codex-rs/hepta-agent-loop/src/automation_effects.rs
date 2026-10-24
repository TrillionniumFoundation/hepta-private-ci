//! Optional status tool over the existing authorized TaskFlow effect owner.
//!
//! No store, run, lease, grant, provider configuration or output artifact is
//! created here. The trusted caller supplies an independently admitted effect
//! run in the same store. Its run ID binds the exact native frame; this is an
//! integrity check, not independent proof of parent-child authority. Original
//! signed intent verification and provider-contract trust remain mandatory.

use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_types::Digest32;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::EffectObservation;
use crate::EffectOwner;
use crate::Error;
use crate::Result;
use crate::StopObservation;
use crate::ToolCall;
use crate::TurnBinding;

#[path = "automation_effects_binding.rs"]
mod binding;
pub use binding::AUTOMATION_STATUS_TOOL_NAME;
pub use binding::PreboundAutomationStatusEffect;
pub use binding::automation_status_effect_run_id;

/// A single admitted status tool. A model cannot select another host, payload,
/// destination, operation, attempt or grant through this adapter.
pub struct AutomationStatusEffectOwner<'a, A> {
    store: &'a AutomationStore,
    authority: &'a FinalUseAuthority,
    driver: ProviderEffectTaskFlowDriver<A>,
    admitted: PreboundAutomationStatusEffect,
    fresh_dispatch_disabled: bool,
}

impl<'a, A: ProviderEffectAdapter> AutomationStatusEffectOwner<'a, A> {
    pub fn new(
        store: &'a AutomationStore,
        authority: &'a FinalUseAuthority,
        driver: ProviderEffectTaskFlowDriver<A>,
        admitted: PreboundAutomationStatusEffect,
    ) -> Self {
        Self {
            store,
            authority,
            driver,
            admitted,
            fresh_dispatch_disabled: false,
        }
    }

    async fn pending(&self) -> Result<Option<AuthorizedEffectPending>> {
        let effect = &self.admitted;
        let pending = self
            .store
            .authorized_taskflow_effect_attempt(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
            )
            .await
            .map_err(|_| owner_error("original effect attempt lookup failed"))?;
        if let Some(pending) = &pending
            && (pending.run_id != effect.intent.run_id
                || pending.step_id != effect.intent.step_id
                || pending.attempt != effect.intent.attempt
                || pending.intent_digest != effect.intent_digest
                || pending.payload_digest != effect.intent.payload_digest
                || pending.destination_id != effect.intent.destination_id
                || pending.authority_epoch != effect.grant.grant.authority_epoch
                || pending.grant_id != effect.grant.grant.grant_id)
        {
            return Err(Error::Contract("original durable effect admission changed"));
        }
        Ok(pending)
    }

    async fn terminal_receipt(&self) -> Result<Option<EffectObservation>> {
        // This original read validates the full intent, payload, final-use
        // binding and command even when the attempt has no terminal receipt.
        self.store
            .read_authorized_taskflow_effect_receipt(
                &self.admitted.intent,
                &self.admitted.command_id,
            )
            .await
            .map_err(|_| owner_error("original effect receipt binding failed"))?
            .map(|receipt| self.project(receipt))
            .transpose()
    }

    async fn check_owner_fence(&self, now: u64, fresh_contact: bool) -> Result<()> {
        let effect = &self.admitted;
        let run = self
            .store
            .taskflow_run(&effect.intent.run_id)
            .await
            .map_err(|_| owner_error("original effect run unavailable"))?
            .ok_or(Error::Contract("pre-admitted effect run absent"))?;
        if run.owner_agent_id != effect.fence.owner_agent_id
            || run.owner_id.as_deref() != Some(effect.fence.owner_id.as_str())
            || run.owner_epoch != Some(effect.fence.owner_epoch)
            || run.generation != Some(effect.fence.generation)
            || run.fencing_token.as_deref() != Some(effect.fence.fencing_token.as_str())
            || !matches!(
                run.state,
                TaskFlowRunState::Running | TaskFlowRunState::Indeterminate
            )
            || fresh_contact
                && (run.state != TaskFlowRunState::Running
                    || run.cancel_requested
                    || run
                        .lease_expires_at_ms
                        .is_none_or(|deadline| deadline <= now))
        {
            return Err(Error::Contract(
                "original effect owner fence is not current",
            ));
        }
        Ok(())
    }

    async fn observe_existing(
        &mut self,
        pending: AuthorizedEffectPending,
    ) -> Result<EffectObservation> {
        if let Some(observed) = self.terminal_receipt().await? {
            return Ok(observed);
        }
        let now = now_ms()?;
        // Original recovery permits a late receipt under the exact historical
        // fence. It cannot renew the lease or permit another physical dispatch.
        self.check_owner_fence(now, false).await?;
        let effect = &self.admitted;
        if let Some(local) = self
            .store
            .settle_authorized_taskflow_effect_observation(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
                &effect.fence,
            )
            .await
            .map_err(|_| owner_error("original durable effect settlement failed"))?
        {
            match local {
                AuthorizedEffectRecoveryResult::ProvenAbsent => return Err(absent_error()),
                AuthorizedEffectRecoveryResult::Observed(receipt) => {
                    let projected = self.project(receipt)?;
                    if !matches!(projected, EffectObservation::Unresolved) {
                        return Ok(projected);
                    }
                }
            }
        }
        let recovery = match self.driver.lookup(&pending).await {
            AuthorizedProviderEffectLookup::Unresolved => return Ok(EffectObservation::Unresolved),
            AuthorizedProviderEffectLookup::ProvenAbsent { proof_digest } => {
                AuthorizedEffectRecovery::ProvenAbsent { proof_digest }
            }
            AuthorizedProviderEffectLookup::Observed(receipt) => {
                AuthorizedEffectRecovery::Observed(receipt)
            }
        };
        // Recovery updates only the original immutable attempt. In particular,
        // proven absence never causes a fresh attempt or grant to be allocated.
        match self
            .store
            .recover_authorized_taskflow_effect(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
                &effect.fence,
                recovery,
                now,
            )
            .await
            .map_err(|_| owner_error("original provider recovery failed"))?
        {
            AuthorizedEffectRecoveryResult::ProvenAbsent => Err(absent_error()),
            AuthorizedEffectRecoveryResult::Observed(receipt) => self.project(receipt),
        }
    }

    fn project(&self, receipt: TaskFlowStepReceipt) -> Result<EffectObservation> {
        let effect = &self.admitted;
        if receipt.run_id != effect.intent.run_id
            || receipt.step_id != effect.intent.step_id
            || receipt.attempt != effect.intent.attempt
            || receipt.fence != effect.fence
            || receipt.intent_digest != effect.intent_digest
            || receipt.payload_digest != effect.intent.payload_digest
        {
            return Err(Error::Contract("original effect receipt identity changed"));
        }
        let status = match (receipt.final_outcome, receipt.observation) {
            (Some(TaskFlowReconcileOutcome::Succeeded), _) => "succeeded",
            (Some(TaskFlowReconcileOutcome::Failed), _) => "failed",
            (None, Some(TaskFlowStepObservation::Succeeded)) => "succeeded",
            (None, Some(TaskFlowStepObservation::Failed)) => "failed",
            _ => return Ok(EffectObservation::Unresolved),
        };
        let receipt_digest = receipt
            .receipt_digest
            .ok_or(Error::Contract("original terminal effect receipt absent"))?;
        // The original store retains the complete receipt. The model receives
        // only the defined status projection, never fencing tokens or grants.
        let status = serde_json::json!({
            "schema":"hepta-native-automation-status:v1", "status":status,
            "native_run_id":effect.binding.run_id.as_str(),
            "native_turn_id":effect.binding.turn_id.as_str(),
            "native_generation":effect.binding.generation.get(),
            "native_operation_key":effect.operation_key.to_string(),
            "native_mapping_digest":effect.mapping_digest.to_string(),
            "selected_call_index":effect.selected_index,
            "effect_run_id":receipt.run_id, "step_id":receipt.step_id,
            "attempt":receipt.attempt, "provider_occurrence_key":effect.provider_key.as_str(),
            "intent_digest":receipt.intent_digest.as_str(),
            "payload_digest":receipt.payload_digest.as_str(),
            "receipt_digest":receipt_digest.as_str(), "receipt_event_seq":receipt.event_seq,
            "result_scope":"status_only_no_output_artifact",
        });
        Ok(EffectObservation::Completed(
            serde_json::to_string(&status)
                .map_err(|_| Error::Contract("status receipt serialization"))?,
        ))
    }
}

impl<A: ProviderEffectAdapter> EffectOwner for AutomationStatusEffectOwner<'_, A> {
    async fn execute_or_observe(
        &mut self,
        binding: &TurnBinding,
        operation_key: Digest32,
        call: &ToolCall,
    ) -> Result<EffectObservation> {
        self.admitted.validate_call(binding, operation_key, call)?;
        // Read immutable original evidence before considering any new contact.
        if let Some(pending) = self.pending().await? {
            return self.observe_existing(pending).await;
        }
        if self.fresh_dispatch_disabled {
            return Ok(EffectObservation::Unresolved);
        }
        let now = now_ms()?;
        if now >= binding.deadline_unix_ms {
            return Err(Error::Limit("original native effect deadline"));
        }
        self.check_owner_fence(now, true).await?;
        if self.driver.adapter().capability()
            != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        {
            return Err(Error::Contract(
                "original provider status capability unavailable",
            ));
        }
        let effect = &self.admitted;
        let result = self
            .store
            .execute_authorized_taskflow_effect_async(
                self.authority,
                &mut self.driver,
                &effect.intent,
                &effect.payload,
                &effect.fence,
                &effect.grant,
                &effect.final_use_binding,
                &effect.command_id,
                now,
            )
            .await;
        match result {
            Ok(receipt) => self.project(receipt),
            Err(AuthorizedEffectError::RecoveryRequired) => match self.pending().await? {
                Some(pending) => self.observe_existing(pending).await,
                None => Ok(EffectObservation::Unresolved),
            },
            Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt) => Err(absent_error()),
            Err(AuthorizedEffectError::FinalUse(_)) => {
                Err(owner_error("original final-use authority rejected effect"))
            }
            Err(_) => Err(owner_error("original authorized effect dispatch failed")),
        }
    }

    async fn cancel(&mut self, binding: &TurnBinding) -> Result<StopObservation> {
        if *binding != self.admitted.binding {
            return Err(Error::Contract("original cancellation binding"));
        }
        self.fresh_dispatch_disabled = true;
        // No cancellation API exists on ProviderEffectTaskFlowDriver. A dropped
        // local future or status/submission receipt is not a remote stop ACK.
        // The native TurnOwner must keep its durable CancelRequested cursor.
        Ok(StopObservation::Unresolved)
    }
}

fn owner_error(reason: &'static str) -> Error {
    Error::Owner(reason.into())
}
fn absent_error() -> Error {
    owner_error("original provider proved absence; no new attempt admitted")
}
fn now_ms() -> Result<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Contract("effect owner clock"))?
        .as_millis()
        .try_into()
        .map_err(|_| Error::Contract("effect owner clock overflow"))
}
