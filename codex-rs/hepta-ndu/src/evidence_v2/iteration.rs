use codex_hepta_types::{
    AuthorityPosture, Digest32, Generation, Revision, StableId,
};

use crate::{
    bind_solver_iteration_receipt_v1, NduIterationContextV1,
    NduIterationReceiptV1, NduSolverIterationReceipt, SubjectClass,
};

use super::{push_id, require_digest, NduEvidenceV2Error};

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
    legacy_receipt_digest: Digest32,
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
    pub const fn legacy_receipt_digest(&self) -> Digest32 {
        self.legacy_receipt_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduEvidenceV2Error> {
        validate_fields(
            &self.subject_id,
            self.objective_digest,
            self.event_digest,
            self.coefficient_digest,
            self.iteration,
            self.predecessor_revision,
            self.next_revision,
            self.residual_raw,
            self.state_digest,
            self.solve_input_digest,
            self.legacy_receipt_digest,
            self.authority,
        )?;
        let expected = digest_v2(
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
            self.legacy_receipt_digest,
        );
        if expected != self.receipt_digest {
            return Err(NduEvidenceV2Error::DigestMismatch);
        }
        Ok(())
    }
}

pub fn validate_iteration_receipt_v1(
    receipt: &NduIterationReceiptV1,
) -> Result<(), NduEvidenceV2Error> {
    validate_fields(
        &receipt.subject_id,
        receipt.objective_digest,
        receipt.event_digest,
        receipt.coefficient_digest,
        receipt.iteration,
        receipt.predecessor_revision,
        receipt.next_revision,
        receipt.residual_raw,
        receipt.state_digest,
        receipt.solve_input_digest,
        receipt.receipt_digest,
        receipt.authority,
    )?;
    let expected = digest_v1(receipt);
    if expected != receipt.receipt_digest {
        return Err(NduEvidenceV2Error::DigestMismatch);
    }
    Ok(())
}

pub fn migrate_iteration_receipt_v1(
    receipt: &NduIterationReceiptV1,
) -> Result<NduIterationReceiptV2, NduEvidenceV2Error> {
    validate_iteration_receipt_v1(receipt)?;
    let migrated = NduIterationReceiptV2 {
        subject_id: receipt.subject_id.clone(),
        subject_class: receipt.subject_class,
        objective_digest: receipt.objective_digest,
        generation: receipt.generation,
        event_digest: receipt.event_digest,
        coefficient_digest: receipt.coefficient_digest,
        iteration: receipt.iteration,
        predecessor_revision: receipt.predecessor_revision,
        next_revision: receipt.next_revision,
        residual_raw: receipt.residual_raw,
        projection_count: receipt.projection_count,
        state_digest: receipt.state_digest,
        solve_input_digest: receipt.solve_input_digest,
        legacy_receipt_digest: receipt.receipt_digest,
        receipt_digest: digest_v2(
            &receipt.subject_id,
            receipt.subject_class,
            receipt.objective_digest,
            receipt.generation,
            receipt.event_digest,
            receipt.coefficient_digest,
            receipt.iteration,
            receipt.predecessor_revision,
            receipt.next_revision,
            receipt.residual_raw,
            receipt.projection_count,
            receipt.state_digest,
            receipt.solve_input_digest,
            receipt.receipt_digest,
        ),
        authority: AuthorityPosture::DENY_ALL,
    };
    migrated.validate()?;
    Ok(migrated)
}

pub fn bind_solver_iteration_receipt_v2(
    context: &NduIterationContextV1,
    receipt: &NduSolverIterationReceipt,
) -> Result<NduIterationReceiptV2, NduEvidenceV2Error> {
    let legacy = bind_solver_iteration_receipt_v1(context, receipt)
        .map_err(|_| NduEvidenceV2Error::ContextMismatch)?;
    migrate_iteration_receipt_v1(&legacy)
}

#[allow(clippy::too_many_arguments)]
fn validate_fields(
    subject_id: &StableId,
    objective_digest: Digest32,
    event_digest: Digest32,
    coefficient_digest: Digest32,
    iteration: u32,
    predecessor_revision: Revision,
    next_revision: Revision,
    residual_raw: i64,
    state_digest: Digest32,
    solve_input_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
) -> Result<(), NduEvidenceV2Error> {
    if subject_id.as_str().is_empty() {
        return Err(NduEvidenceV2Error::InvalidReceipt);
    }
    require_digest(objective_digest, "objective")?;
    require_digest(event_digest, "event")?;
    require_digest(coefficient_digest, "coefficient")?;
    require_digest(state_digest, "state")?;
    require_digest(solve_input_digest, "solve input")?;
    require_digest(receipt_digest, "receipt")?;
    if authority != AuthorityPosture::DENY_ALL || iteration == 0 || residual_raw < 0 {
        return Err(NduEvidenceV2Error::InvalidReceipt);
    }
    let expected_next = predecessor_revision
        .next()
        .map_err(|_| NduEvidenceV2Error::InvalidReceipt)?;
    if expected_next != next_revision {
        return Err(NduEvidenceV2Error::InvalidReceipt);
    }
    Ok(())
}

fn digest_v1(receipt: &NduIterationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.iteration-receipt.v2\0".to_vec();
    push_id(&mut bytes, &receipt.subject_id);
    bytes.push(subject_class_tag(receipt.subject_class));
    bytes.extend_from_slice(receipt.objective_digest.as_array());
    bytes.extend_from_slice(&receipt.generation.get().to_be_bytes());
    bytes.extend_from_slice(receipt.event_digest.as_array());
    bytes.extend_from_slice(receipt.coefficient_digest.as_array());
    bytes.extend_from_slice(&receipt.iteration.to_be_bytes());
    bytes.extend_from_slice(&receipt.predecessor_revision.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.next_revision.get().to_be_bytes());
    bytes.extend_from_slice(&receipt.residual_raw.to_be_bytes());
    bytes.extend_from_slice(&receipt.projection_count.to_be_bytes());
    bytes.extend_from_slice(receipt.state_digest.as_array());
    bytes.extend_from_slice(receipt.solve_input_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_v2(
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
    legacy_receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.iteration-receipt.v2.sealed\0".to_vec();
    push_id(&mut bytes, subject_id);
    bytes.push(subject_class_tag(subject_class));
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
    bytes.extend_from_slice(legacy_receipt_digest.as_array());
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

const fn subject_class_tag(subject_class: SubjectClass) -> u8 {
    match subject_class {
        SubjectClass::System => 0,
        SubjectClass::Domain => 1,
        SubjectClass::Agent => 2,
        SubjectClass::Episode => 3,
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;

    use crate::{
        solve_preference_target_with_context_v1, AxisValue, PreferenceState,
    };

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    #[test]
    fn v1_validation_and_v2_migration_recompute_every_field() {
        let context = NduIterationContextV1 {
            subject_id: id("agent-a"),
            subject_class: SubjectClass::Agent,
            objective_digest: digest("objective"),
            generation: Generation::new(7).expect("generation"),
            event_digest: digest("event"),
            coefficient_digest: digest("coefficient"),
        };
        let initial = PreferenceState::genesis(
            context.subject_id.clone(),
            context.subject_class,
            vec![AxisValue {
                axis: id("quality"),
                value: FixedQ32::ZERO,
            }],
        )
        .expect("genesis");
        let (_, _, receipts) = solve_preference_target_with_context_v1(
            initial,
            vec![AxisValue {
                axis: id("quality"),
                value: FixedQ32::ONE,
            }],
            FixedQ32::from_raw(1_i64 << 30),
            &context,
        )
        .expect("solve");
        let legacy = bind_solver_iteration_receipt_v1(
            &context,
            receipts.first().expect("receipt"),
        )
        .expect("legacy binding");
        validate_iteration_receipt_v1(&legacy).expect("valid legacy");
        let migrated = migrate_iteration_receipt_v1(&legacy).expect("migration");
        migrated.validate().expect("valid v2");

        let mut corrupted = legacy;
        corrupted.residual_raw = corrupted.residual_raw.saturating_add(1);
        assert_eq!(
            validate_iteration_receipt_v1(&corrupted),
            Err(NduEvidenceV2Error::DigestMismatch)
        );
    }
}
