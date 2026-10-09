//! Digest-only neural stage admission. A binding is never a substitute for
//! an authenticated CAS read or a durable NeuronRuntime checkpoint commit.

use codex_hepta_types::{Digest32, Generation, StableId};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronStageBindingErrorV1 {
    MissingDigest,
    MissingAuthorityEpoch,
    InvalidDeadline,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStageBindingV1 {
    pub run_id: StableId,
    pub subject_id: StableId,
    pub owner_id: StableId,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub generation: Generation,
    pub authority_epoch: u64,
    pub fence_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub ndu_snapshot_ref_digest: Digest32,
    pub context_snapshot_ref_digest: Digest32,
    pub feature_vector_digest: Digest32,
    pub predecessor_checkpoint_digest: Digest32,
    pub idempotency_digest: Digest32,
    pub deadline_ms: u64,
}

impl NeuronStageBindingV1 {
    pub fn validate(&self) -> Result<(), NeuronStageBindingErrorV1> {
        if [
            self.objective_digest,
            self.scope_digest,
            self.fence_digest,
            self.revocation_frontier_digest,
            self.model_artifact_digest,
            self.ndu_snapshot_ref_digest,
            self.context_snapshot_ref_digest,
            self.feature_vector_digest,
            self.predecessor_checkpoint_digest,
            self.idempotency_digest,
        ]
        .iter()
        .any(|d| d.is_zero())
        {
            return Err(NeuronStageBindingErrorV1::MissingDigest);
        }
        if self.authority_epoch == 0 {
            return Err(NeuronStageBindingErrorV1::MissingAuthorityEpoch);
        }
        if self.deadline_ms == 0 {
            return Err(NeuronStageBindingErrorV1::InvalidDeadline);
        }
        Ok(())
    }

    pub fn binding_digest(&self) -> Result<Digest32, NeuronStageBindingErrorV1> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.stage-ref.v1".to_vec();
        for id in [&self.run_id, &self.subject_id, &self.owner_id] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        for digest in [
            self.objective_digest,
            self.scope_digest,
            self.fence_digest,
            self.revocation_frontier_digest,
            self.model_artifact_digest,
            self.ndu_snapshot_ref_digest,
            self.context_snapshot_ref_digest,
            self.feature_vector_digest,
            self.predecessor_checkpoint_digest,
            self.idempotency_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[cfg(test)]
#[path = "stage_binding_tests.rs"]
mod tests;
