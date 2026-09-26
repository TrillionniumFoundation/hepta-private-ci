use super::MAX_ITERATIONS;
use crate::NduError;
use crate::SubjectClass;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

/// Local deterministic solver step. This is not the canonical
/// `NduIterationReceiptV1` unless the complete context was frozen before the
/// first numerical update. Legacy context-free steps cannot be exported as
/// source-bound protocol receipts.
/// Fields are intentionally private so callers cannot fabricate canonical-
/// looking state-machine evidence without going through the solver.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSolverIterationReceipt {
    pub(super) subject_id: StableId,
    pub(super) subject_class: SubjectClass,
    pub(super) iteration: u32,
    pub(super) predecessor_revision: Revision,
    pub(super) next_revision: Revision,
    pub(super) residual_raw: i64,
    pub(super) projection_count: u32,
    pub(super) state_digest: Digest32,
    pub(super) source: Option<SolverSourceV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct SolverSourceV1 {
    pub(super) context_digest: Digest32,
    pub(super) input_digest: Digest32,
}

impl NduSolverIterationReceipt {
    pub(crate) fn source_context_digest(&self) -> Option<Digest32> {
        self.source.map(|source| source.context_digest)
    }

    pub(crate) fn solve_input_digest(&self) -> Option<Digest32> {
        self.source.map(|source| source.input_digest)
    }

    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    #[must_use]
    pub const fn subject_class(&self) -> SubjectClass {
        self.subject_class
    }

    #[must_use]
    pub const fn iteration(&self) -> u32 {
        self.iteration
    }

    #[must_use]
    pub const fn predecessor_revision(&self) -> Revision {
        self.predecessor_revision
    }

    #[must_use]
    pub const fn next_revision(&self) -> Revision {
        self.next_revision
    }

    #[must_use]
    pub const fn residual_raw(&self) -> i64 {
        self.residual_raw
    }

    #[must_use]
    pub const fn projection_count(&self) -> u32 {
        self.projection_count
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    pub(crate) fn validate(&self) -> Result<(), NduError> {
        if !(1..=MAX_ITERATIONS).contains(&self.iteration) {
            return Err(NduError::InvalidSolverReceipt("iteration"));
        }
        let expected_next = self
            .predecessor_revision
            .next()
            .map_err(|_| NduError::InvalidSolverReceipt("predecessor revision"))?;
        if self.next_revision != expected_next {
            return Err(NduError::InvalidSolverReceipt("revision adjacency"));
        }
        if self.residual_raw < 0 {
            return Err(NduError::InvalidSolverReceipt("negative residual"));
        }
        if self.state_digest.is_zero() {
            return Err(NduError::InvalidSolverReceipt("state digest"));
        }
        Ok(())
    }
}
