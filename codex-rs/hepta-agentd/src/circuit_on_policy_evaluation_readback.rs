//! Live, readonly custody retained after original B data release.
//!
//! This capability has no release, execute or signing entry point. A cold
//! instance proves only the original cohort is still current; the panel must
//! separately read completed execution, holdout and qualification owners.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitOnPolicyCohortV1;
use super::binding;
use crate::CellEvaluationPlanV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationPanelTaskV1;

/// Metadata from one actual read. It is neither a serializable capability nor
/// a lease. Its equality excludes the observation time so two unchanged reads
/// can bracket other original owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyCohortCurrentV1 {
    binding: Digest32,
    manifest: Digest32,
    dataset: DatasetSnapshotReceiptV3,
    freeze_payload: Vec<u8>,
    commitment: Vec<u8>,
}

impl OriginalCircuitOnPolicyCohortCurrentV1 {
    pub fn binding(&self) -> Digest32 {
        self.binding
    }
}

/// Owns the same original Source views and independent ledger after release.
/// No owner, row, signature key or writable store can be extracted.
pub struct OriginalCircuitOnPolicyCohortReadbackV1 {
    original: OriginalCircuitOnPolicyCohortV1,
    plan: CellEvaluationPlanV1,
    last: Option<OriginalCircuitOnPolicyCohortCurrentV1>,
    fenced: bool,
    #[cfg(test)]
    fixture_clock: Option<u64>,
}

impl OriginalCircuitOnPolicyCohortReadbackV1 {
    pub(super) fn retaining(
        original: OriginalCircuitOnPolicyCohortV1,
        plan: CellEvaluationPlanV1,
    ) -> Self {
        Self {
            original,
            plan,
            last: None,
            fenced: false,
            #[cfg(test)]
            fixture_clock: None,
        }
    }

    /// Read on the original host's blocking lane. All Source publications and
    /// the independent ledger/witness CURRENT are actually read again.
    pub fn read_current(&mut self) -> Result<OriginalCircuitOnPolicyCohortCurrentV1, Error> {
        #[cfg(test)]
        if let Some(current) = self.fixture_clock {
            return self.read_current_with_clock(|| Ok(current));
        }
        self.read_current_with_clock(super::now)
    }

    fn read_current_with_clock(
        &mut self,
        clock: impl FnMut() -> Result<u64, Error>,
    ) -> Result<OriginalCircuitOnPolicyCohortCurrentV1, Error> {
        if self.fenced {
            return Err(Error::Indeterminate);
        }
        self.fenced = true;
        let material = self.original.read_current_with_clock(clock)?;
        let frozen = &self.plan.product_plan().frozen_plan;
        if material.manifest != frozen.final_holdout_digest
            || material.dataset.snapshot.dataset_digest != frozen.dataset_digest
        {
            return Err(Error::Binding(
                "same original cohort and frozen evaluation plan",
            ));
        }
        let mut bytes = b"hepta.circuit.original-on-policy-cohort-current.v1\0".to_vec();
        for digest in [
            frozen.plan_digest,
            material.manifest,
            material.dataset.snapshot.dataset_digest,
            material.dataset.snapshot.ledger_head_digest,
            material.dataset.correction_cut_digest,
            material.dataset.revocation_cut_digest,
            self.original.rule_digest,
            self.original.config.registration.evaluation_profile(),
            self.original.config.training.head_digest,
            self.original.config.scope.binding(),
            self.original.owners.ledger.binding_digest(),
            self.original.owners.ledger.trust_distribution_digest(),
            material.pairing.digest().map_err(|_| Error::Binding("exact frozen original pair contract"))?,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for evidence in [
            &self.original.config.training_evidence,
            &self.original.config.freeze_evidence,
        ] {
            let mut full = evidence.signing_bytes();
            full.extend_from_slice(&evidence.signature);
            bytes.extend_from_slice(&(full.len() as u64).to_be_bytes());
            bytes.extend_from_slice(&full);
        }
        bytes.extend_from_slice(&(material.freeze_payload.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&material.freeze_payload);
        let observed = OriginalCircuitOnPolicyCohortCurrentV1 {
            binding: Digest32::of_bytes(&bytes),
            manifest: material.manifest,
            dataset: material.dataset,
            freeze_payload: material.freeze_payload,
            commitment: bytes,
        };
        if self.last.as_ref().is_some_and(|last| last != &observed) {
            return Err(Error::Binding(
                "same original cohort CURRENT and full signatures",
            ));
        }
        self.last = Some(observed.clone());
        self.fenced = false;
        Ok(observed)
    }

    /// Only the concrete original panel constructor may bind this capability
    /// to a member. No supplied digest can replace the complete original cut.
    pub(crate) fn require_original_member(
        &self,
        registration: &OriginalCellEvaluationPanelRegistrationV1,
        task: &OriginalCellEvaluationPanelTaskV1,
        training: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        plan: &CellEvaluationPlanV1,
        training_evidence: &SignedLearningEvidenceV1,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        let config = &self.original.config;
        let registered = std::iter::once(registration.primary())
            .chain(registration.retention())
            .find(|member| member.plan_id == config.rule.plan_id)
            .ok_or(Error::Binding("original registered cohort member"))?;
        if self.fenced
            || self.original.fenced
            || registration != &config.registration
            || task != registered
            || task.task_digest != config.rule.task_digest
            || task.cohort_rule_digest != self.original.rule_digest
            || training != &config.training
            || scope != &config.scope
            || plan != &self.plan
            || training_evidence != &config.training_evidence
            || verifier.trust_digest() != config.verifier.trust_digest()
            || verifier.scope_digest() != config.verifier.scope_digest()
            || verifier.objective_digest() != config.verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original panel, Training, scope, plan and custody",
            ));
        }
        Ok(())
    }

    /// Pure final authentication of the exact material most recently read.
    /// The caller is the closed panel's internal clock, never a public timestamp.
    /// There is no physical, peer or witness I/O after this common final clock.
    pub(crate) fn authenticate_current(
        &mut self,
        observed: &OriginalCircuitOnPolicyCohortCurrentV1,
        current: u64,
    ) -> Result<(), Error> {
        if self.fenced || self.original.fenced {
            return Err(Error::Indeterminate);
        }
        self.fenced = true;
        if self.last.as_ref() != Some(observed) || current < self.original.last_observed_at {
            return Err(Error::Binding(
                "last actual cohort read and nondecreasing clock",
            ));
        }
        let config = &self.original.config;
        let training = binding::authenticate_training(config, current)?;
        let evaluator = config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &config.freeze_evidence,
            &observed.freeze_payload,
            current,
        )?;
        verify_signed_role_separation(&training.generator, &evaluator, current)?;
        // These existing ledger methods authenticate and inspect the logical
        // cut already physically checked above; they perform no external I/O.
        if LedgerWriter::freeze_dataset(
            &self.original.owners.ledger,
            config.freeze_plan.clone(),
            &config.freeze_evidence,
            current,
        )? != observed.dataset
        {
            return Err(Error::Binding(
                "exact original signed B freeze remains active",
            ));
        }
        let _ = LedgerWriter::read_dataset_records(
            &self.original.owners.ledger,
            &observed.dataset,
            current,
        )?;
        self.original.last_observed_at = current;
        self.fenced = false;
        Ok(())
    }

    /// Closed readonly export of the last actually observed B cut. No owner,
    /// rows, key or receipt seal can be reconstructed from these bytes.
    pub(crate) fn original_model_commitment(
        &self,
        observed: &OriginalCircuitOnPolicyCohortCurrentV1,
    ) -> Result<(Vec<u8>, Vec<u8>, SignedLearningEvidenceV1), Error> {
        if self.fenced
            || self.original.fenced
            || self.last.as_ref() != Some(observed)
            || Digest32::of_bytes(&observed.commitment) != observed.binding
        {
            return Err(Error::Indeterminate);
        }
        Ok((
            observed.commitment.clone(),
            observed.freeze_payload.clone(),
            self.original.config.freeze_evidence.clone(),
        ))
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}


#[cfg(test)]
impl OriginalCircuitOnPolicyCohortReadbackV1 {
    pub(crate) fn fixture_bytes(&mut self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok(self.original.owners.ledger.qualification_file_bytes(
            /*maximum_bytes*/ 8 * 1024 * 1024,
        )?)
    }
}
