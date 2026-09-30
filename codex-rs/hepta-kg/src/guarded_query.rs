//! Physically bounded, deadline-aware query view.
//!
//! Structural validation, immutable indexes and generation byte measurement are
//! performed once when the view is sealed. Every external query checks its
//! operation guard inside index/support traversal and before returning, and
//! validates the physical output byte bound.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeOperationGuardV2;
use crate::KnowledgePhysicalLimitsV2;
use crate::KnowledgePhysicalUsageV2;
use crate::KnowledgeQueryAdmissionErrorV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeRelationQueryV2;
use crate::KnowledgeRelationQueryWorkV2;
use crate::KnowledgeRelationResultV2;
use crate::KnowledgeResourceErrorV2;
use crate::VerifiedKnowledgeGenerationV2;
use crate::validate_generation_physical_limits_v2;
use crate::validate_query_output_physical_limits_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct KnowledgePhysicalQueryObservationV2 {
    pub work: KnowledgeRelationQueryWorkV2,
    pub generation_usage: KnowledgePhysicalUsageV2,
    pub output_bytes: u64,
}

#[derive(Debug)]
pub struct KnowledgePhysicalQueryViewV2 {
    verified: VerifiedKnowledgeGenerationV2,
    limits: KnowledgePhysicalLimitsV2,
    generation_usage: KnowledgePhysicalUsageV2,
}

impl KnowledgePhysicalQueryViewV2 {
    pub fn new(
        generation: KnowledgeGenerationV2,
        limits: KnowledgePhysicalLimitsV2,
    ) -> Result<Self, KnowledgePhysicalQueryErrorV2> {
        let verified = VerifiedKnowledgeGenerationV2::new(generation)?;
        let generation_usage =
            validate_generation_physical_limits_v2(verified.generation(), limits)?;
        Ok(Self {
            verified,
            limits,
            generation_usage,
        })
    }

    #[must_use]
    pub fn generation(&self) -> &KnowledgeGenerationV2 {
        self.verified.generation()
    }

    #[must_use]
    pub fn relation_kinds(&self) -> &BTreeSet<KnowledgeRelationKindV2> {
        self.verified.relation_kinds()
    }

    #[must_use]
    pub const fn limits(&self) -> KnowledgePhysicalLimitsV2 {
        self.limits
    }

    #[must_use]
    pub const fn generation_usage(&self) -> KnowledgePhysicalUsageV2 {
        self.generation_usage
    }

    pub fn query_relations_external(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: Option<u64>,
        guard: &KnowledgeOperationGuardV2,
    ) -> Result<
        (
            KnowledgeRelationResultV2,
            KnowledgePhysicalQueryObservationV2,
        ),
        KnowledgePhysicalQueryErrorV2,
    > {
        let (result, work) = self
            .verified
            .query_relations_external_guarded_with_output_limit(
                query,
                maximum_support_work,
                self.limits.maximum_query_output_bytes,
                guard,
            )
            .map_err(KnowledgePhysicalQueryErrorV2::from)?;
        let output_bytes = validate_query_output_physical_limits_v2(&result, self.limits)?;
        guard.checkpoint()?;
        Ok((
            result,
            KnowledgePhysicalQueryObservationV2 {
                work,
                generation_usage: self.generation_usage,
                output_bytes,
            },
        ))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgePhysicalQueryErrorV2 {
    Generation(KnowledgeGenerationErrorV2),
    Admission(KnowledgeQueryAdmissionErrorV2),
    Resource(KnowledgeResourceErrorV2),
}

impl From<KnowledgeGenerationErrorV2> for KnowledgePhysicalQueryErrorV2 {
    fn from(error: KnowledgeGenerationErrorV2) -> Self {
        Self::Generation(error)
    }
}

impl From<KnowledgeQueryAdmissionErrorV2> for KnowledgePhysicalQueryErrorV2 {
    fn from(error: KnowledgeQueryAdmissionErrorV2) -> Self {
        match error {
            KnowledgeQueryAdmissionErrorV2::Resource(error) => Self::Resource(error),
            other => Self::Admission(other),
        }
    }
}

impl From<KnowledgeResourceErrorV2> for KnowledgePhysicalQueryErrorV2 {
    fn from(error: KnowledgeResourceErrorV2) -> Self {
        Self::Resource(error)
    }
}

impl fmt::Display for KnowledgePhysicalQueryErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Generation(error) => write!(formatter, "{error}"),
            Self::Admission(error) => write!(formatter, "{error}"),
            Self::Resource(error) => write!(formatter, "{error}"),
        }
    }
}

impl StdError for KnowledgePhysicalQueryErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Generation(error) => Some(error),
            Self::Admission(error) => Some(error),
            Self::Resource(error) => Some(error),
        }
    }
}

#[cfg(test)]
#[path = "guarded_query_tests.rs"]
mod tests;
