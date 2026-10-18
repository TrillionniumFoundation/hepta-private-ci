//! Immutable semantic admission for repeated queries over one owned generation.
//!
//! Admission verifies canonical structure, lineage, bounds, authority posture
//! and content digest once. It does not authenticate the source or adapter;
//! callers must still fence the expected owner cut and persisted generation.

use super::KnowledgeGenerationErrorV2;
use super::KnowledgeGenerationV2;
use super::KnowledgeRelationQueryV2;
use super::KnowledgeRelationResultV2;
use super::query_relations_validated;

/// An owned generation whose semantic validation remains valid across queries.
///
/// The generation cannot be changed through this view. Each query still checks
/// its generation digest, identities and resource bounds and computes the same
/// request and result receipts as the validating free query function.
#[derive(Debug, Eq, PartialEq)]
pub struct ValidatedKnowledgeGenerationV2 {
    generation: KnowledgeGenerationV2,
}

impl ValidatedKnowledgeGenerationV2 {
    /// Validates and consumes a generation without cloning its support vectors.
    pub fn new(generation: KnowledgeGenerationV2) -> Result<Self, KnowledgeGenerationErrorV2> {
        generation.validate()?;
        Ok(Self { generation })
    }

    /// Reads the admitted generation without exposing mutation or ownership.
    pub const fn as_generation(&self) -> &KnowledgeGenerationV2 {
        &self.generation
    }

    pub fn query_relations(
        &self,
        query: KnowledgeRelationQueryV2,
    ) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
        query_relations_validated(&self.generation, query)
    }
}

#[cfg(test)]
#[path = "validated_generation_tests.rs"]
mod tests;
