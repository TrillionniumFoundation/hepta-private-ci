//! Admission checks for the existing durable owner. A prepared operation is a
//! committed recovery obligation; current-use checks never rewrite its history.
use super::*;
use crate::sparse_tick;

/// Host-owned live checks. Implementations must use authenticated current owners
/// and enforce deadline/cancellation; a digest alone is not an admission grant.
pub trait NeuronAdmissionGuard {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronAdmissionError {
    Revoked,
    DeadlineExceeded,
    Cancelled,
    Unavailable,
    BindingMismatch,
}

struct MechanismOnly;
impl NeuronAdmissionGuard for MechanismOnly {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    /// Mechanism/qualification entry. Product callers use `tick_guarded`.
    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        self.tick_guarded(model, input, &mut MechanismOnly)
    }

    /// Check live admission before execution, before durable preparation and
    /// before exposing the result (including historical retries). Once prepared,
    /// reconciliation completes the same operation; it never invokes the model.
    pub fn tick_guarded(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        self.validate_recovered_frontiers()?;
        let model_request = self.model_request(&input)?;
        let input_digest = model_request.input_digest;
        if let Some(stored) = self.operations.find_tick(&input.tick_id)? {
            if stored.input_digest != input_digest {
                return Err(NeuronRuntimeError::OperationConflict);
            }
            let output = self.reconcile_operation(stored)?;
            guard
                .check(&self.config, &input)
                .map_err(NeuronRuntimeError::Admission)?;
            return Ok(output);
        }
        if self.operations.pending()?.is_some() {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }

        self.journal.admit_new_tick(
            JournalScope {
                scope_digest: subject_scope_digest(&input.subject_id)?,
                objective_digest: input.objective_digest,
            },
            input.logical_sequence,
        )?;
        self.operations.admit_new_operation()?;
        let current = self.journal.current()?;
        let expected_checkpoint = current.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        if input.checkpoint_digest != expected_checkpoint {
            return Err(NeuronRuntimeError::CheckpointMismatch);
        }
        let expected_anchor = current.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        });

        let started = Instant::now();
        let model_output = model.execute(&model_request)?;
        validate_model_output(&self.config, &model_output)?;
        let native_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(&self.config, &input),
            input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) =
            sparse_tick(&self.native, &native_tick, self.journal.current()?)
                .map_err(JournalError::Mechanism)?;
        let output = self.build_output(
            &input.tick_id,
            &model_output,
            &checkpoint,
            &sparse_receipt,
            started,
        )?;
        let next_anchor = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        let prepared = PreparedNeuronOperationV1::new(
            input_digest,
            input.tick_id.clone(),
            expected_anchor,
            next_anchor,
            native_tick,
            output,
        )?;
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        self.operations.prepare(prepared.clone())?;
        let output = self.reconcile_operation(prepared)?;
        guard
            .check(&self.config, &input)
            .map_err(NeuronRuntimeError::Admission)?;
        Ok(output)
    }
}
