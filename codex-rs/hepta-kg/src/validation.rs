//! Internal validation typestate shared by query and cache construction.

use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;

#[derive(Debug)]
pub(crate) struct ValidatedKnowledgeGenerationV2(KnowledgeGenerationV2);

impl ValidatedKnowledgeGenerationV2 {
    pub(crate) fn new(
        generation: KnowledgeGenerationV2,
    ) -> Result<Self, KnowledgeGenerationErrorV2> {
        generation.validate()?;
        Ok(Self(generation))
    }

    pub(crate) fn generation(&self) -> &KnowledgeGenerationV2 {
        &self.0
    }

    pub(crate) fn into_generation(self) -> KnowledgeGenerationV2 {
        self.0
    }
}
