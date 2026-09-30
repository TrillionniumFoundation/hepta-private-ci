//! Sealed, authority-free proposal admission before durable owner publication.
//!
//! Host context fields are independently obtained declarations. The future writer
//! must obtain them again inside its fenced publication transaction; this module
//! neither reads a selected pointer nor persists, publishes or selects a checkpoint.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthenticatedCompactionError;
use crate::AuthenticatedCompactionProofV1;
use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::MAX_QUALIFIED_COMPACTION_INPUTS;
use crate::QualifiedCompactionCandidateV2;
use crate::QualifiedCompactionError;
use crate::resources::preflight_records;

/// Native destination identity; a host must independently register its writer.
pub const COMPACTION_PUBLICATION_DESTINATION_V1: &str = "compact.engine.checkpoint.publish.v1";

/// Actual selected state, distinct from the source vector's nonzero placeholder.
/// A public instance is a declaration, not an authenticated selected-pointer read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompactionSelectedStateV1 {
    Empty,
    Selected {
        generation: Generation,
        checkpoint_digest: Digest32,
    },
}

/// Untrusted proposal inputs. Admission freezes their bounded original preimages.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPublicationRequestV1 {
    pub owner_agent_id: StableId,
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub operation_id: StableId,
    pub policy_generation: Generation,
    pub expected_selected: CompactionSelectedStateV1,
    pub candidate: QualifiedCompactionCandidateV2,
    pub policy: CompactionPolicyV2,
    pub inputs: Vec<CompactionInputRecordV2>,
    pub authenticated_proof: AuthenticatedCompactionProofV1,
}

/// Current host declarations. Values must come from authenticated owners/trust.
/// These references confer no storage fence or publication/final-use permission.
pub struct CompactionPublicationContextV1<'a> {
    pub owner_agent_id: &'a StableId,
    pub scope_id: &'a StableId,
    pub purpose_id: &'a StableId,
    pub selected: &'a CompactionSelectedStateV1,
    pub policy_generation: Generation,
    pub policy_digest: Digest32,
    pub source_cut_digest: Digest32,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub now: u64,
}

/// Sealed validated proposal, retaining full typed inputs and original signatures.
/// Its compact intent is an identity commitment, not a restart body/outbox codec.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPublicationProposalV1 {
    request: CompactionPublicationRequestV1,
    intent_bytes: Vec<u8>,
    intent_digest: Digest32,
}

impl CompactionPublicationProposalV1 {
    /// Admit bounded policy/input preimages, exact selected lineage and current trust.
    pub fn new(
        request: CompactionPublicationRequestV1,
        context: &CompactionPublicationContextV1<'_>,
    ) -> Result<Self, CompactionPublicationError> {
        validate_request(&request, context)?;
        let intent_bytes = publication_intent(&request);
        let intent_digest = Digest32::of_bytes(&intent_bytes);
        Ok(Self {
            request,
            intent_bytes,
            intent_digest,
        })
    }

    pub fn request(&self) -> &CompactionPublicationRequestV1 {
        &self.request
    }

    pub fn intent_bytes(&self) -> &[u8] {
        &self.intent_bytes
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.intent_digest
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Recheck before use; the durable writer must do this in the same transaction
    /// as source eligibility, selected-pointer CAS, dedupe and receipt insertion.
    pub fn revalidate(
        &self,
        context: &CompactionPublicationContextV1<'_>,
    ) -> Result<(), CompactionPublicationError> {
        validate_request(&self.request, context)
    }
}

fn validate_request(
    request: &CompactionPublicationRequestV1,
    context: &CompactionPublicationContextV1<'_>,
) -> Result<(), CompactionPublicationError> {
    if &request.owner_agent_id != context.owner_agent_id {
        return Err(CompactionPublicationError::OwnerBinding);
    }
    if &request.scope_id != context.scope_id
        || request.scope_id != request.candidate.source_snapshot.vector.scope_id
    {
        return Err(CompactionPublicationError::ScopeBinding);
    }
    if &request.purpose_id != context.purpose_id
        || request.purpose_id != request.candidate.source_snapshot.vector.purpose_id
    {
        return Err(CompactionPublicationError::PurposeBinding);
    }
    if &request.expected_selected != context.selected {
        return Err(CompactionPublicationError::SelectedStateChanged);
    }
    if request.policy_generation != context.policy_generation {
        return Err(CompactionPublicationError::PolicyGenerationBinding);
    }
    if context.policy_digest.is_zero() || request.candidate.policy_digest != context.policy_digest {
        return Err(CompactionPublicationError::PolicyBinding);
    }
    let checkpoint = &request.candidate.checkpoint;
    let source_generation = request
        .candidate
        .source_snapshot
        .vector
        .compact_checkpoint_generation;
    match request.expected_selected {
        CompactionSelectedStateV1::Empty => {
            if checkpoint.generation.get() != 1 || checkpoint.predecessor_digest.is_some() {
                return Err(CompactionPublicationError::CheckpointLineage);
            }
            if source_generation.get() != 1 {
                return Err(CompactionPublicationError::SourceGenerationBinding);
            }
        }
        CompactionSelectedStateV1::Selected {
            generation,
            checkpoint_digest,
        } => {
            if checkpoint_digest.is_zero() {
                return Err(CompactionPublicationError::EmptySelectedDigest);
            }
            let next = generation
                .get()
                .checked_add(1)
                .ok_or(CompactionPublicationError::GenerationOverflow)?;
            if checkpoint.generation.get() != next
                || checkpoint.predecessor_digest != Some(checkpoint_digest)
            {
                return Err(CompactionPublicationError::CheckpointLineage);
            }
            if source_generation != generation {
                return Err(CompactionPublicationError::SourceGenerationBinding);
            }
        }
    }
    // Bound caller-controlled inputs before validate_against_inputs clones them.
    if request.inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(CompactionPublicationError::Compaction(
            QualifiedCompactionError::InputLimitExceeded,
        ));
    }
    request.policy.validate()?;
    preflight_records(
        request.inputs.iter().map(|input| &input.record),
        /*digest_references*/ 0,
    )
    .map_err(QualifiedCompactionError::ResourceBudgetExceeded)?;
    request
        .candidate
        .validate_against_inputs(&request.policy, request.inputs.clone())?;
    request.authenticated_proof.revalidate_for(
        &request.candidate,
        context.source_cut_digest,
        context.verifier,
        context.now,
    )?;
    Ok(())
}

fn publication_intent(request: &CompactionPublicationRequestV1) -> Vec<u8> {
    // Four bounded IDs, one fixed destination, fixed-width generations/digests:
    // the complete identity is < 2 KiB regardless of the retained input size.
    let mut bytes = b"hepta.compaction.publication-intent.v1\0".to_vec();
    for value in [
        request.owner_agent_id.as_str(),
        request.scope_id.as_str(),
        request.purpose_id.as_str(),
        COMPACTION_PUBLICATION_DESTINATION_V1,
        request.operation_id.as_str(),
    ] {
        bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }
    bytes.extend_from_slice(&request.policy_generation.get().to_be_bytes());
    match request.expected_selected {
        CompactionSelectedStateV1::Empty => bytes.push(0),
        CompactionSelectedStateV1::Selected {
            generation,
            checkpoint_digest,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(&generation.get().to_be_bytes());
            bytes.extend_from_slice(checkpoint_digest.as_array());
        }
    }
    bytes.extend_from_slice(&request.candidate.checkpoint.generation.get().to_be_bytes());
    for digest in [
        request.candidate.candidate_digest,
        request.candidate.checkpoint.checkpoint_digest,
        request.candidate.source_snapshot.vector_digest,
        request.authenticated_proof.source_cut_digest(),
        request.candidate.policy_digest,
        request.candidate.selection_input_digest,
        request.authenticated_proof.authentication_digest(),
        request.authenticated_proof.proof().proof_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompactionPublicationError {
    Compaction(QualifiedCompactionError),
    Authentication(AuthenticatedCompactionError),
    OwnerBinding,
    ScopeBinding,
    PurposeBinding,
    SelectedStateChanged,
    PolicyGenerationBinding,
    PolicyBinding,
    CheckpointLineage,
    SourceGenerationBinding,
    EmptySelectedDigest,
    GenerationOverflow,
}

impl fmt::Display for CompactionPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompactionPublicationError {}

impl From<QualifiedCompactionError> for CompactionPublicationError {
    fn from(error: QualifiedCompactionError) -> Self {
        Self::Compaction(error)
    }
}

impl From<AuthenticatedCompactionError> for CompactionPublicationError {
    fn from(error: AuthenticatedCompactionError) -> Self {
        Self::Authentication(error)
    }
}

#[cfg(test)]
#[path = "publication_tests.rs"]
mod tests;
