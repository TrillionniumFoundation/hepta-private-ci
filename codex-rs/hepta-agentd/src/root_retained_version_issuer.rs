//! Attenuate the already held UID-0 issuer connection to one original retained
//! Version request. This creates no policy, signer, lease or replacement socket.
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;

use super::AgentdFinalUseIssuerError;
use super::AgentdUnixFinalUseGrantProvider;

const ORIGINAL_RETAINED_VERSION_DESTINATION: &str = "agentd.cell-generation.next-task-same-model";

enum OriginalVersionIssuerAccessV1 {
    Available,
    ReadbackOnly,
}

pub(crate) struct OriginalRootRetainedVersionIssuerV1 {
    provider: AgentdUnixFinalUseGrantProvider,
    access: OriginalVersionIssuerAccessV1,
}

impl AgentdUnixFinalUseGrantProvider {
    pub(crate) fn into_original_retained_version_issuer(
        self,
    ) -> Result<OriginalRootRetainedVersionIssuerV1, AgentdFinalUseIssuerError> {
        let root = self
            .protected_root
            .as_ref()
            .ok_or(AgentdFinalUseIssuerError::InvalidConfiguration)?;
        if root.original_uid != 0 {
            return Err(AgentdFinalUseIssuerError::PeerDenied);
        }
        self.check_root()?;
        super::super::remaining(root.end)?;
        {
            let slot = self
                .stream
                .try_lock()
                .map_err(|_| AgentdFinalUseIssuerError::Busy)?;
            if slot.is_none() {
                return Err(AgentdFinalUseIssuerError::ChannelClosed);
            }
        }
        Ok(OriginalRootRetainedVersionIssuerV1 {
            provider: self,
            access: OriginalVersionIssuerAccessV1::Available,
        })
    }
}

impl OriginalRootRetainedVersionIssuerV1 {
    /// The sole production caller derives this binding from the actual
    /// Prepared owner after current D/T and Artifact observations. In
    /// particular, a Resident grant or a Model replacement cannot enter here.
    pub(crate) fn request_for_original_retained_version(
        &mut self,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, AgentdFinalUseIssuerError> {
        if binding.destination_id != ORIGINAL_RETAINED_VERSION_DESTINATION
            || binding.subject_id.is_empty()
            || binding.request_sha256 == [0; 32]
            || binding.scope_sha256 == [0; 32]
            || binding.payload_sha256 == [0; 32]
        {
            return Err(AgentdFinalUseIssuerError::BindingMismatch);
        }
        if !matches!(self.access, OriginalVersionIssuerAccessV1::Available) {
            return Err(AgentdFinalUseIssuerError::ChannelClosed);
        }
        self.access = OriginalVersionIssuerAccessV1::ReadbackOnly;
        // The original request checks the held pidfd and the initial absolute
        // end both before and after I/O. Even a complete Denied result cannot
        // restore this one-purpose wrapper or renew its original budget.
        AgentdUnixFinalUseGrantProvider::request_grant(&self.provider, binding)
    }
}
