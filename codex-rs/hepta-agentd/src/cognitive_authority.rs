//! Host-owned current authority input for production cognitive reads.
//!
//! The SQLite owner supplies cognitive frontiers. Every other Lane C identity
//! below remains owned by its canonical host component. Agentd combines these
//! values only for one read and re-fetches them immediately before consumption;
//! it never manufactures defaults or turns the resulting receipt into authority.

use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_COGNITIVE_READ_AUTHORITY_LEASE_MS: u64 = 300_000;

/// External owner state that cannot be derived from the cognitive SQLite cut.
///
/// Implementations are host capabilities, not configuration bags: `current`
/// must return the owners' current values or fail closed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveReadAuthoritySnapshotV1 {
    pub compact_checkpoint_generation: Generation,
    pub prompt_registry_revision: Revision,
    pub retrieval_profile_digest: Digest32,
    pub encoder_preprocessor_digest: Digest32,
    pub authority_epoch: u64,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub maximum_lease_ms: u64,
}

impl CognitiveReadAuthoritySnapshotV1 {
    pub fn validate(&self) -> Result<(), SnapshotProviderError> {
        if self.authority_epoch == 0 {
            return Err(SnapshotProviderError::InvalidRequest("authority_epoch"));
        }
        if self.maximum_lease_ms == 0
            || self.maximum_lease_ms > MAX_COGNITIVE_READ_AUTHORITY_LEASE_MS
        {
            return Err(SnapshotProviderError::InvalidLeaseWindow);
        }
        for digest in [
            self.retrieval_profile_digest,
            self.encoder_preprocessor_digest,
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            if digest.is_zero() {
                return Err(SnapshotProviderError::EmptyDigest);
            }
        }
        Ok(())
    }

    pub(crate) fn bind_lane_c(
        &self,
        cut: &DurableCognitiveSnapshot,
        purpose_id: StableId,
    ) -> Result<LaneCGenerationVectorV1, SnapshotProviderError> {
        self.validate()?;
        let frontiers = cut.frontiers();
        let vector = LaneCGenerationVectorV1 {
            scope_id: cut.scope_id().clone(),
            purpose_id,
            memory_ledger_frontier: frontiers.memory,
            knowledge_fact_frontier: frontiers.knowledge_facts,
            tombstone_frontier: frontiers.tombstone,
            source_ledger_frontier: frontiers.source,
            knowledge_graph_generation: frontiers.knowledge_graph,
            compact_checkpoint_generation: self.compact_checkpoint_generation,
            prompt_registry_revision: self.prompt_registry_revision,
            retrieval_profile_digest: self.retrieval_profile_digest,
            encoder_preprocessor_digest: self.encoder_preprocessor_digest,
            authority_epoch: self.authority_epoch,
            model_digest: self.model_digest,
            tokenizer_digest: self.tokenizer_digest,
            template_digest: self.template_digest,
            tool_schema_digest: self.tool_schema_digest,
        };
        vector
            .validate()
            .map_err(SnapshotProviderError::Contract)?;
        Ok(vector)
    }
}

/// Current host-authority capability required by the production context read.
///
/// A missing implementation, stale witness, revoked epoch, reclaimed generation,
/// or indeterminate owner must return an error. Agentd has no legacy fallback.
pub trait CurrentCognitiveReadAuthority: Send + Sync {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<CognitiveReadAuthoritySnapshotV1, SnapshotProviderError>;
}

#[cfg(test)]
pub(crate) fn test_cognitive_read_authority(
) -> std::sync::Arc<dyn CurrentCognitiveReadAuthority> {
    struct TestAuthority;

    impl CurrentCognitiveReadAuthority for TestAuthority {
        fn current(
            &self,
            _owner: &AgentId,
            _body_generation: u64,
        ) -> Result<CognitiveReadAuthoritySnapshotV1, SnapshotProviderError> {
            let digest = |value: &str| Digest32::of_bytes(value.as_bytes());
            Ok(CognitiveReadAuthoritySnapshotV1 {
                compact_checkpoint_generation: Generation::new(1)
                    .map_err(|_| SnapshotProviderError::Indeterminate)?,
                prompt_registry_revision: Revision::new(1)
                    .map_err(|_| SnapshotProviderError::Indeterminate)?,
                retrieval_profile_digest: digest("test-retrieval-profile"),
                encoder_preprocessor_digest: digest("test-encoder-profile"),
                authority_epoch: 1,
                model_digest: digest("test-model"),
                tokenizer_digest: digest("test-tokenizer"),
                template_digest: digest("test-template"),
                tool_schema_digest: digest("test-tool-schema"),
                maximum_lease_ms: 30_000,
            })
        }
    }

    std::sync::Arc::new(TestAuthority)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn snapshot() -> CognitiveReadAuthoritySnapshotV1 {
        CognitiveReadAuthoritySnapshotV1 {
            compact_checkpoint_generation: Generation::new(1).unwrap(),
            prompt_registry_revision: Revision::new(1).unwrap(),
            retrieval_profile_digest: digest("retrieval"),
            encoder_preprocessor_digest: digest("encoder"),
            authority_epoch: 1,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
            maximum_lease_ms: 1_000,
        }
    }

    #[test]
    fn authority_snapshot_rejects_missing_epoch_and_unbounded_lease() {
        let mut value = snapshot();
        value.authority_epoch = 0;
        assert_eq!(
            value.validate(),
            Err(SnapshotProviderError::InvalidRequest("authority_epoch"))
        );

        let mut value = snapshot();
        value.maximum_lease_ms = MAX_COGNITIVE_READ_AUTHORITY_LEASE_MS + 1;
        assert_eq!(
            value.validate(),
            Err(SnapshotProviderError::InvalidLeaseWindow)
        );
    }
}
