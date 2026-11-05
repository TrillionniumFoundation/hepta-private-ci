//! Explicit signed confirmation of an already proposed completion publication.
//! These observations never authorize executing the underlying operation again.
use super::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CompletionPublicationObservationV1 {
    pub schema_version: u32,
    pub predecessor: UnknownRecoveryPredecessorV1,
    pub pending_publication_sha256: Sha256Digest,
    pub release_state_sha256: Sha256Digest,
    pub release_state_generation: u64,
    pub admission_frontier_sha256: Sha256Digest,
}

impl CompletionPublicationObservationV1 {
    pub(super) fn valid_for(&self, agent: &AgentId) -> bool {
        self.schema_version == 1
            && self.predecessor.valid_for(agent)
            && self.release_state_generation > 0
            && [
                &self.pending_publication_sha256,
                &self.release_state_sha256,
                &self.admission_frontier_sha256,
            ]
            .into_iter()
            .all(|digest| Sha256Digest::parse(digest.as_str()).is_ok())
    }
}

/// A fresh ceremony may retry only the already retained replacement CAS. It
/// binds both attempts, including an explicitly absent replacement attempt,
/// without changing either proposal or the prior confirmation material.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetainedPublicationObservationV1 {
    pub schema_version: u32,
    pub predecessor: UnknownRecoveryPredecessorV1,
    pub original_pending_sha256: Sha256Digest,
    pub replacement_pending_sha256: Sha256Digest,
    pub retained_state_sha256: Sha256Digest,
    pub replacement_anchor_sha256: Sha256Digest,
    pub release_state_sha256: Sha256Digest,
    pub release_state_generation: u64,
    pub admission_frontier_sha256: Sha256Digest,
}

impl RetainedPublicationObservationV1 {
    pub(super) fn valid_for(&self, agent: &AgentId) -> bool {
        self.schema_version == 1
            && self.predecessor.valid_for(agent)
            && self.release_state_generation > 0
            && [
                &self.original_pending_sha256,
                &self.replacement_pending_sha256,
                &self.retained_state_sha256,
                &self.replacement_anchor_sha256,
                &self.release_state_sha256,
                &self.admission_frontier_sha256,
            ]
            .into_iter()
            .all(|digest| Sha256Digest::parse(digest.as_str()).is_ok())
    }
}
