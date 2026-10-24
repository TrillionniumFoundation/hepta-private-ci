//! Failed unactivated proofs have a distinct physical-process retirement path.
//! This evidence cannot be used as a checkpoint head or namespace authority.

use super::super::activation::RetainedCheckpointActivation;
use super::*;

impl RetiredCheckpointPublisher {
    pub(in super::super) fn from_prior_boot_activation(
        root: CognitiveCheckpointPeerLifetime,
        preparation: RetainedCheckpointActivation,
    ) -> Result<Self, AuthorityTrustError> {
        if root
            != crate::HostAuthorityService::current_root_lifetime_for_admin()
                .map_err(|_| AuthorityTrustError::Unavailable)?
            || preparation.peer().boot_id == root.boot_id
        {
            return Err(AuthorityTrustError::Invalid);
        }
        preparation.verify_durable()?;
        let result = Self {
            lifetime: preparation.peer().clone(),
            evidence: RetirementEvidence::PriorBootActivation { root, preparation },
        };
        result.require_retired()?;
        Ok(result)
    }

    pub(in super::super) fn require_unactivated_successor(
        &self,
        previous: &CognitiveCheckpointReceipt,
        candidate: &crate::HostAuthorityWriterRegistration,
        successor: &CognitiveCheckpointPeerLifetime,
    ) -> Result<(), AuthorityTrustError> {
        match &self.evidence {
            RetirementEvidence::SameBoot { .. } => self.require_same_boot_successor(successor),
            RetirementEvidence::PriorBootActivation { root, preparation } => {
                if successor.boot_id != root.boot_id {
                    return Err(AuthorityTrustError::Invalid);
                }
                preparation.matches_replacement(previous, candidate)?;
                self.require_retired()
            }
            RetirementEvidence::PriorBoot { .. } => Err(AuthorityTrustError::Invalid),
        }
    }
}
