//! Incrementally bounded V1 binary encoding of full restart preimages.

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CompactionPublicationBodyError as Error;
use super::MAX_BINARY_BYTES;
use crate::CompactionPublicationProposalV1;
use crate::CompactionSelectedStateV1;

const DOMAIN: &[u8] = b"hepta.compaction.publication-body.v1\0";

pub(super) fn encode(proposal: &CompactionPublicationProposalV1) -> Result<Vec<u8>, Error> {
    let request = proposal.request();
    let mut out = Writer(Vec::new());
    out.bytes(DOMAIN)?;
    for id in [
        &request.owner_agent_id,
        &request.scope_id,
        &request.purpose_id,
        &request.operation_id,
    ] {
        out.id(id)?;
    }
    out.u64(request.policy_generation.get())?;
    match request.expected_selected {
        CompactionSelectedStateV1::Empty => out.tag(0)?,
        CompactionSelectedStateV1::Selected {
            generation,
            checkpoint_digest,
        } => {
            out.tag(1)?;
            out.u64(generation.get())?;
            out.digest(checkpoint_digest)?;
        }
    }
    let vector = &request.candidate.source_snapshot.vector;
    out.id(&vector.scope_id)?;
    out.id(&vector.purpose_id)?;
    for value in [
        vector.memory_ledger_frontier,
        vector.knowledge_fact_frontier,
        vector.tombstone_frontier,
        vector.source_ledger_frontier,
        vector.knowledge_graph_generation.get(),
        vector.compact_checkpoint_generation.get(),
        vector.prompt_registry_revision.get(),
    ] {
        out.u64(value)?;
    }
    out.digest(vector.retrieval_profile_digest)?;
    out.digest(vector.encoder_preprocessor_digest)?;
    out.u64(vector.authority_epoch)?;
    for digest in [
        vector.model_digest,
        vector.tokenizer_digest,
        vector.template_digest,
        vector.tool_schema_digest,
    ] {
        out.digest(digest)?;
    }
    let policy = &request.policy;
    out.id(&policy.policy_id)?;
    out.digest(policy.algorithm_digest)?;
    out.digest(policy.compatibility_digest)?;
    out.u32(policy.maximum_retained_records)?;
    out.count(policy.protected_record_ids.len())?;
    for id in &policy.protected_record_ids {
        out.id(id)?;
    }
    out.count(request.inputs.len())?;
    for input in &request.inputs {
        let record = &input.record;
        out.id(&record.record_id)?;
        out.u64(record.revision.get())?;
        out.tag(match record.kind {
            MemoryKind::Episode => 0,
            MemoryKind::Fact => 1,
            MemoryKind::Preference => 2,
            MemoryKind::Procedure => 3,
        })?;
        out.tag(match record.state {
            RecordState::Live => 0,
            RecordState::Tombstone => 1,
        })?;
        out.digest(record.content_digest)?;
        match record.predecessor_digest {
            None => out.tag(0)?,
            Some(digest) => {
                out.tag(1)?;
                out.digest(digest)?;
            }
        }
        out.count(record.citations.len())?;
        for citation in &record.citations {
            out.id(&citation.source_id)?;
            out.digest(citation.source_digest)?;
        }
        out.u32(input.retention_priority)?;
        out.digest(input.retention_reason_digest)?;
    }
    let binding = request.authenticated_proof.source_binding();
    for digest in [
        binding.source_cut_digest,
        binding.scope_digest,
        binding.objective_digest,
    ] {
        out.digest(digest)?;
    }
    out.u64(binding.authority_epoch)?;
    let qualification = request.authenticated_proof.qualification();
    out.id(&qualification.evaluator_id)?;
    for digest in [
        qualification.candidate_digest,
        qualification.retained_query_suite_digest,
        qualification.reconstruction_obligation_digest,
        qualification.contradiction_holdout_digest,
    ] {
        out.digest(digest)?;
    }
    for flag in [
        qualification.retained_queries_passed,
        qualification.reconstruction_passed,
        qualification.contradictions_preserved,
        qualification.deletion_non_resurrection_passed,
    ] {
        out.tag(u8::from(flag))?;
    }
    let evidence = request.authenticated_proof.signed_evidence();
    for signed in [&evidence.generator, &evidence.evaluator] {
        out.id(&signed.evidence_id)?;
        out.id(&signed.principal_id)?;
        out.tag(match signed.role {
            LearningEvidenceRoleV1::Generator => 0,
            LearningEvidenceRoleV1::Evaluator => 2,
            LearningEvidenceRoleV1::Observer
            | LearningEvidenceRoleV1::CreditAllocator
            | LearningEvidenceRoleV1::UnlearningAuthority
            | LearningEvidenceRoleV1::Selector => {
                return Err(Error::InvalidBinary("evidence_role"));
            }
        })?;
        for digest in [
            signed.trust_digest,
            signed.scope_digest,
            signed.objective_digest,
        ] {
            out.digest(digest)?;
        }
        for value in [signed.authority_epoch, signed.issued_at, signed.expires_at] {
            out.u64(value)?;
        }
        out.digest(signed.payload_digest)?;
        out.bytes(&signed.signature)?;
    }
    for digest in [
        request.candidate.candidate_digest,
        request.candidate.checkpoint.checkpoint_digest,
        request.authenticated_proof.authentication_digest(),
        proposal.intent_digest(),
    ] {
        out.digest(digest)?;
    }
    Ok(out.0)
}

struct Writer(Vec<u8>);
impl Writer {
    fn bytes(&mut self, bytes: &[u8]) -> Result<(), Error> {
        if self
            .0
            .len()
            .checked_add(bytes.len())
            .is_none_or(|length| length > MAX_BINARY_BYTES)
        {
            return Err(Error::BodyLimitExceeded);
        }
        self.0.extend_from_slice(bytes);
        Ok(())
    }
    fn tag(&mut self, tag: u8) -> Result<(), Error> {
        self.bytes(&[tag])
    }
    fn u32(&mut self, value: u32) -> Result<(), Error> {
        self.bytes(&value.to_be_bytes())
    }
    fn u64(&mut self, value: u64) -> Result<(), Error> {
        self.bytes(&value.to_be_bytes())
    }
    fn digest(&mut self, digest: Digest32) -> Result<(), Error> {
        self.bytes(digest.as_array())
    }
    fn count(&mut self, count: usize) -> Result<(), Error> {
        self.u32(u32::try_from(count).map_err(|_| Error::BodyLimitExceeded)?)
    }
    fn id(&mut self, id: &StableId) -> Result<(), Error> {
        self.count(id.as_str().len())?;
        self.bytes(id.as_str().as_bytes())
    }
}
