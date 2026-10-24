//! Additional same-owner time restrictions on the original effect path.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;

use crate::AsyncAuthorizedEffectDriver;
use crate::AuthorizedEffectDriver;
use crate::AuthorizedEffectError;
use crate::AuthorizedEffectIntent;
use crate::TaskFlowClockClaim;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRun;
use crate::TaskFlowStepReceipt;
use crate::taskflow_clock::ClockClaimBinding;
use crate::taskflow_clock::owner_time;

impl TaskFlowClockClaim<'_> {
    /// Dispatch only through this live original-store/clock lease binding.
    /// The caller still supplies the original signed grant and exact payload.
    #[allow(
        clippy::too_many_arguments,
        reason = "original signed effect fields stay explicit"
    )]
    pub async fn execute_authorized_effect<D: AuthorizedEffectDriver>(
        &self,
        driver: &mut D,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        self.store
            .execute_authorized_taskflow_effect_with_time(
                self.authority,
                driver,
                intent,
                wire_payload,
                &self.binding.fence,
                signed_grant,
                expected_binding,
                command_id,
                self.effect_time(),
            )
            .await
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "original signed effect fields stay explicit"
    )]
    pub async fn execute_authorized_effect_async<D: AsyncAuthorizedEffectDriver>(
        &self,
        driver: &mut D,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        self.store
            .execute_authorized_taskflow_effect_async_with_time(
                self.authority,
                driver,
                intent,
                wire_payload,
                &self.binding.fence,
                signed_grant,
                expected_binding,
                command_id,
                self.effect_time(),
            )
            .await
    }

    fn effect_time(&self) -> EffectDispatchTime<'_> {
        EffectDispatchTime::Authority {
            authority: self.authority,
            claim: &self.binding,
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) enum EffectDispatchTime<'a> {
    Caller(u64),
    Authority {
        authority: &'a FinalUseAuthority,
        claim: &'a ClockClaimBinding,
    },
}

impl EffectDispatchTime<'_> {
    pub(crate) fn observe(self) -> Result<u64, TaskFlowError> {
        match self {
            Self::Caller(now) => Ok(now),
            Self::Authority { authority, claim } => {
                let now = owner_time(authority)?;
                if now < claim.run.updated_at_ms {
                    return Err(TaskFlowError::Unavailable);
                }
                Ok(now)
            }
        }
    }

    pub(crate) fn observe_after(self, earliest: u64) -> Result<u64, TaskFlowError> {
        let now = self.observe()?;
        if now < earliest {
            return Err(TaskFlowError::Unavailable);
        }
        Ok(now)
    }

    pub(crate) fn validate_request(
        self,
        run_id: &str,
        fence: &TaskFlowFence,
    ) -> Result<(), TaskFlowError> {
        if let Self::Authority { claim, .. } = self
            && (claim.run.run_id != run_id || claim.fence != *fence)
        {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(())
    }

    /// Called after all awaited original-state reads in the IMMEDIATE TX.
    /// No authority mutex is held over those awaits. The clock callback is the
    /// existing host owner; it must not reenter this AutomationStore transaction.
    pub(crate) fn admission_time(
        self,
        run: &TaskFlowRun,
        fence: &TaskFlowFence,
    ) -> Result<u64, TaskFlowError> {
        self.validate_request(&run.run_id, fence)?;
        if let Self::Authority { claim, .. } = self
            && (run.owner_agent_id != claim.run.owner_agent_id
                || run.definition_digest != claim.run.definition_digest
                || run.lease_expires_at_ms != Some(claim.expires_at_unix_ms))
        {
            return Err(TaskFlowError::StaleFence);
        }
        self.observe()
    }

    /// An additional restriction at registered driver entry, after SQL commit.
    /// Check the grant window too: the extra protected-clock read can itself
    /// take time after FinalUse's first guarded entry check. No signature or
    /// grant field is changed. Once a driver enters, later expiry is not a stop.
    pub(crate) fn before_driver(
        self,
        signed: &SignedFinalUseGrant,
        admitted_at_unix_ms: u64,
    ) -> Result<(), TaskFlowError> {
        if let Self::Authority { claim, .. } = self {
            let now = self.observe_after(admitted_at_unix_ms)?;
            if now >= claim.expires_at_unix_ms
                || now < signed.grant.not_before_unix_ms
                || now >= signed.grant.expires_at_unix_ms
            {
                return Err(TaskFlowError::StaleFence);
            }
        }
        Ok(())
    }
}
