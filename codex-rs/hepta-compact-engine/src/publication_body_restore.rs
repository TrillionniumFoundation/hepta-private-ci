//! Strict V1 binary restoration; counts are bounded before allocation.

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::CompactionPublicationBodyError as Error;
use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::CompactionPublicationContextV1;
use crate::CompactionPublicationProposalV1;
use crate::CompactionPublicationRequestV1;
use crate::CompactionQualificationV2;
use crate::CompactionSelectedStateV1;
use crate::CompactionSourceAuthorityBindingV1;
use crate::MAX_PROTECTED_COMPACTION_REFS;
use crate::MAX_QUALIFIED_COMPACTION_INPUTS;
use crate::SignedCompactionEvidenceV1;
use crate::build_qualified_candidate;
use crate::prove_compaction_with_signed_evidence_v1;

const DOMAIN: &[u8] = b"hepta.compaction.publication-body.v1\0";

pub(super) fn restore(
    binary: &[u8],
    context: &CompactionPublicationContextV1<'_>,
) -> Result<CompactionPublicationProposalV1, Error> {
    let mut input = Reader(binary);
    if input.bytes(DOMAIN.len())? != DOMAIN {
        return Err(Error::InvalidBinary("domain"));
    }
    let owner_agent_id = input.id()?;
    let scope_id = input.id()?;
    let purpose_id = input.id()?;
    let operation_id = input.id()?;
    let policy_generation = Generation::new(input.u64()?)?;
    let expected_selected = match input.tag()? {
        0 => CompactionSelectedStateV1::Empty,
        1 => CompactionSelectedStateV1::Selected {
            generation: Generation::new(input.u64()?)?,
            checkpoint_digest: input.digest()?,
        },
        _ => return Err(Error::InvalidBinary("selected_tag")),
    };
    let vector = LaneCGenerationVectorV1 {
        scope_id: input.id()?,
        purpose_id: input.id()?,
        memory_ledger_frontier: input.u64()?,
        knowledge_fact_frontier: input.u64()?,
        tombstone_frontier: input.u64()?,
        source_ledger_frontier: input.u64()?,
        knowledge_graph_generation: Generation::new(input.u64()?)?,
        compact_checkpoint_generation: Generation::new(input.u64()?)?,
        prompt_registry_revision: Revision::new(input.u64()?)?,
        retrieval_profile_digest: input.digest()?,
        encoder_preprocessor_digest: input.digest()?,
        authority_epoch: input.u64()?,
        model_digest: input.digest()?,
        tokenizer_digest: input.digest()?,
        template_digest: input.digest()?,
        tool_schema_digest: input.digest()?,
    };
    let source_snapshot = CognitiveSnapshotKeyV1::new(vector)?;
    let policy_id = input.id()?;
    let algorithm_digest = input.digest()?;
    let compatibility_digest = input.digest()?;
    let maximum_retained_records = input.u32()?;
    let count = input.count(MAX_PROTECTED_COMPACTION_REFS, /*minimum_bytes*/ 5)?;
    let mut protected_record_ids = Vec::with_capacity(count);
    for _ in 0..count {
        protected_record_ids.push(input.id()?);
    }
    let policy = CompactionPolicyV2 {
        policy_id,
        algorithm_digest,
        compatibility_digest,
        maximum_retained_records,
        protected_record_ids,
    };
    policy.validate()?;
    // Even an empty-citation record requires 88 bytes including its selection fields.
    let count = input.count(MAX_QUALIFIED_COMPACTION_INPUTS, /*minimum_bytes*/ 88)?;
    let mut inputs = Vec::with_capacity(count);
    for _ in 0..count {
        let record_id = input.id()?;
        let revision = Revision::new(input.u64()?)?;
        let kind = match input.tag()? {
            0 => MemoryKind::Episode,
            1 => MemoryKind::Fact,
            2 => MemoryKind::Preference,
            3 => MemoryKind::Procedure,
            _ => return Err(Error::InvalidBinary("memory_kind")),
        };
        let state = match input.tag()? {
            0 => RecordState::Live,
            1 => RecordState::Tombstone,
            _ => return Err(Error::InvalidBinary("record_state")),
        };
        let content_digest = input.digest()?;
        let predecessor_digest = match input.tag()? {
            0 => None,
            1 => Some(input.digest()?),
            _ => return Err(Error::InvalidBinary("predecessor_tag")),
        };
        let count = input.count(/*maximum*/ 64, /*minimum_bytes*/ 37)?;
        let mut citations = Vec::with_capacity(count);
        for _ in 0..count {
            citations.push(Citation {
                source_id: input.id()?,
                source_digest: input.digest()?,
            });
        }
        inputs.push(CompactionInputRecordV2 {
            record: MemoryRecord {
                record_id,
                revision,
                kind,
                state,
                content_digest,
                predecessor_digest,
                citations,
            },
            retention_priority: input.u32()?,
            retention_reason_digest: input.digest()?,
        });
    }
    let source_binding = CompactionSourceAuthorityBindingV1 {
        source_cut_digest: input.digest()?,
        scope_digest: input.digest()?,
        objective_digest: input.digest()?,
        authority_epoch: input.u64()?,
    };
    let qualification = CompactionQualificationV2 {
        evaluator_id: input.id()?,
        candidate_digest: input.digest()?,
        retained_query_suite_digest: input.digest()?,
        reconstruction_obligation_digest: input.digest()?,
        contradiction_holdout_digest: input.digest()?,
        retained_queries_passed: input.boolean()?,
        reconstruction_passed: input.boolean()?,
        contradictions_preserved: input.boolean()?,
        deletion_non_resurrection_passed: input.boolean()?,
    };
    let evidence = SignedCompactionEvidenceV1 {
        generator: input.signed()?,
        evaluator: input.signed()?,
    };
    let expected_candidate = input.digest()?;
    let expected_checkpoint = input.digest()?;
    let expected_authentication = input.digest()?;
    let expected_intent = input.digest()?;
    if !input.0.is_empty() {
        return Err(Error::InvalidBinary("trailing_bytes"));
    }
    let (generation, predecessor) = match expected_selected {
        CompactionSelectedStateV1::Empty => (Generation::new(/*value*/ 1)?, None),
        CompactionSelectedStateV1::Selected {
            generation,
            checkpoint_digest,
        } => (
            Generation::new(
                generation
                    .get()
                    .checked_add(1)
                    .ok_or(Error::InvalidBinary("generation_overflow"))?,
            )?,
            Some(checkpoint_digest),
        ),
    };
    let candidate = build_qualified_candidate(
        source_snapshot,
        generation,
        predecessor,
        &policy,
        inputs.clone(),
    )?;
    if candidate.candidate_digest != expected_candidate {
        return Err(Error::CommitmentMismatch("candidate"));
    }
    if candidate.checkpoint.checkpoint_digest != expected_checkpoint {
        return Err(Error::CommitmentMismatch("checkpoint"));
    }
    let authenticated_proof = prove_compaction_with_signed_evidence_v1(
        &candidate,
        source_binding,
        qualification,
        &evidence,
        context.verifier,
        context.now,
    )?;
    if authenticated_proof.authentication_digest() != expected_authentication {
        return Err(Error::CommitmentMismatch("authentication"));
    }
    let proposal = CompactionPublicationProposalV1::new(
        CompactionPublicationRequestV1 {
            owner_agent_id,
            scope_id,
            purpose_id,
            operation_id,
            policy_generation,
            expected_selected,
            candidate,
            policy,
            inputs,
            authenticated_proof,
        },
        context,
    )?;
    if proposal.intent_digest() != expected_intent {
        return Err(Error::CommitmentMismatch("intent"));
    }
    Ok(proposal)
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn bytes(&mut self, count: usize) -> Result<&'a [u8], Error> {
        let bytes = self.0.get(..count).ok_or(Error::TruncatedBinary)?;
        self.0 = &self.0[count..];
        Ok(bytes)
    }
    fn tag(&mut self) -> Result<u8, Error> {
        Ok(self.bytes(/*count*/ 1)?[0])
    }
    fn u32(&mut self) -> Result<u32, Error> {
        let mut bytes = [0; 4];
        bytes.copy_from_slice(self.bytes(/*count*/ 4)?);
        Ok(u32::from_be_bytes(bytes))
    }
    fn u64(&mut self) -> Result<u64, Error> {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(self.bytes(/*count*/ 8)?);
        Ok(u64::from_be_bytes(bytes))
    }
    fn digest(&mut self) -> Result<Digest32, Error> {
        let mut bytes = [0; 32];
        bytes.copy_from_slice(self.bytes(/*count*/ 32)?);
        Ok(Digest32::from_array(bytes))
    }
    fn id(&mut self) -> Result<StableId, Error> {
        let count = self.u32()? as usize;
        if count == 0 || count > 128 {
            return Err(Error::InvalidBinary("identifier_length"));
        }
        let raw = std::str::from_utf8(self.bytes(count)?)
            .map_err(|_| Error::InvalidBinary("identifier_utf8"))?;
        Ok(StableId::new(raw)?)
    }
    fn count(&mut self, maximum: usize, minimum_bytes: usize) -> Result<usize, Error> {
        let count = self.u32()? as usize;
        if count > maximum || count > self.0.len() / minimum_bytes {
            return Err(Error::InvalidBinary("collection_count"));
        }
        Ok(count)
    }
    fn boolean(&mut self) -> Result<bool, Error> {
        match self.tag()? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(Error::InvalidBinary("boolean")),
        }
    }
    fn signed(&mut self) -> Result<SignedLearningEvidenceV1, Error> {
        let evidence_id = self.id()?;
        let principal_id = self.id()?;
        let role = match self.tag()? {
            0 => LearningEvidenceRoleV1::Generator,
            2 => LearningEvidenceRoleV1::Evaluator,
            _ => return Err(Error::InvalidBinary("evidence_role")),
        };
        let trust_digest = self.digest()?;
        let scope_digest = self.digest()?;
        let objective_digest = self.digest()?;
        let authority_epoch = self.u64()?;
        let issued_at = self.u64()?;
        let expires_at = self.u64()?;
        let payload_digest = self.digest()?;
        let mut signature = [0; 64];
        signature.copy_from_slice(self.bytes(/*count*/ 64)?);
        Ok(SignedLearningEvidenceV1 {
            evidence_id,
            principal_id,
            role,
            trust_digest,
            scope_digest,
            objective_digest,
            authority_epoch,
            issued_at,
            expires_at,
            payload_digest,
            signature,
        })
    }
}
