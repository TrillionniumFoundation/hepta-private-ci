//! Runtime-local next-generation adoption for independently selected learning artifacts.
//!
//! Selection is consumed, never minted, by control.runtime. Adoption changes only
//! the active local artifact generation; it does not merge source, promote a
//! deployment or issue effect authority. One rollback checkpoint is retained
//! until the host explicitly confirms the adopted generation.

use codex_hepta_intelligence_eval::SelfEvolutionSelectionReceiptV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
struct RollbackCheckpointV1 {
    candidate_id: StableId,
    generation: Generation,
    artifact_digest: Digest32,
    selection_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionRuntimeV1 {
    active_candidate_id: StableId,
    generation: Generation,
    artifact_digest: Digest32,
    rollback: Option<RollbackCheckpointV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionAdoptionReceiptV1 {
    pub predecessor_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_id: StableId,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub adoption_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfEvolutionRollbackReceiptV1 {
    pub rejected_candidate_id: StableId,
    pub restored_candidate_id: StableId,
    pub restored_generation: Generation,
    pub restored_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub regression_evidence_digest: Digest32,
    pub rollback_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfEvolutionRuntimeError {
    EmptyDigest,
    SelectionAuthority,
    PredecessorMismatch,
    GenerationMismatch,
    AdoptionPending,
    NoRollbackCheckpoint,
    SelectionMismatch,
}

impl std::fmt::Display for SelfEvolutionRuntimeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for SelfEvolutionRuntimeError {}

impl SelfEvolutionRuntimeV1 {
    pub fn new(
        active_candidate_id: StableId,
        generation: Generation,
        artifact_digest: Digest32,
    ) -> Result<Self, SelfEvolutionRuntimeError> {
        require_digest(artifact_digest)?;
        Ok(Self {
            active_candidate_id,
            generation,
            artifact_digest,
            rollback: None,
        })
    }

    pub fn active_candidate_id(&self) -> &StableId {
        &self.active_candidate_id
    }

    pub fn generation(&self) -> Generation {
        self.generation
    }

    pub fn artifact_digest(&self) -> Digest32 {
        self.artifact_digest
    }

    pub fn adoption_pending_confirmation(&self) -> bool {
        self.rollback.is_some()
    }

    /// Stage exactly one independently selected successor. The prior generation
    /// remains available as a bounded rollback checkpoint until confirmation.
    pub fn adopt(
        &mut self,
        selection: &SelfEvolutionSelectionReceiptV1,
    ) -> Result<SelfEvolutionAdoptionReceiptV1, SelfEvolutionRuntimeError> {
        if selection.authority != AuthorityPosture::DENY_ALL {
            return Err(SelfEvolutionRuntimeError::SelectionAuthority);
        }
        if self.rollback.is_some() {
            return Err(SelfEvolutionRuntimeError::AdoptionPending);
        }
        if self.active_candidate_id != selection.predecessor_id
            || self.generation != selection.predecessor_generation
        {
            return Err(SelfEvolutionRuntimeError::PredecessorMismatch);
        }
        if self.generation.next().ok() != Some(selection.candidate_generation) {
            return Err(SelfEvolutionRuntimeError::GenerationMismatch);
        }
        for digest in [
            selection.candidate_artifact_digest,
            selection.rollback_digest,
            selection.selection_digest,
        ] {
            require_digest(digest)?;
        }

        let checkpoint = RollbackCheckpointV1 {
            candidate_id: self.active_candidate_id.clone(),
            generation: self.generation,
            artifact_digest: self.artifact_digest,
            selection_digest: selection.selection_digest,
        };
        let receipt = SelfEvolutionAdoptionReceiptV1 {
            predecessor_id: checkpoint.candidate_id.clone(),
            predecessor_generation: checkpoint.generation,
            candidate_id: selection.candidate_id.clone(),
            candidate_generation: selection.candidate_generation,
            candidate_artifact_digest: selection.candidate_artifact_digest,
            selection_digest: selection.selection_digest,
            adoption_digest: adoption_digest(selection, checkpoint.artifact_digest),
            authority: AuthorityPosture::DENY_ALL,
        };
        self.active_candidate_id = selection.candidate_id.clone();
        self.generation = selection.candidate_generation;
        self.artifact_digest = selection.candidate_artifact_digest;
        self.rollback = Some(checkpoint);
        Ok(receipt)
    }

    /// Confirm the canaried/adopted generation locally and discard the one-step
    /// rollback checkpoint. Promotion/release remains a separate external gate.
    pub fn confirm_adoption(
        &mut self,
        selection_digest: Digest32,
    ) -> Result<(), SelfEvolutionRuntimeError> {
        let checkpoint = self
            .rollback
            .as_ref()
            .ok_or(SelfEvolutionRuntimeError::NoRollbackCheckpoint)?;
        if checkpoint.selection_digest != selection_digest {
            return Err(SelfEvolutionRuntimeError::SelectionMismatch);
        }
        self.rollback = None;
        Ok(())
    }

    /// Restore the exact predecessor after independently observed regression.
    /// A non-zero regression digest is mandatory so rollback cannot be used as
    /// an unrecorded arbitrary generation switch.
    pub fn rollback(
        &mut self,
        selection: &SelfEvolutionSelectionReceiptV1,
        regression_evidence_digest: Digest32,
    ) -> Result<SelfEvolutionRollbackReceiptV1, SelfEvolutionRuntimeError> {
        require_digest(regression_evidence_digest)?;
        let checkpoint = self
            .rollback
            .take()
            .ok_or(SelfEvolutionRuntimeError::NoRollbackCheckpoint)?;
        if checkpoint.selection_digest != selection.selection_digest
            || self.active_candidate_id != selection.candidate_id
            || self.generation != selection.candidate_generation
        {
            self.rollback = Some(checkpoint);
            return Err(SelfEvolutionRuntimeError::SelectionMismatch);
        }
        let mut bytes = b"hepta.control.self-evolution-rollback.v1".to_vec();
        push_id(&mut bytes, &self.active_candidate_id);
        push_id(&mut bytes, &checkpoint.candidate_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&checkpoint.generation.get().to_be_bytes());
        bytes.extend_from_slice(selection.selection_digest.as_array());
        bytes.extend_from_slice(selection.rollback_digest.as_array());
        bytes.extend_from_slice(regression_evidence_digest.as_array());
        let receipt = SelfEvolutionRollbackReceiptV1 {
            rejected_candidate_id: self.active_candidate_id.clone(),
            restored_candidate_id: checkpoint.candidate_id.clone(),
            restored_generation: checkpoint.generation,
            restored_artifact_digest: checkpoint.artifact_digest,
            selection_digest: selection.selection_digest,
            regression_evidence_digest,
            rollback_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        };
        self.active_candidate_id = checkpoint.candidate_id;
        self.generation = checkpoint.generation;
        self.artifact_digest = checkpoint.artifact_digest;
        Ok(receipt)
    }
}

fn adoption_digest(selection: &SelfEvolutionSelectionReceiptV1, predecessor: Digest32) -> Digest32 {
    let mut bytes = b"hepta.control.self-evolution-adoption.v1".to_vec();
    push_id(&mut bytes, &selection.predecessor_id);
    push_id(&mut bytes, &selection.candidate_id);
    bytes.extend_from_slice(&selection.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&selection.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(selection.candidate_artifact_digest.as_array());
    bytes.extend_from_slice(selection.selection_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn require_digest(digest: Digest32) -> Result<(), SelfEvolutionRuntimeError> {
    if digest.is_zero() {
        Err(SelfEvolutionRuntimeError::EmptyDigest)
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
