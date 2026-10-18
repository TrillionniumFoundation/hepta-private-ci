//! Budget the original synchronous dispatch without changing its durable owner.
//! The RPC timeout remains cooperative for filesystem/OS stalls. In particular,
//! a queued request cannot start the bounded provider call near that timeout.
use super::*;

#[derive(Clone, Copy)]
pub(super) enum ProviderDispatchBudget {
    ConfiguredProvider,
    ControlDeadline(Instant),
}

impl ProviderDispatchBudget {
    pub(super) fn require_remaining(
        self,
        adapter: &AgentdProviderEffectAdapter,
    ) -> Result<(), AuthorizedEffectDriverError> {
        let Self::ControlDeadline(deadline) = self else { return Ok(()); };
        let timeout = match adapter {
            AgentdProviderEffectAdapter::Http(adapter) => adapter.config().timeout,
            AgentdProviderEffectAdapter::Pon(adapter) => adapter.timeout,
        };
        // The native process owner also has a 250 ms kill/reap grace. Leave a
        // full second for that original cleanup and thread handoff. This is an
        // admission bound, not a promise that the OS can be forcibly preempted.
        if deadline.saturating_duration_since(Instant::now()) < timeout + Duration::from_secs(1) {
            return Err(AuthorizedEffectDriverError::BeforeProviderContact);
        }
        Ok(())
    }
}

pub(super) struct AgentdEffectExecution<'a> {
    pub intent: &'a AuthorizedEffectIntent,
    pub wire_payload: &'a [u8],
    pub signed_grant: &'a SignedFinalUseGrant,
    pub command_id: &'a str,
    pub now_ms: u64,
    pub dispatch_budget: ProviderDispatchBudget,
}
