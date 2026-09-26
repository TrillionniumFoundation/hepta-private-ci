//! Live stage fencing for the existing canonical Neuron product call.
use super::*;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use tokio_util::sync::CancellationToken;

pub(super) struct NeuronStageAdmission {
    pub snapshot: CanonicalIntelligenceSnapshotV1,
    pub authority_file: PathBuf,
    pub authority_verifier: IntelligenceAuthorityVerifierV1,
    pub deadline: Instant,
    pub cancellation: CancellationToken,
}

impl NeuronStageAdmission {
    pub(super) fn begin_stage(&mut self, budget_micros: u64) -> Result<(), NeuronAdmissionError> {
        let deadline = Instant::now()
            .checked_add(Duration::from_micros(budget_micros))
            .ok_or(NeuronAdmissionError::DeadlineExceeded)?;
        self.deadline = self.deadline.min(deadline);
        Ok(())
    }
}

impl NeuronAdmissionGuard for NeuronStageAdmission {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        if input.body_generation != Some(self.snapshot.body_generation().get())
            || input.objective_digest != self.snapshot.objective_digest()
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        // Independently authenticated selection/calibration admission is also
        // checked by the guard installed on AgentdNeuronOwner::into_shared.
        if input.logical_sequence < config.calibration.valid_from_sequence
            || input.logical_sequence > config.calibration.expires_after_sequence
        {
            return Err(NeuronAdmissionError::Revoked);
        }
        let mut oracle = FileBackedFreshnessOracleV1::new(
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        );
        validate_current_snapshot(&self.snapshot, &mut oracle)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        Ok(())
    }
}

pub(super) fn failure(
    stage: CanonicalStageV1,
    error: &NeuronRuntimeError,
) -> CanonicalPortFailureV1 {
    let class = match error {
        NeuronRuntimeError::Admission(NeuronAdmissionError::DeadlineExceeded) => {
            CanonicalPortFailureClassV1::TimedOut
        }
        NeuronRuntimeError::Admission(NeuronAdmissionError::Unavailable)
        | NeuronRuntimeError::InvalidCalibration => CanonicalPortFailureClassV1::Unavailable,
        NeuronRuntimeError::WitnessAfterCommit { .. }
        | NeuronRuntimeError::PendingReconciliation
        | NeuronRuntimeError::Operation(codex_hepta_neuron::OperationStoreError::Indeterminate)
        | NeuronRuntimeError::Operation(codex_hepta_neuron::OperationStoreError::Poisoned)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Indeterminate)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Poisoned)
        | NeuronRuntimeError::Model(codex_hepta_neuron::NeuronModelError::Indeterminate) => {
            CanonicalPortFailureClassV1::Indeterminate
        }
        _ => CanonicalPortFailureClassV1::Rejected,
    };
    CanonicalPortFailureV1 {
        class,
        evidence_digest: Digest32::of_bytes(
            format!("hepta.agentd.neuron-stage.v1:{stage:?}:{error:?}").as_bytes(),
        ),
    }
}
