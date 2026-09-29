//! Production qualification ingress for V4 row-committed datasets.
//!
//! These opaque single-use inputs are the only production-facing training path.
//! V2/V3 wrappers remain compatibility surfaces. Admission verifies the exact
//! frozen ledger source set, canonical row commitment, current owner trust,
//! evaluator/observer separation, and one shared resource budget, then repeats
//! every current-owner check immediately before fitting.

use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetFreezePlanV4;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV4;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v4;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v4;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;
use std::fmt;

use crate::BudgetedTabularFitErrorV2;
use crate::OperatorAdmissionStageV1;
use crate::OperatorDatasetBindingError;
use crate::OperatorResourceBudgetV1;
use crate::OwnerDatasetFailureV1;
use crate::OwnerDatasetOperationV1;
use crate::TabularFitReceiptV2;
use crate::TabularOperatorPlanV1;
use crate::WorldModelArtifactV2;
use crate::WorldModelPlanV2;
use crate::WorldModelV2Error;
use crate::dataset_bound::row_commitment::canonical_tabular_row_semantics_v1;
use crate::dataset_bound::row_commitment::canonical_world_model_row_semantics_v1;
use crate::dataset_bound::row_commitment::tabular_row_schema_digest_v1;
use crate::dataset_bound::row_commitment::world_model_row_schema_digest_v1;
use crate::dataset_bound::verify_evidence_membership;
use crate::dataset_bound::verify_tabular_plan_binding;
use crate::fit_tabular_operator_bounded_v2;
use crate::fit_world_model_v2;

const MAX_SIGNED_ROWS_V4: usize = 4_096;

pub struct VerifiedTabularOperatorPlanV4<'a> {
    plan: TabularOperatorPlanV1,
    admission: OwnerAdmissionV4<'a>,
    budget: OperatorResourceBudgetV1,
}

pub struct VerifiedWorldModelPlanV4<'a> {
    plan: WorldModelPlanV2,
    admission: OwnerAdmissionV4<'a>,
    budget: OperatorResourceBudgetV1,
}

struct OwnerAdmissionV4<'a> {
    owner: &'a LedgerWriter,
    receipt: DatasetSnapshotReceiptV4,
    freeze_evidence: SignedLearningEvidenceV1,
    row_evidence: SignedLearningEvidenceV1,
    admitted_at: u64,
}

impl fmt::Debug for VerifiedTabularOperatorPlanV4<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedTabularOperatorPlanV4")
            .field("artifact_id", &self.plan.artifact_id)
            .field("dataset_digest", &self.plan.dataset_digest)
            .field("admitted_at", &self.admission.admitted_at)
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for VerifiedWorldModelPlanV4<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedWorldModelPlanV4")
            .field("model_id", &self.plan.model_id)
            .field("dataset_digest", &self.plan.dataset_digest)
            .field("admitted_at", &self.admission.admitted_at)
            .finish_non_exhaustive()
    }
}

impl VerifiedTabularOperatorPlanV4<'_> {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[must_use]
    pub fn dataset_receipt(&self) -> &DatasetSnapshotReceiptV4 {
        &self.admission.receipt
    }
}

impl VerifiedWorldModelPlanV4<'_> {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[must_use]
    pub fn dataset_receipt(&self) -> &DatasetSnapshotReceiptV4 {
        &self.admission.receipt
    }
}

#[allow(clippy::too_many_arguments)]
pub fn verify_tabular_operator_plan_v4<'a>(
    plan: TabularOperatorPlanV1,
    receipt: DatasetSnapshotReceiptV4,
    owner: &'a LedgerWriter,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    budget: OperatorResourceBudgetV1,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV4<'a>, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v4(&receipt, now)?;
    validate_tabular_rows(&plan, &receipt)?;
    let row_payload = tabular_training_signing_payload_v4(&plan, &receipt, owner)?;
    let admission = OwnerAdmissionV4 {
        owner,
        receipt,
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        admitted_at: now,
    };
    admission.revalidate(&row_payload, now)?;
    Ok(VerifiedTabularOperatorPlanV4 {
        plan,
        admission,
        budget,
    })
}

pub fn fit_tabular_operator_verified_v4(
    input: VerifiedTabularOperatorPlanV4<'_>,
    now: u64,
) -> Result<TabularFitReceiptV2, OperatorDatasetBindingError> {
    let row_payload = tabular_training_signing_payload_v4(
        &input.plan,
        &input.admission.receipt,
        input.admission.owner,
    )?;
    input.admission.revalidate(&row_payload, now)?;
    fit_tabular_operator_bounded_v2(input.plan, input.budget)
        .map_err(OperatorDatasetBindingError::BudgetedTabular)
}

#[allow(clippy::too_many_arguments)]
pub fn verify_world_model_plan_v4<'a>(
    plan: WorldModelPlanV2,
    receipt: DatasetSnapshotReceiptV4,
    owner: &'a LedgerWriter,
    freeze_evidence: &SignedLearningEvidenceV1,
    row_evidence: &SignedLearningEvidenceV1,
    budget: OperatorResourceBudgetV1,
    now: u64,
) -> Result<VerifiedWorldModelPlanV4<'a>, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v4(&receipt, now)?;
    validate_world_model_rows(&plan, &receipt)?;
    let row_payload = world_model_training_signing_payload_v4(&plan, &receipt, owner)?;
    let admission = OwnerAdmissionV4 {
        owner,
        receipt,
        freeze_evidence: freeze_evidence.clone(),
        row_evidence: row_evidence.clone(),
        admitted_at: now,
    };
    admission.revalidate(&row_payload, now)?;
    Ok(VerifiedWorldModelPlanV4 {
        plan,
        admission,
        budget,
    })
}

pub fn fit_world_model_verified_v4(
    input: VerifiedWorldModelPlanV4<'_>,
    now: u64,
) -> Result<WorldModelArtifactV2, OperatorDatasetBindingError> {
    let row_payload = world_model_training_signing_payload_v4(
        &input.plan,
        &input.admission.receipt,
        input.admission.owner,
    )?;
    input.admission.revalidate(&row_payload, now)?;
    fit_world_model_v2(input.plan, input.budget)
        .map_err(OperatorDatasetBindingError::WorldModelV2)
}

pub fn tabular_training_signing_payload_v4(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV4,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    validate_tabular_rows(plan, receipt)?;
    let rows = canonical_tabular_row_semantics_v1(plan, &receipt.base)?;
    owner_commitment_v4(
        b"hepta.operator.tabular-owner-rows.v4\0",
        &rows,
        receipt,
        owner,
    )
}

pub fn world_model_training_signing_payload_v4(
    plan: &WorldModelPlanV2,
    receipt: &DatasetSnapshotReceiptV4,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    validate_world_model_rows(plan, receipt)?;
    let rows = canonical_world_model_row_semantics_v1(
        &plan.model_id,
        &plan.samples,
        &receipt.base,
    )?;
    owner_commitment_v4(
        b"hepta.operator.world-owner-rows.v4\0",
        &rows,
        receipt,
        owner,
    )
}

fn validate_tabular_rows(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV4,
) -> Result<(), OperatorDatasetBindingError> {
    if plan.samples.is_empty()
        || plan.samples.len() > MAX_SIGNED_ROWS_V4
        || receipt.base.snapshot.source_record_digests.len() > MAX_SIGNED_ROWS_V4
        || usize::try_from(receipt.rows.row_count).ok() != Some(plan.samples.len())
        || receipt.rows.row_schema_digest != tabular_row_schema_digest_v1()
        || receipt.rows.training_profile_digest != plan.training_profile_digest
    {
        return Err(OperatorDatasetBindingError::Bounds);
    }
    verify_tabular_plan_binding(plan, &receipt.base)?;
    let rows = canonical_tabular_row_semantics_v1(plan, &receipt.base)?;
    if Digest32::of_bytes(&rows) != receipt.rows.row_commitment_root {
        return Err(OperatorDatasetBindingError::RowCommitmentMismatch);
    }
    let required = plan
        .sensor_ids
        .len()
        .checked_mul(plan.action_ids.len())
        .and_then(|cells| cells.checked_mul(plan.minimum_samples_per_cell))
        .ok_or(OperatorDatasetBindingError::Arithmetic)?;
    if required > plan.samples.len() || required > MAX_SIGNED_ROWS_V4 {
        return Err(OperatorDatasetBindingError::Bounds);
    }
    Ok(())
}

fn validate_world_model_rows(
    plan: &WorldModelPlanV2,
    receipt: &DatasetSnapshotReceiptV4,
) -> Result<(), OperatorDatasetBindingError> {
    if plan.samples.is_empty()
        || plan.samples.len() > MAX_SIGNED_ROWS_V4
        || receipt.base.snapshot.source_record_digests.len() > MAX_SIGNED_ROWS_V4
        || usize::try_from(receipt.rows.row_count).ok() != Some(plan.samples.len())
        || receipt.rows.row_schema_digest != world_model_row_schema_digest_v1()
        || receipt.rows.training_profile_digest != plan.training_profile_digest
        || receipt.base.snapshot.dataset_digest != plan.dataset_digest
        || receipt.base.snapshot.objective_digest != plan.objective_digest
        || receipt.rows.row_commitment_root != plan.row_commitment_root
    {
        return Err(OperatorDatasetBindingError::Bounds);
    }
    verify_evidence_membership(
        &receipt.base.snapshot.source_record_digests,
        plan.samples.iter().map(|row| row.evidence_digest),
    )?;
    let rows = canonical_world_model_row_semantics_v1(
        &plan.model_id,
        &plan.samples,
        &receipt.base,
    )?;
    if Digest32::of_bytes(&rows) != receipt.rows.row_commitment_root {
        return Err(OperatorDatasetBindingError::RowCommitmentMismatch);
    }
    Ok(())
}

fn owner_commitment_v4(
    domain: &[u8],
    rows: &[u8],
    receipt: &DatasetSnapshotReceiptV4,
    owner: &LedgerWriter,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    let verifier = owner.verifier();
    if verifier.objective_digest() != receipt.base.snapshot.objective_digest
        || verifier.scope_digest() != receipt.base.producer.scope_digest
        || verifier.authority_epoch() != receipt.base.producer.authority_epoch
    {
        return Err(OperatorDatasetBindingError::TrustContextMismatch);
    }
    let mut payload = domain.to_vec();
    for digest in [
        Digest32::of_bytes(rows),
        receipt.receipt_digest,
        receipt.rows.row_schema_digest,
        receipt.rows.row_commitment_root,
        receipt.rows.training_profile_digest,
        receipt.base.snapshot.dataset_digest,
        receipt.base.snapshot.ledger_head_digest,
        verifier.trust_digest(),
        owner.trust_distribution_digest(),
        verifier.scope_digest(),
        verifier.objective_digest(),
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    payload.extend_from_slice(&receipt.rows.row_count.to_be_bytes());
    payload.extend_from_slice(&receipt.issued_at.to_be_bytes());
    payload.extend_from_slice(&receipt.expires_at.to_be_bytes());
    payload.extend_from_slice(&owner.trust_generation().to_be_bytes());
    payload.extend_from_slice(&verifier.authority_epoch().to_be_bytes());
    Ok(payload)
}

impl OwnerAdmissionV4<'_> {
    fn revalidate(
        &self,
        row_payload: &[u8],
        now: u64,
    ) -> Result<(), OperatorDatasetBindingError> {
        if now < self.admitted_at {
            return Err(OperatorDatasetBindingError::ClockRegression);
        }
        let plan = DatasetFreezePlanV4 {
            base: DatasetFreezePlanV2 {
                snapshot_id: self.receipt.base.snapshot.snapshot_id.clone(),
                objective_digest: self.receipt.base.snapshot.objective_digest,
                inclusion_policy_digest: self.receipt.base.inclusion_policy_digest,
            },
            rows: self.receipt.rows.clone(),
            expires_at: self.receipt.expires_at,
        };
        let expected = self
            .owner
            .freeze_dataset_v4(plan.clone(), &self.freeze_evidence, now)
            .map_err(|error| owner_failure_v4(OwnerDatasetOperationV1::FreezeDatasetV4, error))?;
        if expected != self.receipt {
            return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
        }
        self.owner
            .read_dataset_records_v4(&self.receipt, now)
            .map_err(|error| {
                owner_failure_v4(OwnerDatasetOperationV1::ReadDatasetRecordsV4, error)
            })?;
        let snapshot = self
            .owner
            .snapshot()
            .map_err(|error| owner_failure_v4(OwnerDatasetOperationV1::Snapshot, error))?;
        let freeze_payload = dataset_freeze_signing_payload_v4(&snapshot, &plan).map_err(|error| {
            owner_failure_v4(OwnerDatasetOperationV1::EncodeFreezePayloadV4, error)
        })?;
        let verifier = self.owner.verifier();
        let evaluator = verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.freeze_evidence,
            &freeze_payload,
            now,
        )?;
        let observer = verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &self.row_evidence,
            row_payload,
            now,
        )?;
        verify_signed_independent_roles_v1(&evaluator, &observer, now)?;
        Ok(())
    }
}

fn owner_failure_v4(
    operation: OwnerDatasetOperationV1,
    error: impl fmt::Display,
) -> OperatorDatasetBindingError {
    OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {
        operation,
        message: error.to_string(),
    })
}

// Keep these imports visibly coupled to the unified error surface. They are
// used by downstream exhaustive matches and by the schema/doc checker.
const _: fn(BudgetedTabularFitErrorV2) -> OperatorDatasetBindingError =
    OperatorDatasetBindingError::BudgetedTabular;
const _: fn(WorldModelV2Error) -> OperatorDatasetBindingError =
    OperatorDatasetBindingError::WorldModelV2;
