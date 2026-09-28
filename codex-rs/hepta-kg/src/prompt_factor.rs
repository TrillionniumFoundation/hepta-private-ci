//! Canonical prompt-factor interaction projection from the prompt.registry owner view.
//!
//! This adapter does not mint relation facts. It accepts only the complete,
//! authority-free source emitted by PromptRegistry and translates it into the
//! same KnowledgeGenerationV2 used by every other knowledge.graph consumer.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_prompt_registry::PromptFactorGraphSourceV1;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeQueryAdmissionErrorV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeRelationQueryV2;
use crate::KnowledgeRelationQueryWorkV2;
use crate::KnowledgeRelationResultV2;
use crate::KnowledgeSupportV2;
use crate::VerifiedKnowledgeGenerationV2;
use crate::build_complete_generation;

const PROMPT_FACTOR_PROFILE_DOMAIN: &[u8] = b"hepta.knowledge.prompt-factor-profile.v1";
const PROMPT_FACTOR_NODE_DOMAIN: &[u8] = b"hepta.knowledge.prompt-factor-node.v1";
const PROMPT_FACTOR_VALIDITY_DOMAIN: &[u8] = b"hepta.knowledge.prompt-factor-validity.v1";
const PROMPT_RELATION_VALIDITY_DOMAIN: &[u8] = b"hepta.knowledge.prompt-relation-validity.v1";

#[derive(Clone, Debug)]
pub struct PromptFactorProjectionV1 {
    registry_revision: u64,
    registry_snapshot_digest: Digest32,
    source_digest: Digest32,
    verified_generation: Arc<VerifiedKnowledgeGenerationV2>,
    authority: AuthorityPosture,
}

impl PartialEq for PromptFactorProjectionV1 {
    fn eq(&self, other: &Self) -> bool {
        self.registry_revision == other.registry_revision
            && self.registry_snapshot_digest == other.registry_snapshot_digest
            && self.source_digest == other.source_digest
            && self.generation() == other.generation()
            && self.authority == other.authority
    }
}

impl Eq for PromptFactorProjectionV1 {}

impl PromptFactorProjectionV1 {
    #[must_use]
    pub const fn registry_revision(&self) -> u64 {
        self.registry_revision
    }

    #[must_use]
    pub const fn registry_snapshot_digest(&self) -> Digest32 {
        self.registry_snapshot_digest
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub fn generation(&self) -> &KnowledgeGenerationV2 {
        self.verified_generation.generation()
    }

    /// Executes the public bounded query contract against the immutable view
    /// built when this owner projection was sealed. Structural validation and
    /// indexes are reused; any temporal visibility cut is still evaluated by
    /// the indexed query on every call.
    pub fn query_relations_external(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: Option<u64>,
    ) -> Result<
        (KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2),
        KnowledgeQueryAdmissionErrorV2,
    > {
        self.verified_generation
            .query_relations_external(query, maximum_support_work)
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), PromptFactorProjectionErrorV1> {
        if self.registry_revision == 0
            || self.registry_snapshot_digest.is_zero()
            || self.source_digest.is_zero()
            || self.generation().source_snapshot_digest != self.source_digest
            || self.generation().generation_digest.is_zero()
            || self.authority.grants_any()
        {
            return Err(PromptFactorProjectionErrorV1::InvalidProjection);
        }
        // The verified view is created only by `VerifiedKnowledgeGenerationV2::new`
        // and is immutable behind `Arc`; repeating full structural validation on
        // every optimizer call would discard the purpose of the sealed view.
        Ok(())
    }
}

pub fn build_prompt_factor_projection_v1(
    generation: Generation,
    generation_vector_digest: Digest32,
    source: &PromptFactorGraphSourceV1,
) -> Result<PromptFactorProjectionV1, PromptFactorProjectionErrorV1> {
    source
        .validate()
        .map_err(|error| PromptFactorProjectionErrorV1::Source(error.to_string()))?;
    if generation_vector_digest.is_zero() {
        return Err(PromptFactorProjectionErrorV1::InvalidGenerationVector);
    }

    let nodes = source
        .factors()
        .iter()
        .map(|factor| {
            let mut payload = PROMPT_FACTOR_NODE_DOMAIN.to_vec();
            push_id(&mut payload, &factor.factor_id);
            push_id(&mut payload, &factor.semantic_version);
            payload.extend_from_slice(factor.content_digest.as_array());
            Ok(KnowledgeNodeV2 {
                node_id: factor.factor_id.clone(),
                node_kind_id: stable_id("kind:prompt-factor")?,
                payload_digest: Digest32::of_bytes(&payload),
                supports: vec![KnowledgeSupportV2 {
                    source_id: factor.factor_id.clone(),
                    source_revision: source.registry_revision(),
                    source_fact_digest: factor.content_digest,
                    validity_digest: scoped_digest(
                        PROMPT_FACTOR_VALIDITY_DOMAIN,
                        &factor.factor_id,
                        factor.content_digest,
                    ),
                    valid_from_unix_seconds: None,
                    valid_to_unix_seconds: None,
                    tombstoned: false,
                }],
            })
        })
        .collect::<Result<Vec<_>, PromptFactorProjectionErrorV1>>()?;

    let edges = source
        .relations()
        .iter()
        .map(|relation| {
            let relation_kind = match relation.kind {
                PromptFactorRelationKind::Complements => KnowledgeRelationKindV2::PromptComplements,
                PromptFactorRelationKind::Substitutes => KnowledgeRelationKindV2::PromptSubstitutes,
                PromptFactorRelationKind::Conflicts => KnowledgeRelationKindV2::PromptConflicts,
            };
            Ok(KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: relation.left_factor_id.clone(),
                    relation: relation_kind,
                    target_node_id: relation.right_factor_id.clone(),
                },
                confidence: ProbabilityQ32::ONE,
                validity_digest: scoped_digest(
                    PROMPT_RELATION_VALIDITY_DOMAIN,
                    &relation.relation_id,
                    relation.evidence_digest,
                ),
                supports: vec![KnowledgeSupportV2 {
                    source_id: relation.relation_id.clone(),
                    source_revision: source.registry_revision(),
                    source_fact_digest: relation.evidence_digest,
                    validity_digest: scoped_digest(
                        PROMPT_RELATION_VALIDITY_DOMAIN,
                        &relation.relation_id,
                        relation.evidence_digest,
                    ),
                    valid_from_unix_seconds: None,
                    valid_to_unix_seconds: None,
                    tombstoned: false,
                }],
            })
        })
        .collect::<Result<Vec<_>, PromptFactorProjectionErrorV1>>()?;

    let graph_profile_digest = Digest32::of_bytes(PROMPT_FACTOR_PROFILE_DOMAIN);
    let projected = build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: source.source_digest(),
            generation_vector_digest,
            graph_profile_digest,
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .map_err(|error| PromptFactorProjectionErrorV1::Kernel(error.to_string()))?;
    let verified_generation = VerifiedKnowledgeGenerationV2::new(projected)
        .map_err(|error| PromptFactorProjectionErrorV1::Kernel(error.to_string()))?;

    let result = PromptFactorProjectionV1 {
        registry_revision: source.registry_revision().get(),
        registry_snapshot_digest: source.registry_snapshot_digest(),
        source_digest: source.source_digest(),
        verified_generation: Arc::new(verified_generation),
        authority: AuthorityPosture::DENY_ALL,
    };
    result.validate()?;
    Ok(result)
}

fn stable_id(value: &str) -> Result<StableId, PromptFactorProjectionErrorV1> {
    StableId::new(value.to_string()).map_err(|_| PromptFactorProjectionErrorV1::InvalidIdentity)
}

fn scoped_digest(domain: &[u8], id: &StableId, digest: Digest32) -> Digest32 {
    let mut bytes = domain.to_vec();
    push_id(&mut bytes, id);
    bytes.extend_from_slice(digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptFactorProjectionErrorV1 {
    Source(String),
    Kernel(String),
    InvalidIdentity,
    InvalidGenerationVector,
    InvalidProjection,
}

impl fmt::Display for PromptFactorProjectionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptFactorProjectionErrorV1 {}
