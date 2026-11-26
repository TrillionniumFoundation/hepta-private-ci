//! Read-only presign fields from the sole original candidate parser. Parsed
//! bytes grant no Generator, custody, publication or execution authority.
use super::*;

pub struct UntrustedSelfIterationCandidateV1 {
    payload_digest: Digest32,
    candidate: Candidate,
}

/// Root must independently bind every field to the admitted original round,
/// protected plans and actual native model receipt before authorizing G.
pub fn inspect_unsigned_self_iteration_candidate_v1(
    payload: &[u8],
    now_unix_ms: u64,
) -> Result<UntrustedSelfIterationCandidateV1, ProductEvaluationError> {
    if payload.is_empty() || payload.len() > MAX_SELF_ITERATION_FROZEN_CANDIDATE_BYTES {
        return Err(invalid());
    }
    Ok(UntrustedSelfIterationCandidateV1 {
        payload_digest: Digest32::of_bytes(payload),
        candidate: validate_candidate(payload, now_unix_ms)?,
    })
}

impl UntrustedSelfIterationCandidateV1 {
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }
    pub fn envelope_id(&self) -> &StableId {
        &self.candidate.ids[0]
    }
    pub fn candidate_id(&self) -> &StableId {
        &self.candidate.ids[1]
    }
    pub fn generator_id(&self) -> &StableId {
        &self.candidate.ids[2]
    }
    pub fn canary_tick_id(&self) -> &StableId {
        &self.candidate.ids[3]
    }
    pub fn baseline_id(&self) -> &StableId {
        &self.candidate.ids[4]
    }
    pub fn base_commit(&self) -> Digest32 {
        self.candidate.digests[0]
    }
    pub fn base_tree(&self) -> Digest32 {
        self.candidate.digests[1]
    }
    pub fn objective_digest(&self) -> Digest32 {
        self.candidate.digests[2]
    }
    pub fn grammar_digest(&self) -> Digest32 {
        self.candidate.digests[3]
    }
    pub fn semantic_diff_digest(&self) -> Digest32 {
        self.candidate.digests[4]
    }
    pub fn test_plan_digest(&self) -> Digest32 {
        self.candidate.digests[5]
    }
    pub fn rollback_digest(&self) -> Digest32 {
        self.candidate.digests[6]
    }
    pub fn governed_proposal_digest(&self) -> Digest32 {
        self.candidate.digests[7]
    }
    pub fn governed_anchor_digest(&self) -> Digest32 {
        self.candidate.digests[8]
    }
    pub fn governed_composition_digest(&self) -> Digest32 {
        self.candidate.digests[9]
    }
    pub fn canary_snapshot_digest(&self) -> Digest32 {
        self.candidate.digests[10]
    }
    pub fn canary_candidate_set_digest(&self) -> Digest32 {
        self.candidate.digests[11]
    }
    pub fn canary_predecessor_digest(&self) -> Digest32 {
        self.candidate.digests[12]
    }
    pub fn successor_body(&self) -> Digest32 {
        self.candidate.digests[13]
    }
    pub fn rollback_body(&self) -> Digest32 {
        self.candidate.digests[14]
    }
    pub fn successor_configuration(&self) -> Digest32 {
        self.candidate.digests[15]
    }
    pub fn rollback_configuration(&self) -> Digest32 {
        self.candidate.digests[16]
    }
    pub fn canary_input_digest(&self) -> Digest32 {
        self.candidate.digests[17]
    }
    pub fn base_generation(&self) -> u64 {
        self.candidate.values[0]
    }
    pub fn maximum_files(&self) -> u64 {
        self.candidate.values[1]
    }
    pub fn maximum_diff_bytes(&self) -> u64 {
        self.candidate.values[2]
    }
    pub fn candidate_admissions(&self) -> u64 {
        self.candidate.values[3]
    }
    pub fn maximum_parallel_sandboxes(&self) -> u64 {
        self.candidate.values[4]
    }
    pub fn expires_unix_seconds(&self) -> u64 {
        self.candidate.values[5]
    }
    pub fn changed_files(&self) -> u64 {
        self.candidate.values[6]
    }
    pub fn canary_budget_micros(&self) -> u64 {
        self.candidate.values[7]
    }
    pub fn canonical_envelope_bytes(&self) -> Option<&[u8]> {
        self.candidate.canonical_envelope.as_deref()
    }
    pub fn canonical_envelope_digest(&self) -> Option<Digest32> {
        self.canonical_envelope_bytes().map(Digest32::of_bytes)
    }
    pub fn generator_round_bytes(&self) -> Option<&[u8]> {
        self.candidate.round_bytes.as_deref()
    }
    pub fn generator_round_payload_digest(&self) -> Option<Digest32> {
        self.generator_round_bytes().map(Digest32::of_bytes)
    }
    pub fn generator_model_request_id(&self) -> Option<&StableId> {
        self.candidate.model_request.as_ref()
    }
    pub fn generator_native_run_digest(&self) -> Option<Digest32> {
        self.candidate.native_run
    }
    pub fn generator_model_output_digest(&self) -> Option<Digest32> {
        self.candidate.output_digest
    }
}
