//! Dataset-bound operator admission.
//!
//! The V2 compatibility APIs only bind caller supplied rows to a self-verifying
//! dataset receipt. Production qualification must use the V3 APIs: they rebind
//! the receipt to an authoritative replayed ledger, verify a host-owned trust
//! snapshot and Ed25519 row-semantics attestation, and only then construct an
//! opaque input that can reach the trainer.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::StrictLearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularWorldModelV1;
use crate::WorldModelError;
use crate::WorldModelSampleV1;
use crate::fit_tabular_operator_strict_v2;
use crate::fit_transition_model;

/// V2 compatibility proof. It validates receipt structure and evidence-set
/// equality, but does not rebind to a current ledger or authenticate row
/// semantics. New production code must use `VerifiedTabularOperatorPlanV3`.
#[derive(Clone, Debug)]
pub struct VerifiedTabularOperatorPlanV2 {
    plan: TabularOperatorPlanV1,
}

/// Production admission proof. Only `verify_tabular_operator_plan_v3` can
/// construct this value; callers cannot pass an ordinary plan into the V3 fit.
#[derive(Clone, Debug)]
pub struct VerifiedTabularOperatorPlanV3 {
    plan: TabularOperatorPlanV1,
    ledger_head_digest: Digest32,
    trust_digest: Digest32,
    row_semantics_digest: Digest32,
}

impl VerifiedTabularOperatorPlanV3 {
    #[must_use]
    pub const fn ledger_head_digest(&self) -> Digest32 {
        self.ledger_head_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn row_semantics_digest(&self) -> Digest32 {
        self.row_semantics_digest
    }
}

/// V2 compatibility proof for world-model rows.
#[derive(Clone, Debug)]
pub struct VerifiedWorldModelDatasetV2 {
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
}

/// Production proof for world-model rows, bound to the current ledger and a
/// host-authorized signed row-semantics payload.
#[derive(Clone, Debug)]
pub struct VerifiedWorldModelDatasetV3 {
    model_id: StableId,
    dataset_digest: Digest32,
    samples: Vec<WorldModelSampleV1>,
    ledger_head_digest: Digest32,
    trust_digest: Digest32,
    row_semantics_digest: Digest32,
}

impl VerifiedWorldModelDatasetV3 {
    #[must_use]
    pub const fn ledger_head_digest(&self) -> Digest32 {
        self.ledger_head_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn row_semantics_digest(&self) -> Digest32 {
        self.row_semantics_digest
    }
}

pub fn verify_tabular_operator_plan_v2(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV2, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    verify_tabular_plan_binding(&plan, receipt)?;
    Ok(VerifiedTabularOperatorPlanV2 { plan })
}

/// Production dataset admission.
///
/// `verifier` must be created from immutable host-owned trust state. The signed
/// evidence must have the `Observer` role and sign the canonical row payload
/// returned by `canonical_tabular_row_semantics_v1`; consequently changing a
/// target, sensor, action, sample identity, evidence digest or dataset/ledger
/// binding invalidates admission.
pub fn verify_tabular_operator_plan_v3(
    plan: TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    verifier: &LearningEvidenceVerifierV1,
    signed_row_semantics: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedTabularOperatorPlanV3, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_against_ledger_v3(receipt, ledger_snapshot, now)?;
    verify_tabular_plan_binding(&plan, receipt)?;
    verify_trust_context(verifier, receipt)?;
    let payload = canonical_tabular_row_semantics_v1(&plan, receipt)?;
    let verified = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        signed_row_semantics,
        &payload,
        now,
    )?;
    if verified.objective_digest() != plan.objective_digest {
        return Err(OperatorDatasetBindingError::TrustContextMismatch);
    }
    Ok(VerifiedTabularOperatorPlanV3 {
        plan,
        ledger_head_digest: receipt.snapshot.ledger_head_digest,
        trust_digest: verified.trust_digest(),
        row_semantics_digest: verified.payload_digest(),
    })
}

pub fn fit_tabular_operator_verified_v2(
    verified: VerifiedTabularOperatorPlanV2,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    fit_tabular_operator_strict_v2(verified.plan).map_err(OperatorDatasetBindingError::Learned)
}

/// The production trainer only accepts the opaque V3 admission proof.
pub fn fit_tabular_operator_verified_v3(
    verified: VerifiedTabularOperatorPlanV3,
) -> Result<TabularOperatorArtifactV1, OperatorDatasetBindingError> {
    fit_tabular_operator_strict_v2(verified.plan).map_err(OperatorDatasetBindingError::Learned)
}

pub fn verify_world_model_dataset_v2(
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV2, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        samples.iter().map(|sample| sample.evidence_digest),
    )?;
    Ok(VerifiedWorldModelDatasetV2 {
        model_id,
        dataset_digest: receipt.snapshot.dataset_digest,
        samples,
    })
}

pub fn verify_world_model_dataset_v3(
    model_id: StableId,
    samples: Vec<WorldModelSampleV1>,
    receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    verifier: &LearningEvidenceVerifierV1,
    signed_row_semantics: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<VerifiedWorldModelDatasetV3, OperatorDatasetBindingError> {
    verify_dataset_snapshot_receipt_against_ledger_v3(receipt, ledger_snapshot, now)?;
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        samples.iter().map(|sample| sample.evidence_digest),
    )?;
    verify_trust_context(verifier, receipt)?;
    let payload = canonical_world_model_row_semantics_v1(&model_id, &samples, receipt)?;
    let verified = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        signed_row_semantics,
        &payload,
        now,
    )?;
    Ok(VerifiedWorldModelDatasetV3 {
        model_id,
        dataset_digest: receipt.snapshot.dataset_digest,
        samples,
        ledger_head_digest: receipt.snapshot.ledger_head_digest,
        trust_digest: verified.trust_digest(),
        row_semantics_digest: verified.payload_digest(),
    })
}

pub fn fit_transition_model_verified_v2(
    verified: VerifiedWorldModelDatasetV2,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    fit_transition_model(verified.model_id, verified.dataset_digest, verified.samples)
        .map_err(OperatorDatasetBindingError::WorldModel)
}

pub fn fit_transition_model_verified_v3(
    verified: VerifiedWorldModelDatasetV3,
) -> Result<TabularWorldModelV1, OperatorDatasetBindingError> {
    fit_transition_model(verified.model_id, verified.dataset_digest, verified.samples)
        .map_err(OperatorDatasetBindingError::WorldModel)
}

fn verify_tabular_plan_binding(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<(), OperatorDatasetBindingError> {
    if plan.dataset_digest != receipt.snapshot.dataset_digest {
        return Err(OperatorDatasetBindingError::DatasetDigestMismatch);
    }
    if plan.objective_digest != receipt.snapshot.objective_digest {
        return Err(OperatorDatasetBindingError::ObjectiveDigestMismatch);
    }
    verify_evidence_membership(
        &receipt.snapshot.source_record_digests,
        plan.samples.iter().map(|sample| sample.evidence_digest),
    )
}

fn verify_trust_context(
    verifier: &LearningEvidenceVerifierV1,
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<(), OperatorDatasetBindingError> {
    if verifier.objective_digest() != receipt.snapshot.objective_digest
        || verifier.scope_digest() != receipt.producer.scope_digest
        || verifier.authority_epoch() != receipt.producer.authority_epoch
    {
        return Err(OperatorDatasetBindingError::TrustContextMismatch);
    }
    Ok(())
}

/// Canonical bytes that a trusted observer signs to attest the complete
/// semantics of every tabular training row and its frozen dataset context.
fn canonical_tabular_row_semantics_v1(
    plan: &TabularOperatorPlanV1,
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    let mut rows = plan.samples.iter().collect::<Vec<_>>();
    rows.sort_by_key(|sample| sample.sample_id.clone());
    let mut bytes = b"hepta.bellman-operator.verified-tabular-rows.v1".to_vec();
    push_id(&mut bytes, &plan.artifact_id)?;
    push_id(&mut bytes, &plan.producer_id)?;
    bytes.extend_from_slice(&plan.generation.get().to_be_bytes());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.sensor_core_digest,
        plan.training_profile_digest,
        receipt.snapshot.ledger_head_digest,
        receipt.correction_cut_digest,
        receipt.revocation_cut_digest,
        receipt.inclusion_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(rows.len())
            .map_err(|_| OperatorDatasetBindingError::Arithmetic)?
            .to_be_bytes(),
    );
    for row in rows {
        push_id(&mut bytes, &row.sample_id)?;
        push_id(&mut bytes, &row.sensor_id)?;
        push_id(&mut bytes, &row.action_id)?;
        bytes.extend_from_slice(&row.target.raw().to_be_bytes());
        bytes.extend_from_slice(row.evidence_digest.as_array());
    }
    Ok(bytes)
}

fn canonical_world_model_row_semantics_v1(
    model_id: &StableId,
    samples: &[WorldModelSampleV1],
    receipt: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, OperatorDatasetBindingError> {
    let mut rows = samples.iter().collect::<Vec<_>>();
    rows.sort_by_key(|sample| sample.sample_id.clone());
    let mut bytes = b"hepta.bellman-operator.verified-world-model-rows.v1".to_vec();
    push_id(&mut bytes, model_id)?;
    for digest in [
        receipt.snapshot.objective_digest,
        receipt.snapshot.dataset_digest,
        receipt.snapshot.ledger_head_digest,
        receipt.correction_cut_digest,
        receipt.revocation_cut_digest,
        receipt.inclusion_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(rows.len())
            .map_err(|_| OperatorDatasetBindingError::Arithmetic)?
            .to_be_bytes(),
    );
    for row in rows {
        push_id(&mut bytes, &row.sample_id)?;
        push_id(&mut bytes, &row.state_id)?;
        push_id(&mut bytes, &row.action_id)?;
        push_id(&mut bytes, &row.next_state_id)?;
        bytes.extend_from_slice(&row.outcome.raw().to_be_bytes());
        bytes.extend_from_slice(row.evidence_digest.as_array());
    }
    Ok(bytes)
}

fn verify_evidence_membership(
    frozen_records: &[Digest32],
    actual: impl Iterator<Item = Digest32>,
) -> Result<(), OperatorDatasetBindingError> {
    let frozen = frozen_records
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    let actual = actual.collect::<std::collections::BTreeSet<_>>();
    if actual != frozen {
        return Err(OperatorDatasetBindingError::EvidenceSetMismatch);
    }
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), OperatorDatasetBindingError> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| OperatorDatasetBindingError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetBindingError {
    DatasetReceipt(DatasetReceiptError),
    SignedEvidence(SignedEvidenceError),
    DatasetDigestMismatch,
    ObjectiveDigestMismatch,
    EvidenceSetMismatch,
    TrustContextMismatch,
    Arithmetic,
    Learned(StrictLearnedOperatorError),
    WorldModel(WorldModelError),
}

impl fmt::Display for OperatorDatasetBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorDatasetBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::DatasetReceipt(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch
            | Self::TrustContextMismatch
            | Self::Arithmetic => None,
        }
    }
}

impl From<DatasetReceiptError> for OperatorDatasetBindingError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::DatasetReceipt(value)
    }
}

impl From<SignedEvidenceError> for OperatorDatasetBindingError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::SignedEvidence(value)
    }
}

#[cfg(test)]
#[path = "dataset_bound_tests.rs"]
mod tests;
