use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::NduError;
use crate::NduSolverIterationReceipt;
use crate::SubjectClass;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationContextV1 {
    pub subject_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub event_digest: Digest32,
    pub coefficient_digest: Digest32,
}

/// Owner-local native representation of the canonical readiness protocol. It
/// cannot be constructed from a local solver step without the complete frozen
/// context and always carries a deny-all authority posture. Fields are private
/// so external crates cannot fabricate validated evidence with a struct literal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationReceiptV1 {
    subject_id: StableId,
    subject_class: SubjectClass,
    objective_digest: Digest32,
    generation: Generation,
    event_digest: Digest32,
    coefficient_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduIterationReceiptV1 {
    #[must_use]
    pub fn subject_id(&self) -> &StableId {
        &self.subject_id
    }

    #[must_use]
    pub const fn subject_class(&self) -> SubjectClass {
        self.subject_class
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn event_digest(&self) -> Digest32 {
        self.event_digest
    }

    #[must_use]
    pub const fn coefficient_digest(&self) -> Digest32 {
        self.coefficient_digest
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

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduError> {
        require_digest(self.objective_digest, "objective")?;
        require_digest(self.event_digest, "event")?;
        require_digest(self.coefficient_digest, "coefficient")?;
        require_digest(self.state_digest, "state")?;
        require_digest(self.receipt_digest, "receipt")?;
        if self.authority != AuthorityPosture::DENY_ALL {
            return Err(NduError::InvalidSolverReceipt("authority posture"));
        }
        let expected_next = self
            .predecessor_revision
            .next()
            .map_err(|_| NduError::InvalidSolverReceipt("predecessor revision"))?;
        if self.next_revision != expected_next {
            return Err(NduError::InvalidSolverReceipt("revision adjacency"));
        }
        if self.iteration == 0 || self.residual_raw < 0 {
            return Err(NduError::InvalidSolverReceipt("iteration payload"));
        }
        let expected = digest_receipt_fields(
            &self.subject_id,
            self.subject_class,
            self.objective_digest,
            self.generation,
            self.event_digest,
            self.coefficient_digest,
            self.iteration,
            self.predecessor_revision,
            self.next_revision,
            self.residual_raw,
            self.projection_count,
            self.state_digest,
        );
        if expected != self.receipt_digest {
            return Err(NduError::InvalidSolverReceipt("receipt digest"));
        }
        Ok(())
    }
}

pub fn bind_solver_iteration_receipt_v1(
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Result<NduIterationReceiptV1, NduError> {
    require_digest(context.objective_digest, "objective")?;
    require_digest(context.event_digest, "event")?;
    require_digest(context.coefficient_digest, "coefficient")?;
    receipt.validate()?;
    require_digest(receipt.state_digest(), "state")?;
    if receipt.subject_id() != &context.subject_id
        || receipt.subject_class() != context.subject_class
    {
        return Err(NduError::ProtocolSubjectMismatch);
    }

    let receipt_digest = digest_receipt_fields(
        &context.subject_id,
        context.subject_class,
        context.objective_digest,
        context.generation,
        context.event_digest,
        context.coefficient_digest,
        receipt.iteration(),
        receipt.predecessor_revision(),
        receipt.next_revision(),
        receipt.residual_raw(),
        receipt.projection_count(),
        receipt.state_digest(),
    );
    let bound = NduIterationReceiptV1 {
        subject_id: context.subject_id.clone(),
        subject_class: context.subject_class,
        objective_digest: context.objective_digest,
        generation: context.generation,
        event_digest: context.event_digest,
        coefficient_digest: context.coefficient_digest,
        iteration: receipt.iteration(),
        predecessor_revision: receipt.predecessor_revision(),
        next_revision: receipt.next_revision(),
        residual_raw: receipt.residual_raw(),
        projection_count: receipt.projection_count(),
        state_digest: receipt.state_digest(),
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    bound.validate()?;
    Ok(bound)
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduError> {
    if value.is_zero() {
        return Err(NduError::EmptyProtocolDigest(field));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn digest_receipt_fields(
    subject_id: &StableId,
    subject_class: SubjectClass,
    objective_digest: Digest32,
    generation: Generation,
    event_digest: Digest32,
    coefficient_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    projection_count: u32,
    state_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.ndu.iteration-receipt.v1");
    push_id(&mut bytes, subject_id);
    bytes.push(subject_class.tag());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(event_digest.as_array());
    bytes.extend_from_slice(coefficient_digest.as_array());
    bytes.extend_from_slice(&iteration.to_be_bytes());
    bytes.extend_from_slice(&predecessor_revision.get().to_be_bytes());
    bytes.extend_from_slice(&next_revision.get().to_be_bytes());
    bytes.extend_from_slice(&residual_raw.to_be_bytes());
    bytes.extend_from_slice(&projection_count.to_be_bytes());
    bytes.extend_from_slice(state_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
