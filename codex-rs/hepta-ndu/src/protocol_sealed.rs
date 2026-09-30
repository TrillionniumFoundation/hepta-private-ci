use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::NduError;
use crate::NduIterationContextV1;
use crate::NduIterationReceiptV1;
use crate::NduSolverIterationReceipt;
use crate::SubjectClass;
use crate::bind_solver_iteration_receipt_v1;

pub trait NduIterationReceiptV1ValidationExt {
    fn validate_complete_v1(&self) -> Result<(), NduError>;
}

impl NduIterationReceiptV1ValidationExt for NduIterationReceiptV1 {
    fn validate_complete_v1(&self) -> Result<(), NduError> {
        validate_receipt_fields(
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
            self.solve_input_digest,
            self.authority,
        )?;
        let expected = digest_receipt_fields(
            b"hepta.ndu.iteration-receipt.v2\0",
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
            self.solve_input_digest,
        );
        if expected != self.receipt_digest {
            return Err(NduError::InvalidSolverReceipt("receipt digest"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduIterationReceiptV2 {
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
    solve_input_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduIterationReceiptV2 {
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
    pub const fn solve_input_digest(&self) -> Digest32 {
        self.solve_input_digest
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
        validate_receipt_fields(
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
            self.solve_input_digest,
            self.authority,
        )?;
        let expected = digest_receipt_fields(
            b"hepta.ndu.iteration-receipt.v3\0",
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
            self.solve_input_digest,
        );
        if expected != self.receipt_digest {
            return Err(NduError::InvalidSolverReceipt("receipt digest"));
        }
        Ok(())
    }
}

pub fn bind_solver_iteration_receipt_v2(
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Result<NduIterationReceiptV2, NduError> {
    let legacy = bind_solver_iteration_receipt_v1(context, receipt)?;
    migrate_iteration_receipt_v1_to_v2(&legacy)
}

pub fn migrate_iteration_receipt_v1_to_v2(
    legacy: &NduIterationReceiptV1,
) -> Result<NduIterationReceiptV2, NduError> {
    legacy.validate_complete_v1()?;
    let receipt_digest = digest_receipt_fields(
        b"hepta.ndu.iteration-receipt.v3\0",
        &legacy.subject_id,
        legacy.subject_class,
        legacy.objective_digest,
        legacy.generation,
        legacy.event_digest,
        legacy.coefficient_digest,
        legacy.iteration,
        legacy.predecessor_revision,
        legacy.next_revision,
        legacy.residual_raw,
        legacy.projection_count,
        legacy.state_digest,
        legacy.solve_input_digest,
    );
    let migrated = NduIterationReceiptV2 {
        subject_id: legacy.subject_id.clone(),
        subject_class: legacy.subject_class,
        objective_digest: legacy.objective_digest,
        generation: legacy.generation,
        event_digest: legacy.event_digest,
        coefficient_digest: legacy.coefficient_digest,
        iteration: legacy.iteration,
        predecessor_revision: legacy.predecessor_revision,
        next_revision: legacy.next_revision,
        residual_raw: legacy.residual_raw,
        projection_count: legacy.projection_count,
        state_digest: legacy.state_digest,
        solve_input_digest: legacy.solve_input_digest,
        receipt_digest,
        authority: legacy.authority,
    };
    migrated.validate()?;
    Ok(migrated)
}

#[allow(clippy::too_many_arguments)]
fn validate_receipt_fields(
    subject_id: &StableId,
    _subject_class: SubjectClass,
    objective_digest: Digest32,
    _generation: Generation,
    event_digest: Digest32,
    coefficient_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    _projection_count: u32,
    state_digest: Digest32,
    solve_input_digest: Digest32,
    authority: AuthorityPosture,
) -> Result<(), NduError> {
    if subject_id.as_str().is_empty() {
        return Err(NduError::InvalidSolverReceipt("subject"));
    }
    for (field, digest) in [
        ("objective", objective_digest),
        ("event", event_digest),
        ("coefficient", coefficient_digest),
        ("state", state_digest),
        ("solve input", solve_input_digest),
    ] {
        if digest.is_zero() {
            return Err(NduError::EmptyProtocolDigest(field));
        }
    }
    if authority != AuthorityPosture::DENY_ALL {
        return Err(NduError::InvalidSolverReceipt("authority posture"));
    }
    if iteration == 0 || residual_raw < 0 {
        return Err(NduError::InvalidSolverReceipt("iteration payload"));
    }
    let expected_next = predecessor_revision
        .next()
        .map_err(|_| NduError::InvalidSolverReceipt("predecessor revision"))?;
    if next_revision != expected_next {
        return Err(NduError::InvalidSolverReceipt("revision adjacency"));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn digest_receipt_fields(
    domain: &[u8],
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
    solve_input_digest: Digest32,
) -> Digest32 {
    let mut bytes = domain.to_vec();
    let subject = subject_id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(subject.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(subject);
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
    bytes.extend_from_slice(solve_input_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    #![allow(clippy::expect_used)]

    use super::*;

    #[test]
    fn legacy_receipt_requires_complete_digest_recomputation() {
        let receipt = NduIterationReceiptV1 {
            subject_id: StableId::new("subject").expect("subject"),
            subject_class: SubjectClass::Agent,
            objective_digest: Digest32::of_bytes(b"objective"),
            generation: Generation::new(1).expect("generation"),
            event_digest: Digest32::of_bytes(b"event"),
            coefficient_digest: Digest32::of_bytes(b"coefficient"),
            iteration: 1,
            predecessor_revision: Revision::new(1).expect("revision"),
            next_revision: Revision::new(2).expect("revision"),
            residual_raw: 0,
            projection_count: 0,
            state_digest: Digest32::of_bytes(b"state"),
            solve_input_digest: Digest32::of_bytes(b"solve-input"),
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(receipt.validate_complete_v1().is_err());
    }
}
