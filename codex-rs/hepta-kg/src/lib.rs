//! Rebuildable knowledge-graph projection.

#![forbid(unsafe_code)]

mod generation;
mod guarded_query;
mod incremental;
#[cfg(feature = "legacy-v1")]
mod legacy_v1;
mod prompt_factor;
mod publication;
mod resource;
mod validation;

use std::error::Error as StdError;
use std::fmt;

pub use generation::KnowledgeEdgeIdentityV2;
pub use generation::KnowledgeEdgeV2;
pub use generation::KnowledgeGenerationErrorV2;
pub use generation::KnowledgeGenerationV2;
pub use generation::KnowledgeNodeV2;
pub use generation::KnowledgeProjectionDeltaV2;
pub use generation::KnowledgeProjectionInputV2;
pub use generation::KnowledgePublicationDispositionV2;
pub use generation::KnowledgePublicationReceiptV2;
pub use generation::KnowledgeRelationKindV2;
pub use generation::KnowledgeRelationQueryV2;
pub use generation::KnowledgeRelationQueryWorkV2;
pub use generation::KnowledgeRelationResultV2;
pub use generation::KnowledgeSupportV2;
pub use generation::MAX_KNOWLEDGE_EDGES_V2;
pub use generation::MAX_KNOWLEDGE_NODES_V2;
pub use generation::MAX_SUPPORTS_PER_RELATION_V2;
pub use generation::VerifiedKnowledgeGenerationV2;
pub use generation::apply_incremental_delta;
pub use generation::build_complete_generation;
pub use generation::publish_generation;
pub use generation::query_relations;
pub use generation::query_relations_with_work;
pub use guarded_query::KnowledgePhysicalQueryErrorV2;
pub use guarded_query::KnowledgePhysicalQueryObservationV2;
pub use guarded_query::KnowledgePhysicalQueryViewV2;
pub use incremental::KnowledgeDependencyIndexV2;
pub use incremental::KnowledgeImpactClosureV2;
pub use incremental::KnowledgeIncrementalErrorV2;
pub use incremental::KnowledgeIncrementalPlanV2;
pub use incremental::KnowledgeMutationFrontierV2;
pub use incremental::KnowledgeStorageDeltaV2;
pub use incremental::KnowledgeSupportIdentityV2;
pub use incremental::apply_storage_delta_v2;
pub use incremental::compute_impact_closure_v2;
pub use incremental::plan_generation_transition_v2;
pub use incremental::plan_incremental_publication_v2;
pub use incremental::should_run_full_rebuild_audit_v2;
pub use incremental::verify_incremental_equivalence_v2;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::Error;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::Error as LegacyKnowledgeProjectionErrorV1;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::KnowledgeEdge;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::KnowledgeProjection;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::rebuild;
pub use prompt_factor::PromptFactorProjectionErrorV1;
pub use prompt_factor::PromptFactorProjectionV1;
pub use prompt_factor::build_prompt_factor_projection_v1;
pub use publication::KnowledgeCommitOutcomeV2;
pub use publication::KnowledgePublicationErrorCodeV2;
pub use publication::KnowledgePublicationErrorV2;
pub use publication::KnowledgeReconciliationStateV2;
pub use publication::KnowledgeTransactionalPublicationV2;
pub use publication::KnowledgeTransactionalStorageV2;
pub use publication::publish_transactionally;
pub use resource::KnowledgeCacheErrorV2;
pub use resource::KnowledgeCancellationV2;
pub use resource::KnowledgeGenerationCacheMetricsV2;
pub use resource::KnowledgeGenerationCacheV2;
pub use resource::KnowledgeJsonShapeV2;
pub use resource::KnowledgeOperationGuardV2;
pub use resource::KnowledgePhysicalLimitsV2;
pub use resource::KnowledgePhysicalUsageV2;
pub use resource::KnowledgePublicationLimiterV2;
pub use resource::KnowledgePublicationPermitV2;
pub use resource::KnowledgeResourceErrorCodeV2;
pub use resource::KnowledgeResourceErrorV2;
pub use resource::MAX_KNOWLEDGE_FIELD_BYTES_V2;
pub use resource::MAX_KNOWLEDGE_GENERATION_BYTES_V2;
pub use resource::MAX_KNOWLEDGE_JSON_BYTES_V2;
pub use resource::MAX_KNOWLEDGE_JSON_DEPTH_V2;
pub use resource::MAX_KNOWLEDGE_JSON_ELEMENTS_V2;
pub use resource::MAX_KNOWLEDGE_QUERY_OUTPUT_BYTES_V2;
pub use resource::measure_generation_v2;
pub use resource::measure_projection_input_v2;
pub use resource::measure_query_result_bytes_v2;
pub use resource::validate_generation_physical_limits_v2;
pub use resource::validate_json_shape_v2;
pub use resource::validate_projection_input_physical_limits_v2;
pub use resource::validate_query_output_physical_limits_v2;

/// Default support-inspection/copy budget for the bounded external query entry.
///
/// This is operation accounting, not a latency, allocator or authorization bound.
pub const DEFAULT_QUERY_SUPPORT_WORK_V2: u64 = 1_000_000;

/// Hard library ceiling for one bounded external query.
pub const MAX_QUERY_SUPPORT_WORK_V2: u64 = 1_000_000;

/// Admission/result classification for the bounded external query entry.
///
/// Successful empty results remain `Ok`; budget exhaustion, invalid admission,
/// deadline/cancellation and semantic/source-cut failures remain distinct. No
/// exhausted or cancelled request returns a partial success or an inexact
/// omitted count.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgeQueryAdmissionErrorV2 {
    InvalidBudget {
        requested_support_work: u64,
        maximum_support_work: u64,
    },
    BudgetExceeded {
        maximum_support_work: u64,
        attempted_support_work: u64,
    },
    Resource(KnowledgeResourceErrorV2),
    Query(KnowledgeGenerationErrorV2),
}

impl From<KnowledgeGenerationErrorV2> for KnowledgeQueryAdmissionErrorV2 {
    fn from(error: KnowledgeGenerationErrorV2) -> Self {
        Self::Query(error)
    }
}

impl From<KnowledgeResourceErrorV2> for KnowledgeQueryAdmissionErrorV2 {
    fn from(error: KnowledgeResourceErrorV2) -> Self {
        Self::Resource(error)
    }
}

impl fmt::Display for KnowledgeQueryAdmissionErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBudget {
                requested_support_work,
                maximum_support_work,
            } => write!(
                formatter,
                "invalid query support-work budget {requested_support_work}; maximum is {maximum_support_work}"
            ),
            Self::BudgetExceeded {
                maximum_support_work,
                attempted_support_work,
            } => write!(
                formatter,
                "query support-work budget {maximum_support_work} exhausted at {attempted_support_work}"
            ),
            Self::Resource(error) => write!(formatter, "{error}"),
            Self::Query(error) => write!(formatter, "{error}"),
        }
    }
}

impl StdError for KnowledgeQueryAdmissionErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Resource(error) => Some(error),
            Self::Query(error) => Some(error),
            Self::InvalidBudget { .. } | Self::BudgetExceeded { .. } => None,
        }
    }
}

/// Explicit unbounded reference/oracle query.
///
/// Product-facing callers should use [`KnowledgePhysicalQueryViewV2`] or an
/// owner adapter that embeds it. This function validates and scans the complete
/// generation and exists for oracle, migration and trusted-owner comparison
/// work; it is not the external resource contract.
pub fn query_relations_reference_unbounded(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
    generation::query_relations(generation, query)
}
