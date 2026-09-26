use std::path::Path;

use codex_hepta_evidence::HeptaEvidenceStore;

use crate::AgentdError;
use crate::AgentdIdentity;

pub(crate) fn is_production_evidence_profile(
    identity: &AgentdIdentity,
    descriptor_or_frontier: &Path,
) -> bool {
    descriptor_or_frontier.parent() == Some(identity.home_root.as_path())
}

pub(crate) async fn verify_production_evidence_frontier(
    _identity: &AgentdIdentity,
    _store: &HeptaEvidenceStore,
    _issuer_trust_file: &Path,
    _production_config_file: &Path,
    _signer_trust_file: &Path,
) -> Result<(), AgentdError> {
    Err(AgentdError::Invalid(
        "kernel.evidence recovery_required: production evidence admission requires Unix ownership, device and file-identity enforcement"
            .to_string(),
    ))
}
