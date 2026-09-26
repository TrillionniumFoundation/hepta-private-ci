//! Owner-controlled trust registry for kernel.evidence production ingress.

use std::path::Path;

use codex_hepta_authbus::RoleIssuerRegistrySnapshot;
use codex_hepta_authbus::VerifiedIssuerHandle;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceIssuerTrustBindingV1;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Clone, Debug)]
pub(crate) struct EvidenceTrust {
    snapshot: RoleIssuerRegistrySnapshot,
}

impl EvidenceTrust {
    pub(crate) fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let snapshot = RoleIssuerRegistrySnapshot::load(
            path,
            identity.home_root.as_path(),
            identity.agent_id.as_str(),
        )
        .map_err(|error| invalid(&error.to_string()))?;
        Ok(Self { snapshot })
    }

    pub(crate) fn verification_bindings(
        &self,
    ) -> Result<Vec<EvidenceIssuerTrustBindingV1>, AgentdError> {
        self.snapshot
            .active_bindings()
            .map(|(issuer, role)| {
                let role = EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error))?;
                Ok(EvidenceIssuerTrustBindingV1::from_registration(
                    issuer, role,
                ))
            })
            .collect()
    }

    pub(crate) fn issuer_for(
        &self,
        issuer_id: &str,
        key_epoch: u64,
        role: EvidenceIssuerRoleV1,
    ) -> Result<VerifiedIssuerHandle, AgentdError> {
        self.snapshot
            .issuer_for(issuer_id, key_epoch, role.as_str())
            .map_err(|error| invalid(&error.to_string()))
    }
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
