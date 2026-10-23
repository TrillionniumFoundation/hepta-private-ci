//! Explicit external trust inputs for the original FinalUse authority owner.

use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseIssuerTrustKey;
use codex_hepta_contracts::FinalUseRevocations;

/// Every trust input is supplied by the embedding host. There is no default
/// clock, frontier, issuer key, revocation head, or legacy-store fallback.
/// Concrete clock/frontier protection and head freshness remain deployment
/// obligations; implementing a trait is not an attestation of those properties.
pub struct AgentdFinalUseHostInputs {
    pub state_directory: PathBuf,
    pub signer_id: String,
    pub issuer_keys: Vec<FinalUseIssuerTrustKey>,
    pub revocations: FinalUseRevocations,
    pub clock: Arc<dyn AuthorityClock>,
    pub frontier_store: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
}

impl AgentdFinalUseHostInputs {
    pub(crate) fn open(self) -> Result<FinalUseAuthority, FinalUseError> {
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            &self.state_directory,
            self.signer_id,
            self.issuer_keys,
            self.revocations,
            self.clock,
            self.frontier_store,
        )
    }
}

#[cfg(test)]
#[path = "production_authority_tests.rs"]
mod tests;
