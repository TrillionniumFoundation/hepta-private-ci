//! Attenuate an already held original Root issuer transport to one actual
//! changed-Model Prepared binding. A request is not an authorization: the
//! existing independent issuer policy may deny it, and original publication
//! still verifies the returned FinalUse grant. No same-model right is widened.
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::FileAnchorWitnessStore;
use super::AgentdFinalUseIssuerError;
use super::AgentdUnixFinalUseGrantProvider;
use crate::PreparedOriginalCircuitModelPublicationV1;

const DESTINATION: &str = "agentd.cell-generation.replace-drained";

pub(crate) struct OriginalRootModelVersionIssuerV1 {
    provider: AgentdUnixFinalUseGrantProvider,
    requested: bool,
}
impl AgentdUnixFinalUseGrantProvider {
    pub(crate) fn into_original_model_version_issuer(
        self,
    ) -> Result<OriginalRootModelVersionIssuerV1, AgentdFinalUseIssuerError> {
        let root = self.protected_root.as_ref()
            .ok_or(AgentdFinalUseIssuerError::InvalidConfiguration)?;
        if root.original_uid != 0 { return Err(AgentdFinalUseIssuerError::PeerDenied); }
        self.check_root()?;
        super::super::remaining(root.end)?;
        {
            let slot = self.stream.try_lock().map_err(|_| AgentdFinalUseIssuerError::Busy)?;
            if slot.is_none() { return Err(AgentdFinalUseIssuerError::ChannelClosed); }
        }
        Ok(OriginalRootModelVersionIssuerV1 { provider: self, requested: false })
    }
}
impl OriginalRootModelVersionIssuerV1 {
    /// The only caller holds the actual original Prepared operation. A wire
    /// request, LEARN receipt or unsigned future binding cannot enter here.
    pub(crate) fn request_for_original_model_version(
        &mut self,
        prepared: &PreparedOriginalCircuitModelPublicationV1<'_, FileAnchorWitnessStore, FileAnchorWitnessStore>,
    ) -> Result<SignedFinalUseGrant, AgentdFinalUseIssuerError> {
        let binding = prepared.final_use_binding();
        if binding.destination_id != DESTINATION || binding.subject_id.is_empty()
            || binding.request_sha256 == [0; 32] || binding.scope_sha256 == [0; 32]
            || binding.payload_sha256 == [0; 32]
        {
            return Err(AgentdFinalUseIssuerError::BindingMismatch);
        }
        if self.requested { return Err(AgentdFinalUseIssuerError::ChannelClosed); }
        self.requested = true;
        // Existing pidfd, absolute end, frame bounds, issuer policy and grant
        // validation remain unchanged. Denial does not rearm this wrapper.
        AgentdUnixFinalUseGrantProvider::request_grant(&self.provider, binding)
    }
}
