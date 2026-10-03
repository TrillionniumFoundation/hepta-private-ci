//! Owner-derived terminal training. Provenance records are not training samples.
//!
//! One admitted episode contributes exactly one finalized outcome. The existing
//! terminal extractor resolves the decision/action and outcome/value from the
//! authenticated ledger. A separate observer attests that exact projection.
//! These tokens are single-use borrows, not serializable admission receipts.

use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::time::Instant;

use super::owner_terminal::fit_terminal_cell_at;
use super::owner_terminal::terminal_effective_now;

use crate::FrozenTerminalCellV1;
use crate::TabularOperatorArtifactV1;
use crate::TerminalCellError;
use crate::TerminalCellProfileV1;
use crate::freeze_terminal_cell_from_owner_v1;

/// Preparing this value reads real owner records but does not authorize fitting.
/// It exposes only canonical bytes for the independently provisioned observer.
pub struct PreparedTerminalCellV3<'a> {
    owner: &'a LedgerWriter,
    frozen: FrozenTerminalCellV1,
    profile: TerminalCellProfileV1,
    freeze_evidence: SignedLearningEvidenceV1,
    payload: Vec<u8>,
    admitted_at: u64,
}

/// Only `PreparedTerminalCellV3::verify` constructs a fit-capable value.
/// No Clone/Deserialize/public-field implementation may be added.
pub struct VerifiedTerminalCellV3<'a> {
    prepared: PreparedTerminalCellV3<'a>,
    rows: SignedLearningEvidenceV1,
}

/// Derive terminal targets and action labels from the current authenticated
/// owner. The complete dataset remains bound even though one episode contains
/// multiple provenance events. No caller-supplied numeric targets are accepted.
pub fn prepare_terminal_cell_from_owner_v3<'a>(
    owner: &'a LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    profile: TerminalCellProfileV1,
    freeze_evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<PreparedTerminalCellV3<'a>, TerminalCellError> {
    verify_freeze(owner, dataset, freeze_evidence, now)?;
    let frozen = freeze_terminal_cell_from_owner_v1(owner, dataset, profile.clone(), now)?;
    let payload = terminal_payload(owner, &frozen);
    Ok(PreparedTerminalCellV3 {
        owner,
        frozen,
        profile,
        freeze_evidence: freeze_evidence.clone(),
        payload,
        admitted_at: now,
    })
}

impl<'a> PreparedTerminalCellV3<'a> {
    pub fn signing_payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn sample_count(&self) -> usize {
        self.frozen.sample_count()
    }

    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        self.frozen.dataset()
    }

    pub fn verify(
        self,
        rows: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<VerifiedTerminalCellV3<'a>, TerminalCellError> {
        self.revalidate(rows, now)?;
        Ok(VerifiedTerminalCellV3 {
            prepared: self,
            rows: rows.clone(),
        })
    }

    fn revalidate(
        &self,
        rows: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<(VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1), TerminalCellError> {
        if now < self.admitted_at {
            return Err(TerminalCellError::Unsupported(
                "terminal V3 clock regression",
            ));
        }
        verify_freeze(
            self.owner,
            self.frozen.dataset(),
            &self.freeze_evidence,
            now,
        )?;
        let derived = freeze_terminal_cell_from_owner_v1(
            self.owner,
            self.frozen.dataset(),
            self.profile.clone(),
            now,
        )?;
        if terminal_payload(self.owner, &derived) != self.payload {
            return Err(TerminalCellError::Unsupported(
                "terminal V3 source projection changed",
            ));
        }
        let freeze_plan = freeze_plan(self.frozen.dataset());
        let snapshot = self.owner.snapshot()?;
        let freeze_payload = dataset_freeze_signing_payload_v2(&snapshot, &freeze_plan)
            .map_err(|_| TerminalCellError::Unsupported("terminal V3 freeze preimage"))?;
        let verifier = self.owner.verifier();
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &self.freeze_evidence,
                &freeze_payload,
                now,
            )
            .map_err(TerminalCellError::SignedEvidence)?;
        let observer = verifier
            .verify(LearningEvidenceRoleV1::Observer, rows, &self.payload, now)
            .map_err(TerminalCellError::SignedEvidence)?;
        verify_signed_independent_roles_v1(&evaluator, &observer, now)
            .map_err(TerminalCellError::SignedEvidence)?;
        Ok((evaluator, observer))
    }
}

/// Consumes the owner borrow and repeats all checks using the host's use time.
pub fn fit_terminal_cell_verified_v3(
    verified: VerifiedTerminalCellV3<'_>,
    now: u64,
) -> Result<TabularOperatorArtifactV1, TerminalCellError> {
    let started = Instant::now();
    fit_terminal_cell_verified_at(verified, now, || terminal_effective_now(now, &started))
}

pub(super) fn fit_terminal_cell_verified_at(
    verified: VerifiedTerminalCellV3<'_>,
    now: u64,
    mut effective_now: impl FnMut() -> Result<u64, TerminalCellError>,
) -> Result<TabularOperatorArtifactV1, TerminalCellError> {
    verified.prepared.revalidate(&verified.rows, now)?;
    let (artifact, finished_at) = fit_terminal_cell_at(
        verified.prepared.owner,
        &verified.prepared.frozen,
        now,
        &mut effective_now,
    )?;
    // Root, dataset and both signed projections must still be valid after the
    // real synchronous fit. Elapsed time never refreshes an authority witness.
    let (evaluator, observer) = verified.prepared.revalidate(&verified.rows, finished_at)?;
    let final_at = effective_now()?;
    if final_at < finished_at {
        return Err(TerminalCellError::ClockRegression);
    }
    verified.prepared.owner.revalidate_trust_at(final_at)?;
    let verifier = verified.prepared.owner.verifier();
    verifier
        .revalidate(&evaluator, final_at)
        .map_err(TerminalCellError::SignedEvidence)?;
    verifier
        .revalidate(&observer, final_at)
        .map_err(TerminalCellError::SignedEvidence)?;
    Ok(artifact)
}

fn freeze_plan(dataset: &DatasetSnapshotReceiptV3) -> DatasetFreezePlanV2 {
    DatasetFreezePlanV2 {
        snapshot_id: dataset.snapshot.snapshot_id.clone(),
        objective_digest: dataset.snapshot.objective_digest,
        inclusion_policy_digest: dataset.inclusion_policy_digest,
    }
}

fn verify_freeze(
    owner: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    evidence: &SignedLearningEvidenceV1,
    now: u64,
) -> Result<(), TerminalCellError> {
    owner.revalidate_trust_at(now)?;
    let expected = owner.freeze_dataset(freeze_plan(dataset), evidence, now)?;
    if expected != *dataset {
        return Err(TerminalCellError::Unsupported(
            "terminal V3 owner/dataset mismatch",
        ));
    }
    owner.revalidate_dataset_snapshot(dataset, now)?;
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn terminal_payload(owner: &LedgerWriter, frozen: &FrozenTerminalCellV1) -> Vec<u8> {
    let plan = frozen.plan();
    let receipt = frozen.dataset();
    let mut bytes = b"hepta.operator.owner-derived-terminal.v3\0".to_vec();
    push_id(&mut bytes, &plan.artifact_id);
    push_id(&mut bytes, &plan.producer_id);
    push_id(&mut bytes, &receipt.snapshot.snapshot_id);
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
        owner.verifier().trust_digest(),
        owner.trust_distribution_digest(),
        owner.verifier().scope_digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&owner.trust_generation().to_be_bytes());
    bytes.extend_from_slice(&owner.verifier().authority_epoch().to_be_bytes());
    bytes.extend_from_slice(&(plan.minimum_samples_per_cell as u64).to_be_bytes());
    // The extractor supplies a canonical, immutable projection. Include the
    // full action domain so an unsupported action cannot disappear silently.
    for ids in [&plan.sensor_ids, &plan.action_ids] {
        bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
        for id in ids {
            push_id(&mut bytes, id);
        }
    }
    bytes.extend_from_slice(&(plan.samples.len() as u64).to_be_bytes());
    for row in &plan.samples {
        push_id(&mut bytes, &row.sample_id);
        push_id(&mut bytes, &row.sensor_id);
        push_id(&mut bytes, &row.action_id);
        bytes.extend_from_slice(&row.target.raw().to_be_bytes());
        bytes.extend_from_slice(row.evidence_digest.as_array());
    }
    // A fixed-size commitment fits the shared evidence transport limit. This
    // hashes all derived rows; it never drops rows or changes sample counts.
    let mut commitment = b"hepta.operator.owner-derived-terminal-commitment.v3\0".to_vec();
    commitment.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    commitment
}
