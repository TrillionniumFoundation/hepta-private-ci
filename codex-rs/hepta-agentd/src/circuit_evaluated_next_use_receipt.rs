//! Explicit Observer receipts for a completed evaluated-retention C.
//! The original five-cut S and all T/B/S signatures stay pinned. The sources
//! carry actual Cell/TaskSource owners and read-only predecessor capabilities.

use super::*;
#[path = "circuit_evaluated_next_use_remote.rs"]
mod remote;
pub use remote::OriginalCircuitEvaluatedNextUseRemoteSourcesV1;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

pub struct OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
    pub selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    pub signer: TrustedLearningSignerV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCircuitEvaluatedNextUseReceiptSourcesV1<
    'a,
    C: AnchorWitnessStore,
    S: AnchorWitnessStore,
> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub cell: &'a PublishedCircuitCellOwnerV1<C>,
    pub source: &'a CircuitTaskSourceReadbackV1<S>,
    pub identity: &'a AgentdIdentity,
    pub trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    pub evaluator: &'a OriginalCellEvaluationCommandClientV1,
    pub selector: &'a LearningIterationEvidenceClientV1,
}

/// An original Observer journal result, never permission to execute a task.
pub struct OriginalCircuitEvaluatedNextUseReceiptV1 {
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    snapshot: LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
}

impl OriginalCircuitEvaluatedNextUseReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }

    pub fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }

    pub(crate) fn original_selection(&self) -> &OriginalCircuitEvaluatedSelectionReceiptV1 {
        &self.selection
    }
}

pub(super) enum Profile {
    Legacy,
    Evaluated(OriginalCircuitEvaluatedSelectionReceiptV1),
}

impl Profile {
    pub(super) fn require_new(&self, current: u64) -> Result<(), OwnerError> {
        if let Self::Evaluated(selection) = self {
            selection
                .original_context()
                .require_new_original_receipt(current)
                .map_err(|_| OwnerError::Binding("fresh original evaluated C profile"))?;
        }
        Ok(())
    }

    pub(super) fn require_signed_separation(
        &self,
        signed: &VerifiedLearningEvidenceV1,
        current: u64,
    ) -> Result<(), Error> {
        if let Self::Evaluated(selection) = self {
            for predecessor in selection.original_receipt_predecessors(current)? {
                verify_signed_actor_separation(&predecessor, signed, current)?;
            }
        }
        Ok(())
    }
}

impl<C: AnchorWitnessStore, S: AnchorWitnessStore> NextUseSources
    for OriginalCircuitEvaluatedNextUseReceiptSourcesV1<'_, C, S>
{
    fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.snapshot
    }

    fn trainer(&self) -> Option<&LearningIterationEvidenceClientV1> {
        None
    }

    fn selector(&self) -> &LearningIterationEvidenceClientV1 {
        self.selector
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
        config: &OriginalCircuitNextUseReceiptConfigV1,
    ) -> Result<LearningIterationObservationV1, Error> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.selection.clone())?;
        Ok(self
            .cell
            .read_learning_next_use(&coordinator, self.source, self.identity)?)
    }
}

impl<W: AnchorWitnessStore> OriginalCircuitNextUseReceiptOwnerV1<W> {
    /// Construct custody and immutable pins only. Attesting still requires the
    /// actual completed C and current original T/B/S owners on both sides.
    pub fn create_evaluated(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedNextUseReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        Self::from_evaluated_custody(file, witness, config, key, CommandOrigin::FreshCreate)
    }

    /// Cold recovery cannot create a missing C receipt or refresh any window.
    pub fn recover_evaluated(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedNextUseReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        Self::from_evaluated_custody(file, witness, config, key, CommandOrigin::Recovered)
    }

    fn from_evaluated_custody(
        file: File,
        witness: W,
        config: OriginalCircuitEvaluatedNextUseReceiptConfigV1,
        key: SigningKey,
        command_origin: CommandOrigin,
    ) -> Result<Self, Error> {
        let current = now()?;
        if matches!(&command_origin, CommandOrigin::FreshCreate) {
            config
                .selection
                .original_context()
                .require_new_original_receipt(current)?;
        }
        let selection = match &command_origin {
            CommandOrigin::FreshCreate => config.selection,
            CommandOrigin::Recovered => config.selection.into_original_receipt_readback(),
        };
        selection.original_receipt_predecessors(current)?;
        let (scope, verifier, training_evidence) =
            selection.original_context().receipt_configuration();
        let config = OriginalCircuitNextUseReceiptConfigV1 {
            selection: selection.snapshot().clone(),
            scope,
            signer: config.signer,
            verifier,
            training_evidence,
            selection_evidence: selection.attestation().clone(),
            maximum_signature_lifetime_seconds: config.maximum_signature_lifetime_seconds,
        };
        if key.verifying_key().to_bytes() != config.signer.verifying_key
            || config.signer.principal.principal_id != config.selection.owners.next_use_observer
            || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        {
            return Err(OwnerError::Binding("original evaluated Observer custody").into());
        }
        let binding = selection.original_receipt_binding();
        let profile = Profile::Evaluated(selection);
        authenticate_predecessors(
            &config,
            &profile,
            &[
                config.training_evidence.clone(),
                config.selection_evidence.clone(),
            ],
            current,
        )?;
        let saved = ProductEvaluationExecutionKeyV1 {
            plan_id: config.selection.request.operation_id.clone(),
            binding_digest: Digest32::of_parts(&[
                b"hepta.agentd.original-circuit-evaluated-next-use-receipt.v1\0",
                binding.as_array(),
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
            journal,
            config,
            profile,
            key,
            saved,
            command_origin,
            completion_fenced: false,
        })
    }

    pub async fn attest_original_evaluated_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseReceiptSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = match self.command_origin {
            CommandOrigin::FreshCreate => self.attest_source(source).await?,
            CommandOrigin::Recovered => self.readback_source(source).await?,
        };
        self.completed_evaluated_next_use(completed)
    }

    pub async fn readback_evaluated_completion(
        &mut self,
        source: OriginalCircuitEvaluatedNextUseReceiptSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let completed = self.readback_source(source).await?;
        self.completed_evaluated_next_use(completed)
    }

    fn completed_evaluated_next_use(
        &self,
        completed: (LearningIterationReceiptV1, SignedLearningEvidenceV1),
    ) -> Result<OriginalCircuitEvaluatedNextUseReceiptV1, Error> {
        let Profile::Evaluated(selection) = &self.profile else {
            return Err(OwnerError::Binding("original evaluated C profile").into());
        };
        let (receipt, attestation) = completed;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(selection.snapshot().clone())?;
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        Ok(OriginalCircuitEvaluatedNextUseReceiptV1 {
            selection: selection.clone(),
            snapshot: coordinator.snapshot().clone(),
            receipt,
            attestation,
        })
    }
}

pub(super) fn authenticate_predecessors(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    profile: &Profile,
    evidence: &[SignedLearningEvidenceV1; 2],
    current: u64,
) -> Result<[VerifiedLearningEvidenceV1; 2], Error> {
    let Profile::Evaluated(selection) = profile else {
        return super::authenticate_predecessors(config, evidence, current);
    };
    let (scope, verifier, training) = selection.original_context().receipt_configuration();
    if selection.snapshot() != &config.selection
        || scope.binding() != config.scope.binding()
        || verifier.trust_digest() != config.verifier.trust_digest()
        || verifier.scope_digest() != config.verifier.scope_digest()
        || verifier.objective_digest() != config.verifier.objective_digest()
        || training != config.training_evidence
        || selection.attestation() != &config.selection_evidence
        || evidence
            != &[
                config.training_evidence.clone(),
                config.selection_evidence.clone(),
            ]
    {
        return Err(OwnerError::Binding("same original evaluated C predecessors").into());
    }
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Observer,
        &config.signer,
        current,
    )?;
    let originals = selection.original_receipt_predecessors(current)?;
    for original in &originals {
        verify_independent_roles(original.principal(), &config.signer.principal, current)
            .map_err(SignedEvidenceError::from)?;
        if original.controller_id() == &config.signer.controller_id {
            return Err(SignedEvidenceError::ControllerCollision.into());
        }
    }
    let [training, _evaluation, selection] = originals;
    Ok([training, selection])
}

pub(super) fn receipt(
    config: &OriginalCircuitNextUseReceiptConfigV1,
    profile: &Profile,
    observation: &LearningIterationObservationV1,
    observed_unix_seconds: u64,
) -> Result<LearningIterationReceiptV1, Error> {
    let Profile::Evaluated(_) = profile else {
        return super::receipt(config, observation, observed_unix_seconds);
    };
    if !matches!(
        observation,
        LearningIterationObservationV1::RetainedModelNextUse { .. }
    ) {
        return Err(OwnerError::Binding("actual original retained-model C completion").into());
    }
    super::receipt_with_domain(
        config,
        observation,
        observed_unix_seconds,
        b"hepta.agentd.original-circuit-evaluated-next-use-evidence.v1\0",
    )
}
