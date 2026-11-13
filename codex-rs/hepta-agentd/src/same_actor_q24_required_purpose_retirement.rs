//! Same original required-purpose socket retirement, with its own function scope.

use super::*;

impl OriginalRequiredPurposeRetirement {
    /// Close this exact underlying socket while keeping all original aliases
    /// and failure guards registered. This is a one-way expected-purpose EOF,
    /// never common Gate closure, a new request, or a completion claim.
    pub(crate) fn shutdown_original_after_root_intent(
        &self,
        intent: &crate::same_actor_q24_deployment::OriginalRootRetirementIntent,
    ) -> Result<(), crate::AgentdError> {
        let checked = (|| {
            intent.require_original_gate(&self.gate)?;
            if self
                .retired
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
            {
                return Err(refused("original purpose retirement was already consumed").into());
            }
            {
                let mut state = self
                    .gate
                    .state
                    .lock()
                    .map_err(|_| refused("original purpose Gate is poisoned"))?;
                self.gate.check_locked(&mut state)?;
                let Some(OriginalPhaseEndpoint::Stream(stream)) = state.streams.get(&self.id)
                else {
                    return Err(
                        refused("original purpose stream registration is unavailable").into(),
                    );
                };
                // The registered alias is a clone of the actual owner's
                // socket. shutdown affects that same socket and every clone;
                // merely dropping one FD would leave the peer alive.
                stream.shutdown(Shutdown::Both)?;
                self.gate.check_locked(&mut state)?;
            }
            intent.require_original_gate(&self.gate)?;
            Ok::<(), crate::AgentdError>(())
        })();
        if checked.is_err() {
            self.gate.close();
        }
        checked
    }
}
