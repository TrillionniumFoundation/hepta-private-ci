//! Output and cancellation over the original authorized process effect.
//! No runtime dependency, authorization issuer or second effect ledger lives here.

use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_types::Digest32;

use super::now_ms;
use super::owner_error;
use crate::EffectObservation;
use crate::EffectOwner;
use crate::Error;
use crate::Phase;
use crate::Result;
use crate::StopObservation;
use crate::ToolCall;
use crate::TurnBinding;
use crate::taskflow_owner::observe_bound_effect_turn;

#[path = "runtime_process_cancel.rs"]
mod cancellation;
#[path = "runtime_process_contract.rs"]
mod contract;
#[path = "runtime_process_driver.rs"]
mod driver;
#[path = "runtime_process_projection.rs"]
mod projection;
pub use contract::*;
use driver::RuntimeProcessDriver;
use projection::stop_from;
use projection::terminal_status;

/// One independently admitted process effect. Output is verified against the
/// original durable receipt on every projection, including after reconnection.
pub struct RuntimeProcessEffectOwner<'a, A> {
    store: &'a AutomationStore,
    authority: &'a FinalUseAuthority,
    driver: RuntimeProcessDriver<A>,
    admitted: PreboundRuntimeProcessEffect,
    fresh_dispatch_disabled: bool,
}

#[derive(Clone, Copy)]
enum Contact {
    Dispatch,
    Observe,
    Cancel,
}

impl<'a, A: RuntimeProcessOwner> RuntimeProcessEffectOwner<'a, A> {
    pub fn new(
        store: &'a AutomationStore,
        authority: &'a FinalUseAuthority,
        owner: A,
        admitted: PreboundRuntimeProcessEffect,
    ) -> Self {
        let intent = ProviderEffectIntent::new(
            admitted.0.provider_key.clone(),
            admitted.0.intent.payload_digest.clone(),
        );
        Self {
            store,
            authority,
            driver: RuntimeProcessDriver { owner, intent },
            admitted,
            fresh_dispatch_disabled: false,
        }
    }

    async fn pending(&self) -> Result<Option<AuthorizedEffectPending>> {
        let effect = &self.admitted.0;
        let pending = self
            .store
            .authorized_taskflow_effect_attempt(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
            )
            .await
            .map_err(|_| owner_error("original runtime attempt lookup failed"))?;
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
            return Err(Error::Contract("original runtime admission changed"));
        }
        Ok(pending)
    }

    async fn retained_receipt(&self) -> Result<Option<TaskFlowStepReceipt>> {
        self.store
            .read_authorized_taskflow_effect_receipt(
                &self.admitted.0.intent,
                &self.admitted.0.command_id,
            )
            .await
            .map_err(|_| owner_error("original runtime receipt binding failed"))
    }

    async fn check_fence(&self, now: u64, contact: Contact) -> Result<()> {
        let effect = &self.admitted.0;
        let run = self
            .store
            .taskflow_run(&effect.intent.run_id)
            .await
            .map_err(|_| owner_error("original runtime effect run unavailable"))?
            .ok_or(Error::Contract("original runtime effect run absent"))?;
        let live_contact = !matches!(contact, Contact::Observe);
        if run.owner_agent_id != effect.fence.owner_agent_id
            || run.owner_id.as_deref() != Some(effect.fence.owner_id.as_str())
            || run.owner_epoch != Some(effect.fence.owner_epoch)
            || run.generation != Some(effect.fence.generation)
            || run.fencing_token.as_deref() != Some(effect.fence.fencing_token.as_str())
            || !matches!(
                run.state,
                TaskFlowRunState::Running | TaskFlowRunState::Indeterminate
            )
            || live_contact
                && run
                    .lease_expires_at_ms
                    .is_none_or(|deadline| deadline <= now)
            || matches!(contact, Contact::Dispatch)
                && (run.state != TaskFlowRunState::Running || run.cancel_requested)
        {
            return Err(Error::Contract(
                "original runtime owner fence is not current",
            ));
        }
        Ok(())
    }

    async fn observe_existing(&self) -> Result<EffectObservation> {
        if let Some(receipt) = self.retained_receipt().await? {
            return self.project(receipt, None).await;
        }
        let now = now_ms()?;
        self.check_fence(now, Contact::Observe).await?;
        let effect = &self.admitted.0;
        if let Some(local) = self
            .store
            .settle_authorized_taskflow_effect_observation(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
                &effect.fence,
            )
            .await
            .map_err(|_| owner_error("original runtime durable settlement failed"))?
        {
            match local {
                AuthorizedEffectRecoveryResult::ProvenAbsent => {
                    return Ok(EffectObservation::Unresolved);
                }
                AuthorizedEffectRecoveryResult::Observed(receipt)
                    if terminal_status(&receipt).is_some() =>
                {
                    return self.project(receipt, None).await;
                }
                AuthorizedEffectRecoveryResult::Observed(_) => {}
            }
        }
        let RuntimeProcessObservation::Terminal(result) = self
            .driver
            .owner
            .observe(&self.driver.intent, &effect.payload)
            .await
        else {
            return Ok(EffectObservation::Unresolved);
        };
        let receipt = result.receipt(&self.driver.intent)?;
        match self
            .store
            .recover_authorized_taskflow_effect(
                &effect.intent.run_id,
                &effect.intent.step_id,
                effect.intent.attempt,
                &effect.fence,
                AuthorizedEffectRecovery::Observed(receipt),
                now,
            )
            .await
            .map_err(|_| owner_error("original runtime recovery failed"))?
        {
            AuthorizedEffectRecoveryResult::ProvenAbsent => Ok(EffectObservation::Unresolved),
            AuthorizedEffectRecoveryResult::Observed(receipt) => {
                self.project(receipt, Some(result)).await
            }
        }
    }
}

impl<A: RuntimeProcessOwner> EffectOwner for RuntimeProcessEffectOwner<'_, A> {
    async fn execute_or_observe(
        &mut self,
        binding: &TurnBinding,
        key: Digest32,
        call: &ToolCall,
    ) -> Result<EffectObservation> {
        self.admitted.0.validate_call(binding, key, call)?;
        if self.pending().await?.is_some() {
            return self.observe_existing().await;
        }
        if self.fresh_dispatch_disabled {
            return Ok(EffectObservation::Unresolved);
        }
        let now = now_ms()?;
        let effect = &self.admitted.0;
        let (current, native_run) =
            observe_bound_effect_turn(self.store, &effect.fence, binding).await?;
        if native_run.cancel_requested
            || matches!(current.phase, Phase::CancelRequested | Phase::Cancelled)
        {
            self.fresh_dispatch_disabled = true;
            return Ok(EffectObservation::Unresolved);
        }
        if runtime_process_effect_run_id(&current)? != effect.intent.run_id
            || native_run.state != TaskFlowRunState::Running
            || native_run
                .lease_expires_at_ms
                .is_none_or(|deadline| deadline <= now)
        {
            return Err(Error::Contract(
                "original native process frame is not current",
            ));
        }
        if now >= binding.deadline_unix_ms {
            return Err(Error::Limit("original runtime effect deadline"));
        }
        self.check_fence(now, Contact::Dispatch).await?;
        let effect = &self.admitted.0;
        match self
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
            .await
        {
            Ok(receipt) => self.project(receipt, None).await,
            Err(AuthorizedEffectError::RecoveryRequired) => {
                if self.pending().await?.is_some() {
                    self.observe_existing().await
                } else {
                    Ok(EffectObservation::Unresolved)
                }
            }
            Err(AuthorizedEffectError::ProvenAbsentNeedsNewAttempt) => {
                Ok(EffectObservation::Unresolved)
            }
            Err(AuthorizedEffectError::FinalUse(_)) => Err(owner_error(
                "original final-use authority rejected runtime effect",
            )),
            Err(_) => Err(owner_error("original authorized runtime dispatch failed")),
        }
    }

    async fn cancel(&mut self, binding: &TurnBinding) -> Result<StopObservation> {
        if *binding != self.admitted.0.binding {
            return Err(Error::Contract("original runtime cancellation binding"));
        }
        let (current, native_run) =
            observe_bound_effect_turn(self.store, &self.admitted.0.fence, binding).await?;
        if !native_run.cancel_requested
            && !matches!(current.phase, Phase::CancelRequested | Phase::Cancelled)
        {
            return Err(Error::Contract(
                "original durable native cancellation absent",
            ));
        }
        self.fresh_dispatch_disabled = true;
        if self.pending().await?.is_none() {
            return self.cancel_before_admission().await;
        }
        if let Some(receipt) = self.retained_receipt().await? {
            return Ok(stop_from(self.project(receipt, None).await?));
        }
        if native_run
            .lease_expires_at_ms
            .is_none_or(|deadline| deadline <= now_ms().unwrap_or(u64::MAX))
        {
            return Err(Error::Contract(
                "original native cancellation owner expired",
            ));
        }
        self.check_fence(now_ms()?, Contact::Cancel).await?;
        // Never promote a cancel reply to a stop acknowledgement. Re-observe
        // the original key and reconcile its terminal evidence independently.
        let _ = self
            .driver
            .owner
            .cancel(&self.driver.intent, &self.admitted.0.payload)
            .await;
        Ok(stop_from(self.observe_existing().await?))
    }
}
