use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::CognitiveRecoveryAnchor;

/// Independently retained migration evidence. This is not a signature, a new
/// authority grant, or permission to reconstruct a witness from a suspect DB.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveSchemaUpgradeTransitionV1 {
    pub(super) profile: String,
    pub(super) old_anchor: CognitiveRecoveryAnchor,
    pub(super) new_anchor: CognitiveRecoveryAnchor,
    pub(super) source_version: i64,
    pub(super) target_version: i64,
    pub(super) migration_plan_digest: Sha256Digest,
    pub(super) authority_fence_digest: Sha256Digest,
    pub(super) predecessor_database_filename: String,
    pub(super) prepared_database_filename: String,
}

impl CognitiveSchemaUpgradeTransitionV1 {
    pub fn old_anchor(&self) -> &CognitiveRecoveryAnchor {
        &self.old_anchor
    }

    pub fn new_anchor(&self) -> &CognitiveRecoveryAnchor {
        &self.new_anchor
    }

    pub fn migration_plan_digest(&self) -> &Sha256Digest {
        &self.migration_plan_digest
    }
}

/// Current disposition read from the trusted host, never discovered by scanning
/// local SQLite generations. A transition retains both cuts across a crash
/// between durable host acknowledgement and atomic active-pointer publication.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum CognitiveSchemaUpgradeWitnessV1 {
    CurrentAnchor(CognitiveRecoveryAnchor),
    RetainedTransition(CognitiveSchemaUpgradeTransitionV1),
    Revoked,
}

/// Host-owned, independently authenticated witness storage. Implementations
/// must return the CURRENT owner disposition and durably compare-and-swap the
/// exact old anchor to the supplied transition, or acknowledge an identical
/// transition idempotently. Storage must survive process failure independently
/// of the cognitive DB. No production implementation or issuer is installed by
/// this crate; an ordinary caller-provided digest is not this host authority.
/// After activation, implementations must archive the transition and durably
/// retain its new anchor, then refresh that independent anchor after subsequent
/// owner mutations. They must never reclassify a pending or stale transition as
/// a current witness merely because a local SQLite file looks consistent.
pub trait CognitiveSchemaUpgradeHostV1: Send + Sync {
    fn current_witness(&self, owner: &AgentId) -> Result<CognitiveSchemaUpgradeWitnessV1, String>;

    fn retain_transition(
        &self,
        transition: &CognitiveSchemaUpgradeTransitionV1,
    ) -> Result<(), String>;
}
