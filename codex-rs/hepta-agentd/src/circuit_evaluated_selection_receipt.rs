//! Explicit evaluated-retention profile for the original Selector journal.
//! The public legacy configuration remains a TrainingNoUpdate-only profile.
//! Original T/B pins never replace live reads or a published Cell capability.

use super::*;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;

pub struct OriginalCircuitEvaluatedSelectionReceiptConfigV1 {
    pub context: OriginalCircuitEvaluatedRetentionContextV1,
    pub signer: TrustedLearningSignerV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCircuitEvaluatedSelectionReceiptSourcesV1<'a, C: AnchorWitnessStore> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub cell: &'a PublishedCircuitCellOwnerV1<C>,
    pub trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    pub evaluator: &'a OriginalCellEvaluationCommandClientV1,
}

/// Only an actual original Selector journal read constructs this result.
/// It grants no C execution, publication, signing custody or later CURRENT.
pub struct OriginalCircuitEvaluatedSelectionReceiptV1 {
    context: OriginalCircuitEvaluatedRetentionContextV1,
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
}

impl Clone for OriginalCircuitEvaluatedSelectionReceiptV1 {
    fn clone(&self) -> Self {
        Self {
            context: self.context.clone_for_original_receipt(),
            snapshot: self.snapshot.clone(),
            receipt: self.receipt.clone(),
            attestation: self.attestation.clone(),
        }
    }
}

impl OriginalCircuitEvaluatedSelectionReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }

    pub(crate) fn original_context(&self) -> &OriginalCircuitEvaluatedRetentionContextV1 {
        &self.context
    }
}

pub(super) enum Profile {
    TrainingNoUpdate,
    Evaluated(OriginalCircuitEvaluatedRetentionContextV1),
}

impl Profile {
    pub(super) fn evidence_domain(&self) -> &'static [u8] {
        match self {
            Self::TrainingNoUpdate => b"hepta.agentd.original-circuit-selection-evidence.v1\0",
            Self::Evaluated(_) => {
                b"hepta.agentd.original-circuit-evaluated-selection-evidence.v1\0"
            }
        }
    }

    pub(super) fn require_new(&self, current: u64) -> Result<(), OwnerError> {
        if let Self::Evaluated(context) = self {
            context
                .require_new_original_receipt(current)
                .map_err(|_| OwnerError::Binding("fresh original evaluated Selection profile"))?;
        }
        Ok(())
    }

    pub(super) fn require_signed_separation(
        &self,
        signed: &VerifiedLearningEvidenceV1,
        current: u64,
    ) -> Result<(), Error> {
        if let Self::Evaluated(context) = self {
            for predecessor in context.original_receipt_predecessors(current)? {
                verify_signed_actor_separation(&predecessor, signed, current)?;
            }
        }
        Ok(())
    }
}

impl<C: AnchorWitnessStore> SelectionSources
    for OriginalCircuitEvaluatedSelectionReceiptSourcesV1<'_, C>
{
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }

    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        None
    }

    fn evaluated_owners(
        &self,
    ) -> Option<(
        &OriginalCellQ24TrainingCommandClientV1,
        &OriginalCellEvaluationCommandClientV1,
    )> {
        Some((self.trainer, self.evaluator))
    }

    fn location(&self) -> ObservationLocation {
        ObservationLocation::EvaluatedOwner
    }

    async fn observe(
        &self,
        config: &OriginalCircuitSelectionReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
        Ok(self.cell.read_learning_selection(&coordinator)?)
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitSelectionReceiptOwnerV1<W> {
    /// Original enrolled custody and fresh files only. This constructs the
    /// fixed profile; no observation, role signature or future S is created.
    pub fn create_evaluated(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        Self::from_evaluated_custody(file, witness, config, key, CommandOrigin::FreshCreate)
    }

    /// Recover the same signature store and immutable T/B pins. The recovered
    /// owner can only read an existing S, including when its record is missing.
    pub fn recover_evaluated(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedSelectionReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        Self::from_evaluated_custody(file, witness, config, key, CommandOrigin::Recovered)
    }

    fn from_evaluated_custody(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedSelectionReceiptConfigV1,
        key: SigningKey,
        command_origin: CommandOrigin,
    ) -> Result<Self, Error> {
        let current = now()?;
        if matches!(&command_origin, CommandOrigin::FreshCreate) {
            config.context.require_new_original_receipt(current)?;
        }
        let context = match &command_origin {
            CommandOrigin::FreshCreate => config.context,
            CommandOrigin::Recovered => config.context.into_original_receipt_readback(),
        };
        let (scope, verifier, training_evidence) = context.receipt_configuration();
        let profile = Profile::Evaluated(context);
        let Profile::Evaluated(context) = &profile else {
            return Err(OwnerError::Binding("original evaluated Selection profile").into());
        };
        let config = OriginalCircuitSelectionReceiptConfigV1 {
            decision: context.snapshot().clone(),
            scope,
            signer: config.signer,
            verifier,
            training_evidence,
            maximum_signature_lifetime_seconds: config.maximum_signature_lifetime_seconds,
        };
        if key.verifying_key().to_bytes() != config.signer.verifying_key
            || config.signer.principal.principal_id != config.decision.owners.selector
            || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        {
            return Err(OwnerError::Binding("original evaluated Selector custody").into());
        }
        authenticate_training(&config, &profile, &config.training_evidence, current)?;
        let saved = ProductEvaluationExecutionKeyV1 {
            plan_id: config.decision.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-circuit-evaluated-selection-receipt.v1\0",
                context.receipt_context_binding().as_array(),
                config.signer.principal.principal_id.as_str().as_bytes(),
                &config.signer.verifying_key,
                &config.maximum_signature_lifetime_seconds.to_be_bytes(),
            ]),
        };
        let journal = match &command_origin {
            CommandOrigin::FreshCreate => {
                LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?
            }
            CommandOrigin::Recovered => {
                LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?
            }
        };
        Ok(Self {
            command_origin,
            journal,
            config,
            profile,
            key,
            saved,
            completion_fenced: false,
        })
    }

    pub async fn attest_original_evaluated_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_selection(completed)
    }

    pub async fn readback_evaluated_selection(
        &mut self,
        source: OriginalCircuitEvaluatedSelectionReceiptSourcesV1<'_, impl AnchorWitnessStore>,
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_selection(completed)
    }

    fn completed_evaluated_selection(
        &self,
        completed: (LearningIterationReceiptV1, SignedLearningEvidenceV1),
    ) -> Result<OriginalCircuitEvaluatedSelectionReceiptV1, Error> {
        let Profile::Evaluated(context) = &self.profile else {
            return Err(OwnerError::Binding("original evaluated Selection profile").into());
        };
        let (receipt, attestation) = completed;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(context.snapshot().clone())?;
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        Ok(OriginalCircuitEvaluatedSelectionReceiptV1 {
            context: context.clone_for_original_receipt(),
            snapshot: coordinator.snapshot().clone(),
            receipt,
            attestation,
        })
    }
}

pub(super) fn authenticate_evaluated_training(
    config: &OriginalCircuitSelectionReceiptConfigV1,
    context: &OriginalCircuitEvaluatedRetentionContextV1,
    evidence: &SignedLearningEvidenceV1,
    current: u64,
) -> Result<VerifiedLearningEvidenceV1, Error> {
    if evidence != &config.training_evidence || context.snapshot() != &config.decision {
        return Err(OwnerError::Binding("same original evaluated Selection predecessors").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Selector,
        &config.signer,
        current,
    )?;
    let predecessors = context.original_receipt_predecessors(current)?;
    for original in &predecessors {
        verify_independent_roles(original.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if original.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
    }
    let [training, _evaluation] = predecessors;
    Ok(training)
}
