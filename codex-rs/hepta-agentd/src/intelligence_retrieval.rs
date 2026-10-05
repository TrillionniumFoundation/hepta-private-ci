//! Exact `memory.retrieval` owner binding for the normal Agentd intelligence path.
//!
//! The seven intelligence stages remain unchanged. Retrieval is an input owner:
//! its owner-created canonical result is retained, converted to the existing
//! `intelligence.control` consumer contract, and fenced against the signed
//! current-owner oracle immediately before and after the product run.

use std::ops::Deref;

use codex_hepta_intelligence::CanonicalFreshnessOracleV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_intelligence::CanonicalRecallIntelligenceInputV1;
use codex_hepta_intelligence::OwnerBindingV1;
use codex_hepta_intelligence::bind_canonical_recall_for_intelligence_v1;
use codex_hepta_memory_retrieval::RetrievalOwnedCanonicalRecallV1;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCanonicalRecallInputV1 {
    intelligence: CanonicalRecallIntelligenceInputV1,
    retrieval: RetrievalOwnedCanonicalRecallV1,
    retrieval_owner: OwnerBindingV1,
}

impl AgentdCanonicalRecallInputV1 {
    fn seal(
        run_id: StableId,
        retrieval: RetrievalOwnedCanonicalRecallV1,
        retrieval_owner: OwnerBindingV1,
    ) -> Result<Self, CanonicalIntelligenceError> {
        retrieval
            .validate()
            .map_err(|error| CanonicalIntelligenceError::CanonicalRecall(error.to_string()))?;
        validate_retrieval_owner_binding(&retrieval_owner)?;
        let upstream_binding_digest = retrieval.consumer_binding().binding_sha256.digest();
        let intelligence = bind_canonical_recall_for_intelligence_v1(
            run_id,
            retrieval.packet().clone(),
            Some(upstream_binding_digest),
        )?;
        let value = Self {
            intelligence,
            retrieval,
            retrieval_owner,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), CanonicalIntelligenceError> {
        self.retrieval
            .validate()
            .map_err(|error| CanonicalIntelligenceError::CanonicalRecall(error.to_string()))?;
        validate_retrieval_owner_binding(&self.retrieval_owner)?;
        self.intelligence.validate()?;
        let upstream = self.retrieval.consumer_binding();
        if &self.intelligence.packet != self.retrieval.packet()
            || self
                .intelligence
                .consumer_binding
                .compatibility_payload_sha256
                .map(|digest| digest.digest())
                != Some(upstream.binding_sha256.digest())
        {
            return Err(CanonicalIntelligenceError::CanonicalRecall(
                "intelligence recall does not bind the exact retrieval owner result".to_owned(),
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn retrieval(&self) -> &RetrievalOwnedCanonicalRecallV1 {
        &self.retrieval
    }

    #[must_use]
    pub const fn retrieval_owner(&self) -> &OwnerBindingV1 {
        &self.retrieval_owner
    }

    #[must_use]
    pub const fn intelligence_input(&self) -> &CanonicalRecallIntelligenceInputV1 {
        &self.intelligence
    }

    #[must_use]
    pub fn into_intelligence_input(self) -> CanonicalRecallIntelligenceInputV1 {
        self.intelligence
    }
}

impl Deref for AgentdCanonicalRecallInputV1 {
    type Target = CanonicalRecallIntelligenceInputV1;

    fn deref(&self) -> &Self::Target {
        self.intelligence_input()
    }
}

pub fn bind_retrieval_owned_canonical_recall_for_agentd_v1(
    run_id: StableId,
    retrieval: RetrievalOwnedCanonicalRecallV1,
    retrieval_owner: OwnerBindingV1,
) -> Result<AgentdCanonicalRecallInputV1, CanonicalIntelligenceError> {
    AgentdCanonicalRecallInputV1::seal(run_id, retrieval, retrieval_owner)
}

pub(super) fn validate_retrieval_owner_current<O: CanonicalFreshnessOracleV1>(
    snapshot: &CanonicalIntelligenceSnapshotV1,
    recall: &AgentdCanonicalRecallInputV1,
    oracle: &mut O,
) -> Result<(), CanonicalIntelligenceError> {
    recall.validate()?;
    let expected = recall.retrieval_owner();
    let current = oracle
        .current(&expected.owner_id)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(expected.owner_id.clone()))?;
    if current.owner_id != expected.owner_id
        || current.generation != expected.generation
        || current.implementation_digest != expected.implementation_digest
    {
        return Err(CanonicalIntelligenceError::StaleOwner(
            expected.owner_id.clone(),
        ));
    }
    if current.key_digest != expected.key_digest || current.key_epoch != expected.key_epoch {
        return Err(CanonicalIntelligenceError::KeyDrift(
            expected.owner_id.clone(),
        ));
    }
    if current.authority_epoch != snapshot.authority_epoch() {
        return Err(CanonicalIntelligenceError::AuthorityEpochDrift(
            expected.owner_id.clone(),
        ));
    }
    if current.revocation_frontier_digest != snapshot.revocation_frontier_digest() {
        return Err(CanonicalIntelligenceError::RevocationFrontierDrift(
            expected.owner_id.clone(),
        ));
    }
    Ok(())
}

fn validate_retrieval_owner_binding(
    binding: &OwnerBindingV1,
) -> Result<(), CanonicalIntelligenceError> {
    if binding.owner_id.as_str() != "memory.retrieval"
        || binding.implementation_digest.is_zero()
        || binding.key_digest.is_zero()
        || binding.key_epoch == 0
    {
        return Err(CanonicalIntelligenceError::CanonicalRecall(
            "invalid memory.retrieval owner binding".to_owned(),
        ));
    }
    Ok(())
}
