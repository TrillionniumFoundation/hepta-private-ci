//! Canonical identities for frozen definitions, scopes and semantic requests.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::SparseCheckpoint;
use crate::canonical_feature_vector_digest_v1;
use crate::cell_types::*;

impl CellScopeV1 {
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell.scope.v1".to_vec();
        for id in [&self.agent_id, &self.cell_id, &self.run_id] {
            push_id(&mut bytes, id);
        }
        bytes.extend_from_slice(self.principal_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

impl CellDefinitionV1 {
    /// V2 binds the host-registered training allowlist as well as runtime pins.
    /// A V1 owner/journal requires explicit admission of the new definition;
    /// missing policy must never be inferred from a caller's update mask.
    pub fn semantic_digest(&self) -> Result<Digest32, CellExecutionError> {
        self.runtime
            .validate_native(&self.native)
            .map_err(|_| CellExecutionError::InvalidDefinition)?;
        if self.bundle_digest.is_zero()
            || self.state_schema_digest.is_zero()
            || !(1..=65_536).contains(&self.max_input_bytes)
            || self.max_queue_age_micros == 0
            || self.max_resident_bytes == 0
            || self.candidates.is_empty()
            || self.candidates.len() > 256
            || self.trainable_parameters.len() > MAX_CELL_TRAINABLE_PARAMETERS
        {
            return Err(CellExecutionError::InvalidDefinition);
        }
        let mut ids = BTreeSet::new();
        let mut indices = BTreeSet::new();
        let mut abstain_count = 0;
        let mut bytes = b"hepta.cell.definition.v2".to_vec();
        for id in [
            &self.cell_id,
            &self.runtime.config_id,
            &self.runtime.model_id,
        ] {
            push_id(&mut bytes, id);
        }
        let r = &self.runtime;
        for digest in [self.bundle_digest, self.state_schema_digest]
            .into_iter()
            .chain(r.compatibility_digests())
        {
            bytes.extend_from_slice(digest.as_array());
        }
        for number in r.compatibility_numbers().into_iter().chain([
            self.max_input_bytes as u64,
            self.max_queue_age_micros,
            self.max_resident_bytes,
            self.candidates.len() as u64,
        ]) {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for candidate in &self.candidates {
            if candidate.activation_index >= r.state_width
                || !ids.insert(candidate.candidate_id.as_str())
                || !indices.insert(candidate.activation_index)
            {
                return Err(CellExecutionError::InvalidDefinition);
            }
            let kind = match candidate.kind {
                CellCandidateKindV1::Action => 0,
                CellCandidateKindV1::Abstain => {
                    abstain_count += 1;
                    1
                }
                CellCandidateKindV1::SlowPath => 2,
            };
            push_id(&mut bytes, &candidate.candidate_id);
            bytes.extend_from_slice(&(candidate.activation_index as u64).to_be_bytes());
            bytes.push(kind);
        }
        if abstain_count != 1 {
            return Err(CellExecutionError::InvalidDefinition);
        }
        let mut trainable = BTreeSet::new();
        bytes.extend_from_slice(b"hepta.cell.training-policy.v1");
        bytes.extend_from_slice(&(self.trainable_parameters.len() as u64).to_be_bytes());
        for parameter in &self.trainable_parameters {
            if !trainable.insert(parameter) {
                return Err(CellExecutionError::InvalidDefinition);
            }
            push_id(&mut bytes, parameter);
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub(crate) fn operation_digest(
    definition_digest: Digest32,
    snapshot: &CellOwnerSnapshotV1,
    input: &CellStepInputV1,
    encoded: &CellEncodedInputV1,
) -> Digest32 {
    let mut bytes = b"hepta.cell.operation.v1".to_vec();
    push_id(&mut bytes, &input.operation_id);
    for digest in [
        definition_digest,
        input.scope.digest(),
        input.source_frontier,
        input.objective_digest,
        input.ndu_snapshot_digest,
        snapshot
            .checkpoint
            .as_ref()
            .map_or(Digest32::ZERO, SparseCheckpoint::digest),
        Digest32::of_bytes(&input.observation),
        canonical_feature_vector_digest_v1(&encoded.feature_vector_q24),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for number in [
        snapshot.writer_epoch,
        snapshot.revision,
        input.monotonic_micros,
        input.deadline_micros,
        encoded.consumed_bytes as u64,
        encoded.truncated_bytes as u64,
    ] {
        bytes.extend_from_slice(&number.to_be_bytes());
    }
    for candidate in &input.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.allowed));
    }
    Digest32::of_bytes(&bytes)
}

/// Bind an external operation to its complete frozen definition and semantic
/// input, without including the current owner revision or checkpoint.
pub fn canonical_cell_step_request_digest_v1(
    definition: &CellDefinitionV1,
    input: &CellStepInputV1,
) -> Result<Digest32, CellExecutionError> {
    Ok(semantic_request_digest(
        definition.semantic_digest()?,
        input,
    ))
}

/// Independent of the owner revision: retries cannot acquire new execution
/// semantics just because a prior commit advanced temporal state.
pub(crate) fn semantic_request_digest(
    definition_digest: Digest32,
    input: &CellStepInputV1,
) -> Digest32 {
    let mut bytes = b"hepta.cell.semantic-request.v1".to_vec();
    push_id(&mut bytes, &input.operation_id);
    for digest in [
        definition_digest,
        input.scope.digest(),
        input.source_frontier,
        input.objective_digest,
        input.ndu_snapshot_digest,
        Digest32::of_bytes(&input.observation),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&input.monotonic_micros.to_be_bytes());
    bytes.extend_from_slice(&input.deadline_micros.to_be_bytes());
    bytes.extend_from_slice(&(input.candidates.len() as u64).to_be_bytes());
    for candidate in &input.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.allowed));
    }
    Digest32::of_bytes(&bytes)
}

/// Inference.control owns a shared request ledger. The same operation label in
/// different Cell partitions must not collide; a changed snapshot within one
/// operation must not mint a second request ID to bypass that ledger.
pub(crate) fn inference_request_id(
    scope: &CellScopeV1,
    operation_id: &StableId,
) -> Result<StableId, CellExecutionError> {
    let mut bytes = b"hepta.cell.inference-request-id.v1".to_vec();
    bytes.extend_from_slice(scope.digest().as_array());
    push_id(&mut bytes, operation_id);
    let digest = Digest32::of_bytes(&bytes);
    StableId::new(format!("cell-infer:{digest}")).map_err(|_| CellExecutionError::InvalidInput)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
